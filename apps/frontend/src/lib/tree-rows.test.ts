import { describe, expect, it } from "vitest";

import { filterVisibleTreeRows, isRowSelectable, toggleUid, type TreeRowIdentity } from "@/lib/tree-rows";

// A row shape deliberately unrelated to either concrete table: the point of these tests is that
// the shared base works on *any* row kind that can describe itself through a TreeRowIdentity.
type FakeRow = { uid: number | null; parentUid: number | null; hasChildren: boolean; pinned?: boolean };

const identity: TreeRowIdentity<FakeRow> = {
  uidOf: (row) => row.uid,
  parentUidOf: (row) => row.parentUid,
  hasChildrenOf: (row) => row.hasChildren,
};

function row(uid: number | null, parentUid: number | null, hasChildren = false): FakeRow {
  return { uid, parentUid, hasChildren };
}

// Depth-first document order: 1 > (2 > 3), 4.
const rows: FakeRow[] = [row(1, null, true), row(2, 1, true), row(3, 2), row(4, null)];

describe("filterVisibleTreeRows", () => {
  it("returns every row when nothing is collapsed", () => {
    expect(filterVisibleTreeRows(rows, new Set(), identity).map((item) => item.uid)).toEqual([1, 2, 3, 4]);
  });

  it("hides the descendants of a collapsed row but keeps the collapsed row itself", () => {
    expect(filterVisibleTreeRows(rows, new Set([1]), identity).map((item) => item.uid)).toEqual([1, 4]);
  });

  it("hides a whole subtree, not just the collapsed row's direct children", () => {
    expect(filterVisibleTreeRows(rows, new Set([2]), identity).map((item) => item.uid)).toEqual([1, 2, 4]);
  });

  it("ignores a collapsed uid on a leaf row, which has nothing to hide", () => {
    expect(filterVisibleTreeRows(rows, new Set([4]), identity).map((item) => item.uid)).toEqual([1, 2, 3, 4]);
  });

  it("keeps a row whose parent is not in the list, treating it as a root instead of dropping it", () => {
    const orphaned = [row(1, null, true), row(2, 999)];
    expect(filterVisibleTreeRows(orphaned, new Set([1]), identity).map((item) => item.uid)).toEqual([1, 2]);
  });

  it("keeps an identity-less row visible and never lets it hide anything", () => {
    const withNullUid = [row(null, null, true), row(1, null)];
    expect(filterVisibleTreeRows(withNullUid, new Set(), identity)).toHaveLength(2);
  });
});

describe("isRowSelectable", () => {
  it("treats every identified row as selectable when the identity says nothing", () => {
    expect(isRowSelectable(row(1, null), identity)).toBe(true);
  });

  it("never selects a row with no identity, even when isSelectable would allow it", () => {
    expect(isRowSelectable(row(null, null), { ...identity, isSelectable: () => true })).toBe(false);
  });

  it("honours the identity's own opt-out", () => {
    const pinnedIdentity: TreeRowIdentity<FakeRow> = { ...identity, isSelectable: (candidate) => !candidate.pinned };
    expect(isRowSelectable({ ...row(1, null), pinned: true }, pinnedIdentity)).toBe(false);
  });
});

describe("toggleUid", () => {
  it("adds an absent uid and removes a present one, without mutating the input", () => {
    const initial = new Set([1]);
    expect([...toggleUid(initial, 2)]).toEqual([1, 2]);
    expect([...toggleUid(initial, 1)]).toEqual([]);
    expect([...initial]).toEqual([1]);
  });
});
