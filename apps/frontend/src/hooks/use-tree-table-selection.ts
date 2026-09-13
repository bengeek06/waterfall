import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { filterVisibleTreeRows, isRowSelectable, toggleUid, type TreeRowIdentity } from "@/lib/tree-rows";

/** The subset of a mouse/keyboard event `selectRow` actually reads. */
export type TreeRowSelectEvent = { ctrlKey: boolean; metaKey: boolean; shiftKey: boolean };

/**
 * Spread onto *every* focusable control rendered inside a tree row -- a fold/unfold chevron, a
 * "Supprimer" button, an inline `<Input>`/`<select>`/`<Checkbox>`.
 *
 * `onRowKeyDown` below calls `preventDefault()` on Enter and Space (among others) to drive the row
 * selection. Cancelling a `keydown` on a `<button>` also cancels its *native activation*: without
 * this guard, a user who tabs to "Supprimer" and presses Enter or Space deletes nothing and moves
 * the row selection instead -- an operable-looking control that cannot be operated (WCAG 2.1.1).
 *
 * Exported as a spreadable props object, deliberately, rather than left to each call site to
 * remember as its own `(event) => event.stopPropagation()` lambda: three of the five in-row
 * controls had been missed exactly that way, and #336/#337 will add more.
 */
export const stopRowKeys = {
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => event.stopPropagation(),
} as const;

