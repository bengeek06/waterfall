import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useTreeTableSelection } from "@/hooks/use-tree-table-selection";
import type { TreeRowIdentity } from "@/lib/tree-rows";

// Deliberately not a planning row nor a devis grid row: these tests verify the shared base on its
// own, so "the planning table and the devis grid consume the same primitives" is a claim about
// something that is actually testable without either table.
type FakeRow = { uid: number | null; parentUid: number | null; hasChildren: boolean; kind: "group" | "item" };

const identity: TreeRowIdentity<FakeRow> = {
  uidOf: (row) => row.uid,
  parentUidOf: (row) => row.parentUid,
  hasChildrenOf: (row) => row.hasChildren,
};

// Same identity, but "group" rows can never be selected -- the devis grid's own rule for task
// rows, expressed through the base instead of reimplemented inside it.
const identityWithUnselectableGroups: TreeRowIdentity<FakeRow> = {
  ...identity,
  isSelectable: (row) => row.kind !== "group",
};

function group(uid: number, parentUid: number | null): FakeRow {
  return { uid, parentUid, hasChildren: true, kind: "group" };
}

function item(uid: number, parentUid: number | null): FakeRow {
  return { uid, parentUid, hasChildren: false, kind: "item" };
}

// 1 (group) > [2, 3], 4 (group) > [5]
const rows: FakeRow[] = [group(1, null), item(2, 1), item(3, 1), group(4, null), item(5, 4)];

const plainClick = { ctrlKey: false, metaKey: false, shiftKey: false };
const ctrlClick = { ctrlKey: true, metaKey: false, shiftKey: false };
const metaClick = { ctrlKey: false, metaKey: true, shiftKey: false };
const shiftClick = { ctrlKey: false, metaKey: false, shiftKey: true };

function renderSelection(identityUnderTest: TreeRowIdentity<FakeRow> = identity) {
  return renderRowsSelection(rows, identityUnderTest);
}

function renderRowsSelection(rowsUnderTest: FakeRow[], identityUnderTest: TreeRowIdentity<FakeRow> = identity) {
  return renderHook(() => useTreeTableSelection(rowsUnderTest, identityUnderTest));
}

describe("useTreeTableSelection collapse/expand", () => {
  it("starts with every row visible and nothing collapsed", () => {
    const { result } = renderSelection();
    expect(result.current.visibleRows.map((row) => row.uid)).toEqual([1, 2, 3, 4, 5]);
    expect([...result.current.collapsedUids]).toEqual([]);
  });

  it("hides a collapsed row's descendants and restores them when toggled back", () => {
    const { result } = renderSelection();

    act(() => result.current.toggleCollapsed(1));
    expect(result.current.visibleRows.map((row) => row.uid)).toEqual([1, 4, 5]);
    expect([...result.current.collapsedUids]).toEqual([1]);

    act(() => result.current.toggleCollapsed(1));
    expect(result.current.visibleRows.map((row) => row.uid)).toEqual([1, 2, 3, 4, 5]);
  });

  it("collapses several subtrees independently", () => {
    const { result } = renderSelection();

    act(() => result.current.toggleCollapsed(1));
    act(() => result.current.toggleCollapsed(4));

    expect(result.current.visibleRows.map((row) => row.uid)).toEqual([1, 4]);
  });
});

