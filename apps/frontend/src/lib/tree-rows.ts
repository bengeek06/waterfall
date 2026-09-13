// E14-09 (#335) / resolves #316: the row-shape-agnostic half of the shared editable-tree base.
//
// The planning table and the devis grid render two different things (different columns, different
// calculations, different move rules) over the *same* interaction model: a depth-first row list
// that folds and unfolds, selects, and commits per-row drafts. Everything in this module and in
// the `use-tree-*` hooks is that interaction model and nothing else -- it is parameterized by a
// `TreeRowIdentity`, which is the only thing it ever needs to know about a concrete row.
//
// If a rule about *what* a row means (a column, a subtotal, whether a move is legal) ends up
// here, it is in the wrong file: it belongs to the table that owns that meaning.

/**
 * Everything the shared base needs to know about a concrete row kind.
 *
 * `uidOf` returning `null` marks a row that has no identity in the tree's shared uid space: it is
 * still rendered, but can never be collapsed, selected or focused (the devis grid's snapshot-only
 * task rows are the real case). `isSelectable` narrows that further, for a row that *has* an
 * identity but must stay out of the selection entirely (the devis grid's task rows, which its
 * move toolbar never reorders).
 */
export type TreeRowIdentity<TRow> = {
  uidOf: (row: TRow) => number | null;
  parentUidOf: (row: TRow) => number | null;
  hasChildrenOf: (row: TRow) => boolean;
  isSelectable?: (row: TRow) => boolean;
};

export function isRowSelectable<TRow>(row: TRow, identity: TreeRowIdentity<TRow>): boolean {
  if (identity.uidOf(row) === null) {
    return false;
  }
  return identity.isSelectable ? identity.isSelectable(row) : true;
}

/**
 * Filters `rows` -- already in depth-first document order, i.e. a parent always precedes its own
 * descendants -- down to the rows currently visible given `collapsedUids`.
 *
 * A single forward pass is enough precisely because of that ordering: once a collapsed row is
 * seen, every following row whose parent chain passes through it is hidden too. A row whose
 * `parentUidOf` does not resolve to any preceding row (an orphan) is treated as a root and stays
 * visible, rather than disappearing silently.
 */
export function filterVisibleTreeRows<TRow>(
  rows: readonly TRow[],
  collapsedUids: ReadonlySet<number>,
  identity: TreeRowIdentity<TRow>,
): TRow[] {
  const hiddenUids = new Set<number>();
  const visible: TRow[] = [];
  for (const row of rows) {
    const uid = identity.uidOf(row);
    const parentUid = identity.parentUidOf(row);
    if (parentUid !== null && hiddenUids.has(parentUid)) {
      if (uid !== null) {
        hiddenUids.add(uid);
      }
      continue;
    }
    visible.push(row);
    if (uid !== null && identity.hasChildrenOf(row) && collapsedUids.has(uid)) {
      hiddenUids.add(uid);
    }
  }
  return visible;
}

/** Adds `uid` to `uids` when absent, removes it when present, always returning a new Set. */
export function toggleUid(uids: ReadonlySet<number>, uid: number): Set<number> {
  const next = new Set(uids);
  if (next.has(uid)) {
    next.delete(uid);
  } else {
    next.add(uid);
  }
  return next;
}