// E14-09 (#335) / resolves #316: collapse/expand, single/multi/range selection, focus tracking and
// keyboard navigation over any depth-first-ordered row list -- the socle both the planning table
// (previously use-planning-tree-selection.ts) and the devis grid (previously
// use-estimate-grid-selection.ts) now share. The only thing it knows about a concrete row is its
// `TreeRowIdentity`; anything else (columns, subtotals, whether a move is legal) stays with the
// table that owns it.
//
// Keyboard navigation used to exist on the planning side only, which #316 documented as the
// visible consequence of the duplication: carrying it here makes it available to every consumer
// at once instead of having to be written a second time.
//
// `rows` must already be in depth-first document order (parent before its descendants): the
// visibility filter and the range-selection anchor both rely on it.
export function useTreeTableSelection<TRow>(rows: readonly TRow[], identity: TreeRowIdentity<TRow>) {
  const [collapsedUids, setCollapsedUids] = useState<Set<number>>(new Set());
  const [selectedUids, setSelectedUids] = useState<Set<number>>(new Set());
  const [focusedUid, setFocusedUid] = useState<number | null>(null);
  const rowRefs = useRef(new Map<number, HTMLTableRowElement>());

  const visibleRows = useMemo(
    () => filterVisibleTreeRows(rows, collapsedUids, identity),
    [rows, collapsedUids, identity],
  );

  // Two separate indexes, because navigation and range selection do not walk the same list: arrow
  // keys move across *every* visible row (including a row that can never be selected, so the user
  // can still travel through it), whereas Shift+click spans only the selectable ones (the devis
  // grid's task rows sit between cost lines and must not be swept into the selection).
  const navigableRows = useMemo(() => visibleRows.filter((row) => identity.uidOf(row) !== null), [visibleRows, identity]);
  const navigableIndexByUid = useMemo(
    () => new Map(navigableRows.map((row, index) => [identity.uidOf(row) as number, index])),
    [navigableRows, identity],
  );
  const selectableRows = useMemo(
    () => visibleRows.filter((row) => isRowSelectable(row, identity)),
    [visibleRows, identity],
  );
  const selectableIndexByUid = useMemo(
    () => new Map(selectableRows.map((row, index) => [identity.uidOf(row) as number, index])),
    [selectableRows, identity],
  );

  // The single row carrying `tabIndex={0}`: the focused one, or -- before anything has been
  // focused -- the first navigable row, so the table is reachable with one Tab press and arrow
  // navigation has somewhere to start.
  //
  // `focusedUid` is checked against the *current* navigable rows rather than trusted as-is: it
  // survives the row that carries it disappearing (folding an ancestor, reloading a shorter tree),
  // and a `focusedUid` pointing at a row that is no longer rendered would leave the table with no
  // tab stop at all -- the previously focused element having been unmounted, the focus falls back
  // to <body> and Tab can never re-enter the table. Falling back to the first navigable row keeps
  // the table permanently reachable.
  const firstNavigableUid = navigableRows.length ? identity.uidOf(navigableRows[0]) : null;
  const focusableUid = focusedUid !== null && navigableIndexByUid.has(focusedUid) ? focusedUid : firstNavigableUid;

  useEffect(() => {
    if (focusedUid === null) {
      return;
    }
    const rowElement = rowRefs.current.get(focusedUid);
    // Do not steal focus back to the row when it is already inside one of its inline edit controls.
    if (rowElement && !rowElement.contains(document.activeElement)) {
      rowElement.focus();
    }
  }, [focusedUid]);

  function toggleCollapsed(uid: number) {
    setCollapsedUids((current) => toggleUid(current, uid));
  }

  function selectRow(row: TRow, event: TreeRowSelectEvent) {
    if (!isRowSelectable(row, identity)) {
      return;
    }
    const uid = identity.uidOf(row) as number;
    setSelectedUids((current) => {
      if (event.shiftKey && focusedUid !== null && selectableIndexByUid.has(focusedUid)) {
        const start = Math.min(selectableIndexByUid.get(focusedUid)!, selectableIndexByUid.get(uid)!);
        const end = Math.max(selectableIndexByUid.get(focusedUid)!, selectableIndexByUid.get(uid)!);
        return new Set(selectableRows.slice(start, end + 1).map((candidate) => identity.uidOf(candidate) as number));
      }
      if (event.ctrlKey || event.metaKey) {
        return toggleUid(current, uid);
      }
      return new Set([uid]);
    });
    setFocusedUid(uid);
  }

  function focusSibling(row: TRow, offset: number) {
    const uid = identity.uidOf(row);
    const index = (uid !== null ? navigableIndexByUid.get(uid) : undefined) ?? 0;
    const sibling = navigableRows[index + offset];
    if (sibling) {
      setFocusedUid(identity.uidOf(sibling));
    }
  }

  function expandOrFocusChild(row: TRow) {
    const uid = identity.uidOf(row);
    if (uid === null || !identity.hasChildrenOf(row)) {
      return;
    }
    if (collapsedUids.has(uid)) {
      toggleCollapsed(uid);
    } else {
      focusSibling(row, 1);
    }
  }

  function collapseOrFocusParent(row: TRow) {
    const uid = identity.uidOf(row);
    if (uid !== null && identity.hasChildrenOf(row) && !collapsedUids.has(uid)) {
      toggleCollapsed(uid);
      return;
    }
    // A row's raw `parentUidOf` is not guaranteed to resolve to a row that is actually navigable:
    // a row whose parent is outside the loaded tree is rendered as a root while still carrying its
    // original parent uid (the planning's re-rooted orphans), and a parent can also simply be
    // hidden. Focusing such a uid would move the tab stop onto a row that does not exist, so the
    // focus is only moved when the target is really there.
    const parentUid = identity.parentUidOf(row);
    if (parentUid !== null && navigableIndexByUid.has(parentUid)) {
      setFocusedUid(parentUid);
    }
  }

  const rowKeyHandlers: Record<string, (row: TRow) => void> = {
    ArrowDown: (row) => focusSibling(row, 1),
    ArrowUp: (row) => focusSibling(row, -1),
    ArrowRight: expandOrFocusChild,
    ArrowLeft: collapseOrFocusParent,
    Enter: (row) => selectRow(row, { ctrlKey: false, metaKey: false, shiftKey: false }),
    " ": (row) => selectRow(row, { ctrlKey: true, metaKey: false, shiftKey: false }),
  };

  function onRowKeyDown(event: KeyboardEvent<HTMLTableRowElement>, row: TRow) {
    const handler = rowKeyHandlers[event.key];
    if (!handler) {
      return;
    }
    event.preventDefault();
    handler(row);
  }

  function clearSelection() {
    setSelectedUids(new Set());
  }

  /**
   * Registers/unregisters a rendered row element, so the focus effect above can move the browser
   * focus to the row matching `focusedUid`. Meant to be passed straight to a `<TableRow ref={}>`.
   */
  function registerRow(row: TRow, element: HTMLTableRowElement | null) {
    const uid = identity.uidOf(row);
    if (uid === null) {
      return;
    }
    if (element) {
      rowRefs.current.set(uid, element);
    } else {
      rowRefs.current.delete(uid);
    }
  }

  function reset() {
    setCollapsedUids(new Set());
    setSelectedUids(new Set());
    setFocusedUid(null);
  }

  return {
    visibleRows,
    rowRefs,
    registerRow,
    collapsedUids,
    selectedUids,
    focusedUid,
    focusableUid,
    setFocusedUid,
    toggleCollapsed,
    selectRow,
    onRowKeyDown,
    clearSelection,
    reset,
  };
}