describe("useTreeTableSelection row selection", () => {
  it("replaces the selection on a plain click and tracks the focused row", () => {
    const { result } = renderSelection();

    act(() => result.current.selectRow(rows[1], plainClick));
    expect([...result.current.selectedUids]).toEqual([2]);
    expect(result.current.focusedUid).toBe(2);

    act(() => result.current.selectRow(rows[2], plainClick));
    expect([...result.current.selectedUids]).toEqual([3]);
    expect(result.current.focusedUid).toBe(3);
  });

  it("adds and removes a row from the selection on Ctrl+click", () => {
    const { result } = renderSelection();

    act(() => result.current.selectRow(rows[1], plainClick));
    act(() => result.current.selectRow(rows[2], ctrlClick));
    expect([...result.current.selectedUids].sort()).toEqual([2, 3]);

    act(() => result.current.selectRow(rows[2], ctrlClick));
    expect([...result.current.selectedUids]).toEqual([2]);
  });

  it("treats Cmd+click like Ctrl+click, for macOS", () => {
    const { result } = renderSelection();

    act(() => result.current.selectRow(rows[1], plainClick));
    act(() => result.current.selectRow(rows[4], metaClick));

    expect([...result.current.selectedUids].sort()).toEqual([2, 5]);
  });

  it("selects the whole range between the focused row and the clicked one on Shift+click", () => {
    const { result } = renderSelection();

    act(() => result.current.selectRow(rows[1], plainClick));
    act(() => result.current.selectRow(rows[4], shiftClick));

    expect([...result.current.selectedUids].sort()).toEqual([2, 3, 4, 5]);
  });

  it("selects the same range when the Shift+click goes upwards", () => {
    const { result } = renderSelection();

    act(() => result.current.selectRow(rows[4], plainClick));
    act(() => result.current.selectRow(rows[1], shiftClick));

    expect([...result.current.selectedUids].sort()).toEqual([2, 3, 4, 5]);
  });

  it("spans the range over visible rows only, skipping a collapsed subtree", () => {
    const { result } = renderSelection();

    act(() => result.current.toggleCollapsed(1));
    act(() => result.current.selectRow(rows[0], plainClick));
    act(() => result.current.selectRow(rows[4], shiftClick));

    expect([...result.current.selectedUids].sort()).toEqual([1, 4, 5]);
  });

  it("falls back to a single selection when Shift+click has no usable anchor", () => {
    const { result } = renderSelection();

    act(() => result.current.selectRow(rows[2], shiftClick));

    expect([...result.current.selectedUids]).toEqual([3]);
  });

  it("clears the selection without touching what is collapsed", () => {
    const { result } = renderSelection();

    act(() => result.current.toggleCollapsed(1));
    act(() => result.current.selectRow(rows[3], plainClick));
    act(() => result.current.clearSelection());

    expect([...result.current.selectedUids]).toEqual([]);
    expect([...result.current.collapsedUids]).toEqual([1]);
  });

  it("resets collapse, selection and focus at once", () => {
    const { result } = renderSelection();

    act(() => result.current.toggleCollapsed(1));
    act(() => result.current.selectRow(rows[3], plainClick));
    act(() => result.current.reset());

    expect([...result.current.collapsedUids]).toEqual([]);
    expect([...result.current.selectedUids]).toEqual([]);
    expect(result.current.focusedUid).toBeNull();
  });
});

describe("useTreeTableSelection with rows the identity excludes from selection", () => {
  it("ignores a click on an unselectable row entirely", () => {
    const { result } = renderSelection(identityWithUnselectableGroups);

    act(() => result.current.selectRow(rows[0], plainClick));

    expect([...result.current.selectedUids]).toEqual([]);
    expect(result.current.focusedUid).toBeNull();
  });

  it("leaves unselectable rows out of a Shift+click range", () => {
    const { result } = renderSelection(identityWithUnselectableGroups);

    act(() => result.current.selectRow(rows[1], plainClick));
    act(() => result.current.selectRow(rows[4], shiftClick));

    expect([...result.current.selectedUids].sort()).toEqual([2, 3, 5]);
  });

  it("still lets the arrow keys travel through an unselectable row", () => {
    const { result } = renderSelection(identityWithUnselectableGroups);

    act(() => result.current.onRowKeyDown(keyEvent("ArrowDown"), rows[2]));
    expect(result.current.focusedUid).toBe(4);

    act(() => result.current.onRowKeyDown(keyEvent("ArrowDown"), rows[3]));
    expect(result.current.focusedUid).toBe(5);
  });
});

// The hook only ever reads `key` off the event and calls preventDefault, so a minimal stub is
// enough and keeps these tests independent of any rendered table.
function keyEvent(key: string) {
  return { key, preventDefault: () => {} } as unknown as Parameters<
    ReturnType<typeof useTreeTableSelection<FakeRow>>["onRowKeyDown"]
  >[0];
}

describe("useTreeTableSelection keyboard navigation", () => {
  it("moves the focus down and up through the visible rows", () => {
    const { result } = renderSelection();

    act(() => result.current.onRowKeyDown(keyEvent("ArrowDown"), rows[0]));
    expect(result.current.focusedUid).toBe(2);

    act(() => result.current.onRowKeyDown(keyEvent("ArrowUp"), rows[1]));
    expect(result.current.focusedUid).toBe(1);
  });

  it("stays put at the first and last visible row", () => {
    const { result } = renderSelection();

    act(() => result.current.onRowKeyDown(keyEvent("ArrowUp"), rows[0]));
    expect(result.current.focusedUid).toBeNull();

    act(() => result.current.onRowKeyDown(keyEvent("ArrowDown"), rows[4]));
    expect(result.current.focusedUid).toBeNull();
  });

  it("expands a collapsed row on ArrowRight, then steps into its first child", () => {
    const { result } = renderSelection();

    act(() => result.current.toggleCollapsed(1));
    act(() => result.current.onRowKeyDown(keyEvent("ArrowRight"), rows[0]));
    expect([...result.current.collapsedUids]).toEqual([]);

    act(() => result.current.onRowKeyDown(keyEvent("ArrowRight"), rows[0]));
    expect(result.current.focusedUid).toBe(2);
  });

  it("collapses an expanded row on ArrowLeft, then walks up to its parent", () => {
    const { result } = renderSelection();

    act(() => result.current.onRowKeyDown(keyEvent("ArrowLeft"), rows[0]));
    expect([...result.current.collapsedUids]).toEqual([1]);

    act(() => result.current.onRowKeyDown(keyEvent("ArrowLeft"), rows[1]));
    expect(result.current.focusedUid).toBe(1);
  });

  it("selects on Enter and toggles the selection on Space, like a click and a Ctrl+click", () => {
    const { result } = renderSelection();

    act(() => result.current.onRowKeyDown(keyEvent("Enter"), rows[1]));
    expect([...result.current.selectedUids]).toEqual([2]);

    act(() => result.current.onRowKeyDown(keyEvent(" "), rows[2]));
    expect([...result.current.selectedUids].sort()).toEqual([2, 3]);

    act(() => result.current.onRowKeyDown(keyEvent(" "), rows[2]));
    expect([...result.current.selectedUids]).toEqual([2]);
  });

  it("makes the first row the single tab stop until something else takes the focus", () => {
    const { result } = renderSelection();
    expect(result.current.focusableUid).toBe(1);

    act(() => result.current.selectRow(rows[2], plainClick));
    expect(result.current.focusableUid).toBe(3);
  });
});

