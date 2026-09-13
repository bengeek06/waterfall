import { describe, expect, it } from "vitest";

import type { RevisionNode, RevisionPlanFacet } from "./backend";
import { buildPlanningRows, normalizeSelectionToRoots, planningMoveAvailability } from "./planning-tree";

function facet(overrides: Partial<RevisionPlanFacet> = {}): RevisionPlanFacet {
  return {
    name: "Tâche",
    calendar_id: null,
    calendar_source: null,
    is_milestone: false,
    duration_minutes: null,
    duration_format: null,
    start_at: null,
    finish_at: null,
    work_minutes: null,
    percent_complete: 0,
    is_manual: true,
    ...overrides,
  };
}

function taskNode(
  nodeId: number,
  options: { parentId?: number | null; position?: number; level?: number; name?: string; milestone?: boolean } = {},
): RevisionNode {
  return {
    node_id: nodeId,
    work_item_id: nodeId * 10,
    kind: "task",
    parent_id: options.parentId ?? null,
    position: options.position ?? 1,
    row_number: nodeId,
    level: options.level ?? 1,
    external_uid: null,
    description: null,
    planning: facet({ name: options.name ?? `T${nodeId}`, is_milestone: options.milestone ?? false }),
    cost: null,
    predecessors: [],
  };
}

// P > [X, Y, Z], and a root sibling Q -- the very shape #344's outdent decision is stated on.
function tree(): RevisionNode[] {
  return [
    taskNode(1, { name: "P", position: 1 }),
    taskNode(2, { name: "X", parentId: 1, position: 1, level: 2 }),
    taskNode(3, { name: "Y", parentId: 1, position: 2, level: 2 }),
    taskNode(4, { name: "Z", parentId: 1, position: 3, level: 2 }),
    taskNode(5, { name: "Q", position: 2 }),
  ];
}

// Poste > Livrable > Détail, plus a root sibling: three levels deep, which `tree()` above is not.
function deepChain(): RevisionNode[] {
  return [
    taskNode(1, { name: "Poste", position: 1 }),
    taskNode(2, { name: "Livrable", parentId: 1, position: 1, level: 2 }),
    taskNode(3, { name: "Détail", parentId: 2, position: 1, level: 3 }),
    taskNode(4, { name: "Autre poste", position: 2 }),
  ];
}

describe("buildPlanningRows", () => {
  it("keeps only the task nodes, in the order the server sent them", () => {
    const nodes = [...tree(), { ...taskNode(6), kind: "cost" as const, planning: null, parent_id: 1 }];

    const rows = buildPlanningRows(nodes);

    expect(rows.map((row) => row.planning.name)).toEqual(["P", "X", "Y", "Z", "Q"]);
  });
});

describe("normalizeSelectionToRoots", () => {
  it("drops a node whose ancestor is also selected", () => {
    const rows = buildPlanningRows(tree());

    const roots = normalizeSelectionToRoots(rows, new Set([1, 3]));

    expect(roots.map((row) => row.node_id)).toEqual([1]);
  });

  it("walks the whole ancestor chain, not just the direct parent", () => {
    // Ctrl+click on a poste and on one of its *grandchildren*: the grandchild's parent is not
    // itself selected, so only a walk up to the root can see that the poste already carries it.
    // Stopping at the direct parent would answer two roots at two different levels -- which
    // `_common_parent` then refuses as `mixed-parents`, greying out all four buttons on a
    // selection the backend would have accepted.
    const roots = normalizeSelectionToRoots(deepChain(), new Set([1, 3]));

    expect(roots.map((node) => node.node_id)).toEqual([1]);
  });

  it("returns the selected roots in display order", () => {
    const rows = buildPlanningRows(tree());

    const roots = normalizeSelectionToRoots(rows, new Set([5, 2]));

    expect(roots.map((row) => row.node_id)).toEqual([2, 5]);
  });
});

