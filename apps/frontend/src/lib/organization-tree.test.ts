import { describe, expect, it } from "vitest";

import { buildOrganizationNodeOptions, resolveOrganizationPath } from "@/lib/organization-tree";
import type { ResourceNode } from "@/lib/backend";

function makeNode(overrides: Partial<ResourceNode> = {}): ResourceNode {
  return {
    id: 1,
    code: "A",
    name: "Node A",
    parent_id: null,
    is_active: true,
    ...overrides,
  } as ResourceNode;
}

describe("buildOrganizationNodeOptions", () => {
  it("returns nothing for an empty referential", () => {
    expect(buildOrganizationNodeOptions([])).toEqual([]);
  });

  it("lists root nodes at depth 0, sorted by code", () => {
    const b = makeNode({ id: 2, code: "B", name: "Node B" });
    const a = makeNode({ id: 1, code: "A", name: "Node A" });

    const options = buildOrganizationNodeOptions([b, a]);

    expect(options).toEqual([
      { id: 1, code: "A", name: "Node A", depth: 0 },
      { id: 2, code: "B", name: "Node B", depth: 0 },
    ]);
  });

  it("lists a child immediately after its parent, indented one level deeper", () => {
    const root = makeNode({ id: 1, code: "A", name: "Direction" });
    const child = makeNode({ id: 2, code: "A.1", name: "Pôle Études", parent_id: 1 });

    const options = buildOrganizationNodeOptions([child, root]);

    expect(options).toEqual([
      { id: 1, code: "A", name: "Direction", depth: 0 },
      { id: 2, code: "A.1", name: "Pôle Études", depth: 1 },
    ]);
  });

  it("never collapses anything: every node in the referential is listed", () => {
    const root = makeNode({ id: 1, code: "A", name: "Direction" });
    const child = makeNode({ id: 2, code: "A.1", name: "Pôle Études", parent_id: 1 });
    const grandchild = makeNode({ id: 3, code: "A.1.1", name: "BE Structures", parent_id: 2 });

    const options = buildOrganizationNodeOptions([root, child, grandchild]);

    expect(options.map((option) => option.id)).toEqual([1, 2, 3]);
    expect(options[2].depth).toBe(2);
  });
});

describe("resolveOrganizationPath", () => {
  const root = makeNode({ id: 1, code: "A", name: "Direction" });
  const child = makeNode({ id: 2, code: "A.1", name: "Pôle Études", parent_id: 1 });
  const grandchild = makeNode({ id: 3, code: "A.1.1", name: "BE Structures", parent_id: 2 });
  const nodes = [root, child, grandchild];

  it("returns null for a null/undefined nodeId", () => {
    expect(resolveOrganizationPath(null, nodes)).toBeNull();
    expect(resolveOrganizationPath(undefined, nodes)).toBeNull();
  });

  it("returns null for a nodeId that can't be found in the referential", () => {
    expect(resolveOrganizationPath(999, nodes)).toBeNull();
  });

  it("returns just the node's own name for a root node", () => {
    expect(resolveOrganizationPath(1, nodes)).toBe("Direction");
  });

  it("joins every ancestor name root-first with ' / '", () => {
    expect(resolveOrganizationPath(3, nodes)).toBe("Direction / Pôle Études / BE Structures");
  });

  it("never loops forever on an accidental parent_id cycle in the data", () => {
    const cyclicA = makeNode({ id: 10, code: "X", name: "X", parent_id: 11 });
    const cyclicB = makeNode({ id: 11, code: "Y", name: "Y", parent_id: 10 });

    expect(() => resolveOrganizationPath(10, [cyclicA, cyclicB])).not.toThrow();
  });
});