describe("useTreeTableSelection tab stop", () => {
  it("gives the tab stop back to the first navigable row once the focused one is folded away", () => {
    const { result } = renderSelection();

    act(() => result.current.selectRow(rows[1], plainClick));
    expect(result.current.focusableUid).toBe(2);

    // Folding row 1 unmounts row 2 -- the element that held the browser focus. Were focusableUid
    // to keep pointing at it, no rendered row would carry tabIndex={0} and Tab could never bring
    // the focus back into the table.
    act(() => result.current.toggleCollapsed(1));

    expect(result.current.visibleRows.map((row) => row.uid)).toEqual([1, 4, 5]);
    expect(result.current.focusableUid).toBe(1);
  });

  it("skips a row with no uid when picking the default tab stop", () => {
    const rowsWithUnidentifiedFirst: FakeRow[] = [
      { uid: null, parentUid: null, hasChildren: false, kind: "item" },
      item(2, null),
    ];
    const { result } = renderRowsSelection(rowsWithUnidentifiedFirst);

    expect(result.current.visibleRows).toHaveLength(2);
    expect(result.current.focusableUid).toBe(2);
  });

  it("ignores an ArrowLeft whose parent uid resolves to no loaded row", () => {
    // The planning's re-rooted orphan: rendered as a root, yet still carrying the parent uid it
    // came in with (see planningTreeRowIdentity's own comment).
    const orphanRows: FakeRow[] = [group(1, null), { uid: 2, parentUid: 99, hasChildren: false, kind: "item" }];
    const { result } = renderRowsSelection(orphanRows);

    act(() => result.current.onRowKeyDown(keyEvent("ArrowLeft"), orphanRows[1]));

    expect(result.current.focusedUid).toBeNull();
    expect(result.current.focusableUid).toBe(1);
  });
});

describe("useTreeTableSelection with a row carrying no uid", () => {
  // The devis grid's own case: a snapshot-only task row, rendered but absent from the shared uid
  // space, so it can never be folded, focused or selected.
  const rowsWithUnidentified: FakeRow[] = [
    group(1, null),
    { uid: null, parentUid: 1, hasChildren: false, kind: "item" },
    item(3, 1),
  ];

  it("keeps it visible but out of the keyboard travel", () => {
    const { result } = renderRowsSelection(rowsWithUnidentified);
    expect(result.current.visibleRows).toHaveLength(3);

    act(() => result.current.onRowKeyDown(keyEvent("ArrowDown"), rowsWithUnidentified[0]));

    expect(result.current.focusedUid).toBe(3);
  });

  it("ignores a click on it, and hides it along with its collapsed parent", () => {
    const { result } = renderRowsSelection(rowsWithUnidentified);

    act(() => result.current.selectRow(rowsWithUnidentified[1], plainClick));
    expect([...result.current.selectedUids]).toEqual([]);
    expect(result.current.focusedUid).toBeNull();

    act(() => result.current.toggleCollapsed(1));
    expect(result.current.visibleRows.map((row) => row.uid)).toEqual([1]);
  });
});

describe("useTreeTableSelection Shift+click anchored on an unselectable row", () => {
  // Only keyboard navigation can put the focus on a row the identity excludes from the selection
  // (a click on it is ignored outright), so this divergence between the focused row and the
  // selectable range is precisely what E14-09 introduces on the devis grid.
  it("falls back to a single selection instead of spanning from an anchor it cannot place", () => {
    const { result } = renderSelection(identityWithUnselectableGroups);

    act(() => result.current.onRowKeyDown(keyEvent("ArrowDown"), rows[2]));
    expect(result.current.focusedUid).toBe(4);

    act(() => result.current.selectRow(rows[4], shiftClick));

    expect([...result.current.selectedUids]).toEqual([5]);
  });
});