describe("planningMoveAvailability", () => {
  // The complete node list, deliberately -- see the function's own contract. `buildPlanningRows`
  // is what the *table* renders, and is never what a command is decided on.
  const rows = () => tree();

  it("refuses every command on an empty selection", () => {
    for (const mode of ["up", "down", "indent", "outdent"] as const) {
      const availability = planningMoveAvailability(rows(), new Set(), mode);
      expect(availability.enabled).toBe(false);
      expect(availability.refusal).toBe("empty-selection");
    }
  });

  it("refuses a selection spanning two parents", () => {
    const availability = planningMoveAvailability(rows(), new Set([2, 5]), "up");

    expect(availability.enabled).toBe(false);
    expect(availability.refusal).toBe("mixed-parents");
  });

  it("refuses a sibling block with a hole in it", () => {
    const availability = planningMoveAvailability(rows(), new Set([2, 4]), "down");

    expect(availability.enabled).toBe(false);
    expect(availability.refusal).toBe("not-contiguous");
  });

  it("allows moving a middle sibling either way, and refuses the edges", () => {
    expect(planningMoveAvailability(rows(), new Set([3]), "up").enabled).toBe(true);
    expect(planningMoveAvailability(rows(), new Set([3]), "down").enabled).toBe(true);
    expect(planningMoveAvailability(rows(), new Set([2]), "up").refusal).toBe("at-first-position");
    expect(planningMoveAvailability(rows(), new Set([4]), "down").refusal).toBe("at-last-position");
  });

  it("refuses indenting the first child of a parent", () => {
    expect(planningMoveAvailability(rows(), new Set([2]), "indent").refusal).toBe("at-first-position");
  });

  it("refuses indenting under a jalon (INV-27) and says so", () => {
    const nodes = tree();
    nodes[1].planning = facet({ name: "X", is_milestone: true });

    const availability = planningMoveAvailability(nodes, new Set([3]), "indent");

    expect(availability.enabled).toBe(false);
    expect(availability.refusal).toBe("milestone-parent");
    expect(availability.reason).toContain("jalon");
  });

  it("refuses outdenting a root", () => {
    expect(planningMoveAvailability(rows(), new Set([1]), "outdent").refusal).toBe("already-at-root");
  });

  it("allows outdenting an ordinary child", () => {
    expect(planningMoveAvailability(rows(), new Set([3]), "outdent").enabled).toBe(true);
  });

  it("refuses outdenting a jalon that is followed by siblings (INV-27 through Règle 5)", () => {
    // Outdenting Y makes the siblings that followed it (Z) its children, so a jalon there would
    // end up carrying one -- which INV-27 refuses. The user is told rather than shown a 400.
    const nodes = tree();
    nodes[2].planning = facet({ name: "Y", is_milestone: true });

    const availability = planningMoveAvailability(nodes, new Set([3]), "outdent");

    expect(availability.enabled).toBe(false);
    expect(availability.refusal).toBe("milestone-children");
    expect(availability.reason).toContain("jalon");
  });

  it("allows outdenting a jalon that is the last of its siblings", () => {
    // Nothing follows it, so nothing becomes its child and the rule does not apply.
    const nodes = tree();
    nodes[3].planning = facet({ name: "Z", is_milestone: true });

    expect(planningMoveAvailability(nodes, new Set([4]), "outdent").enabled).toBe(true);
  });

  it("decides on the selection roots, so selecting a parent and its child is still one move", () => {
    expect(planningMoveAvailability(rows(), new Set([3, 4]), "outdent").enabled).toBe(true);
  });

  it("still offers the move when the second selected row is a *grandchild* of the first", () => {
    // The same normalisation, seen from the toolbar: one root, at root level, with a sibling
    // after it -- so "Descendre" is offered. Read as two roots, the selection spans two levels
    // and every command dies as `mixed-parents`.
    expect(planningMoveAvailability(deepChain(), new Set([1, 3]), "down").enabled).toBe(true);
  });

  // ------------------------------------------------------------------------------------------
  // The sibling model is the backend's: children_of() orders tasks **and** cost nodes together
  // (structure.py) and INV-05 numbers `position` 1..n over that whole set. Only INV-14 forbids a
  // *task* under a cost node, so a task carrying both sub-tasks and cost lines is a legal state --
  // and the planning table renders only half of it.
  // ------------------------------------------------------------------------------------------

  describe("on a sibling set mixing tasks and cost lines", () => {
    // P > [task A(1), cost C(2), task B(3)]: three siblings on the wire, two rendered rows.
    function mixedNodes(): RevisionNode[] {
      const costNode: RevisionNode = {
        ...taskNode(3, { name: "C", parentId: 1, position: 2, level: 2 }),
        kind: "cost",
        planning: null,
      };
      return [
        taskNode(1, { name: "P", position: 1 }),
        taskNode(2, { name: "A", parentId: 1, position: 1, level: 2 }),
        costNode,
        taskNode(4, { name: "B", parentId: 1, position: 3, level: 2 }),
      ];
    }

    it("refuses indenting a task whose preceding sibling is a cost line (INV-14)", () => {
      // Filtered to its task rows the block reads [A, B] and B looks indentable under A. It is
      // not: the backend would take siblings[first_index - 1] of [A, C, B] and land the task
      // under C, which FacetPlacementError refuses with a 400.
      const availability = planningMoveAvailability(mixedNodes(), new Set([4]), "indent");

      expect(availability.enabled).toBe(false);
      expect(availability.refusal).toBe("cost-parent");
      expect(availability.reason).toContain("chiffrage");
    });

    it("refuses {A, B} as a non-contiguous block, because the cost line sits between them", () => {
      const availability = planningMoveAvailability(mixedNodes(), new Set([2, 4]), "up");

      expect(availability.enabled).toBe(false);
      expect(availability.refusal).toBe("not-contiguous");
    });

    it("offers Descendre on the last *task*, which is not the last sibling", () => {
      // The mirror defect: counted over the task rows alone, B is the last of its level and the
      // command would be greyed out -- yet the backend accepts it, since C follows it.
      const nodes = mixedNodes();
      nodes[2].position = 3;
      nodes[3].position = 2;

      expect(planningMoveAvailability(nodes, new Set([4]), "down").enabled).toBe(true);
    });

    it("refuses outdenting a jalon followed only by a cost line", () => {
      // Règle 5 hands the following siblings to the outdented node whatever facet they carry, so
      // a cost line following a jalon is an INV-27 violation just as a task would be.
      const nodes = mixedNodes();
      nodes[3].position = 2;
      nodes[3].planning = facet({ name: "B", is_milestone: true });
      nodes[2].position = 3;

      const availability = planningMoveAvailability(nodes, new Set([4]), "outdent");

      expect(availability.enabled).toBe(false);
      expect(availability.refusal).toBe("milestone-children");
    });

    it("refuses outdenting a cost line that is followed by a task (INV-14 through Règle 5)", () => {
      // The mirror of the indent refusal, and the one the planning table cannot reach: outdenting
      // C hands the siblings that followed it (task B) to C itself, and `_validate_move_target`
      // answers FacetPlacementError -- a cost node carries no task. Unreachable here because only
      // tasks are selectable; reachable from the devis grid (#337), which selects cost rows.
      const availability = planningMoveAvailability(mixedNodes(), new Set([3]), "outdent");

      expect(availability.enabled).toBe(false);
      expect(availability.refusal).toBe("cost-parent");
    });

    it("still lets a cost line be indented under another cost line", () => {
      // INV-14 is one-way: it forbids a *task* under a cost node, never a cost node under one.
      // The refusal therefore looks at what is selected, not only at the new parent -- which is
      // what makes this function reusable by the devis grid (#337) instead of forked.
      const nodes = mixedNodes();
      const secondCost: RevisionNode = {
        ...taskNode(5, { name: "D", parentId: 1, position: 3, level: 2 }),
        kind: "cost",
        planning: null,
      };
      nodes[3].position = 4; // task B moves after the two cost lines: P > [A, C, D, B]

      expect(planningMoveAvailability([...nodes, secondCost], new Set([5]), "indent").enabled).toBe(true);
    });
  });
});
