import type { ResourceNode } from "@/lib/backend";

export type OrganizationNodeOption = { id: number; code: string; name: string; depth: number };

// Simplified, non-collapsible sibling-sorted depth-first flattening of the organization tree,
// shared by the "Nœud organisationnel" <select> in estimate-role-assignment-dialog.tsx (E12-06/
// #278). Modeled after resources/page.tsx's own `flattenOrganization`, which additionally tracks
// per-node collapse/expand state for OrganizationTree's interactive table -- this dialog only
// ever needs a flat, fully-expanded, indented list of every node once, so that richer version is
// deliberately not reused here rather than threading a `collapsedIds` concept this caller has no
// use for.
export function buildOrganizationNodeOptions(nodes: ResourceNode[]): OrganizationNodeOption[] {
  const childrenByParent = new Map<number | null, ResourceNode[]>();
  for (const node of nodes) {
    const parentId = node.parent_id ?? null;
    const siblings = childrenByParent.get(parentId) ?? [];
    siblings.push(node);
    childrenByParent.set(parentId, siblings);
  }
  for (const siblings of childrenByParent.values()) {
    siblings.sort((left, right) => left.code.localeCompare(right.code));
  }

  const rows: OrganizationNodeOption[] = [];
  function visit(parentId: number | null, depth: number) {
    for (const node of childrenByParent.get(parentId) ?? []) {
      rows.push({ id: node.id, code: node.code, name: node.name, depth });
      visit(node.id, depth + 1);
    }
  }
  visit(null, 0);
  return rows;
}

// Resolves a role's organizational "Dept" column (E12-06/#278) by walking `nodeId`'s parent_id
// chain in `nodes` up to the root, joining each ancestor's name (root-first) with " / ". Returns
// null for a null/undefined nodeId, or one that can't be found at all (defensive only -- every
// node_id an EstimateRoleAssignment's role can carry comes from the same referential loaded
// here). `seen` guards against an accidental parent_id cycle in the data turning this into an
// infinite loop, rather than trusting the referential's own invariants blindly.
export function resolveOrganizationPath(nodeId: number | null | undefined, nodes: ResourceNode[]): string | null {
  if (nodeId == null) {
    return null;
  }
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const segments: string[] = [];
  const seen = new Set<number>();
  let current = byId.get(nodeId);
  while (current && !seen.has(current.id)) {
    segments.unshift(current.name);
    seen.add(current.id);
    current = current.parent_id != null ? byId.get(current.parent_id) : undefined;
  }
  return segments.length ? segments.join(" / ") : null;
}
