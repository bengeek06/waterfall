import { describe, expect, it } from "vitest";

import type { RevisionNode } from "./backend";
import {
  buildRevisionTreeRows,
  revisionNodeRowIdentity,
  rowNumberByNodeId,
  siblingRanks,
  siblingsByParent,
} from "./revision-tree";
import { filterVisibleTreeRows } from "./tree-rows";

function node(overrides: Partial<RevisionNode> & { node_id: number }): RevisionNode {
  return {
    work_item_id: overrides.node_id * 100,
    kind: "task",
    parent_id: null,
    position: 1,
    row_number: overrides.node_id,
    level: 1,
    external_uid: null,
    description: null,
    planning: null,
    cost: null,
    predecessors: [],
    ...overrides,
  } as RevisionNode;
}

// `Alpha > {Design, Cost line}`, `Beta` -- one task with a task child and a cost child, so the
// kind filter has something to actually do.
const nodes: RevisionNode[] = [
  node({ node_id: 1, row_number: 1, level: 1, position: 1 }),
  node({ node_id: 2, row_number: 2, level: 2, position: 1, parent_id: 1 }),
  node({ node_id: 3, row_number: 3, level: 2, position: 2, parent_id: 1, kind: "cost" }),
  node({ node_id: 4, row_number: 4, level: 1, position: 2 }),
];

describe("buildRevisionTreeRows", () => {
  it("keeps the server's depth-first order, row numbers and levels untouched", () => {
    const rows = buildRevisionTreeRows(nodes);

    expect(rows.map((row) => row.node_id)).toEqual([1, 2, 3, 4]);
    expect(rows.map((row) => row.row_number)).toEqual([1, 2, 3, 4]);
    expect(rows.map((row) => row.level)).toEqual([1, 2, 2, 1]);
  });

  it("flags a node that has children among the kept rows", () => {
    const rows = buildRevisionTreeRows(nodes);

    expect(rows.map((row) => row.hasChildren)).toEqual([true, false, false, false]);
  });

  it("drops the kinds it was not asked for, and recomputes hasChildren over what is left", () => {
    // A task whose only remaining child is a cost line has nothing to unfold in the planning
    // table: showing a chevron there would open an empty branch.
    const rows = buildRevisionTreeRows(
      [nodes[0], nodes[2]], // Alpha and its cost line only
      ["task"],
    );

    expect(rows.map((row) => row.node_id)).toEqual([1]);
    expect(rows[0].hasChildren).toBe(false);
  });

  it("does not renumber the rows it keeps", () => {
    // The positional identifier is the one the user reads and every other screen shows; a filtered
    // view must not invent a second, private numbering.
    const rows = buildRevisionTreeRows(nodes, ["cost"]);

    expect(rows.map((row) => row.row_number)).toEqual([3]);
  });
});

describe("revisionNodeRowIdentity", () => {
  it("reads a row by node id and parent id", () => {
    const rows = buildRevisionTreeRows(nodes);

    expect(revisionNodeRowIdentity.uidOf(rows[1])).toBe(2);
    expect(revisionNodeRowIdentity.parentUidOf(rows[1])).toBe(1);
    expect(revisionNodeRowIdentity.parentUidOf(rows[0])).toBeNull();
    expect(revisionNodeRowIdentity.hasChildrenOf(rows[0])).toBe(true);
  });

  it("drives the shared visibility filter: collapsing a node hides its whole subtree", () => {
    const rows = buildRevisionTreeRows(nodes);

    const visible = filterVisibleTreeRows(rows, new Set([1]), revisionNodeRowIdentity);

    expect(visible.map((row) => row.node_id)).toEqual([1, 4]);
  });
});

describe("rowNumberByNodeId", () => {
  it("maps every node of the tree, including the kinds a table filters out", () => {
    expect(rowNumberByNodeId(nodes)).toEqual(
      new Map([
        [1, 1],
        [2, 2],
        [3, 3],
        [4, 4],
      ]),
    );
  });
});

describe("siblingsByParent", () => {
  it("groups by parent and orders each group by (position, node_id), as children_of() does", () => {
    const shuffled = [nodes[3], nodes[2], nodes[0], nodes[1]];

    const groups = siblingsByParent(shuffled);

    expect(groups.get(null)?.map((row) => row.node_id)).toEqual([1, 4]);
    expect(groups.get(1)?.map((row) => row.node_id)).toEqual([2, 3]);
  });

  it("breaks a tie on node_id, so two siblings sharing a position still have one order", () => {
    // INV-05 numbers `position` 1..n among siblings, so a tie is a violated state -- but that is
    // exactly why `children_of()` (structure.py) sorts on `(position, node_id)` rather than on
    // `position` alone, and why this does too: the move commands rank a selection in this order,
    // and a ranking that depends on the order the rows happened to arrive in would make an
    // "Indenter" enabled or disabled at random. Given deliberately out of node_id order, since
    // a stable sort would otherwise keep the input order and hide the tie-break.
    const tied = [
      node({ node_id: 3, position: 1, parent_id: 1 }),
      node({ node_id: 2, position: 1, parent_id: 1 }),
    ];

    expect(siblingsByParent(tied).get(1)?.map((row) => row.node_id)).toEqual([2, 3]);
  });

  it("answers the sibling set of exactly the rows it was given, and of nothing else", () => {
    // The whole point of the contract: hand it the task rows and it ranks among task rows, hand
    // it the complete tree and it ranks among every child. Neither is the "right" one in the
    // abstract -- the caller decides, and says which it wants (see planningMoveAvailability).
    const taskRowsOnly = buildRevisionTreeRows(nodes, ["task"]);

    expect(siblingsByParent(taskRowsOnly).get(1)?.map((row) => row.node_id)).toEqual([2]);
    expect(siblingsByParent(nodes).get(1)?.map((row) => row.node_id)).toEqual([2, 3]);
  });
});

describe("siblingRanks", () => {
  it("counts position and total in one and the same set", () => {
    const ranks = siblingRanks(nodes);

    expect(ranks.get(2)).toEqual({ position: 1, total: 2 });
    expect(ranks.get(3)).toEqual({ position: 2, total: 2 });
    expect(ranks.get(4)).toEqual({ position: 2, total: 2 });
  });

  it("never announces a rank past the size of the set, on a kind-filtered view", () => {
    // #380: the stored `position` of a task following a cost line is 3 while the planning table
    // renders 2 siblings. Deriving both numbers here keeps aria-posinset <= aria-setsize.
    const withTrailingTask = [...nodes, node({ node_id: 5, row_number: 5, level: 2, position: 3, parent_id: 1 })];
    const taskRowsOnly = buildRevisionTreeRows(withTrailingTask, ["task"]);

    const rank = siblingRanks(taskRowsOnly).get(5);

    expect(rank).toEqual({ position: 2, total: 2 });
    expect(withTrailingTask[4].position).toBe(3);
  });
});
