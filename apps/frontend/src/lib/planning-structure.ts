import type { PlanningStructureCreate } from "./backend";

export type PlanningStructureDraftRow = {
  postKey: string;
  postName: string;
  lotKey: string;
  lotName: string;
  deliverables: string;
};

export function buildPlanningStructurePayload(
  rows: PlanningStructureDraftRow[],
): PlanningStructureCreate {
  const posts = new Map<
    string,
    {
      key: string;
      name: string;
      lots: Map<string, { key: string; name: string; deliverables: { key: string; name: string }[] }>;
    }
  >();

  for (const row of rows) {
    if (!row.postKey.trim() || !row.postName.trim() || !row.lotKey.trim() || !row.lotName.trim()) {
      continue;
    }
    const post = posts.get(row.postKey) ?? {
      key: row.postKey.trim(),
      name: row.postName.trim(),
      lots: new Map(),
    };
    const lot = post.lots.get(row.lotKey) ?? {
      key: row.lotKey.trim(),
      name: row.lotName.trim(),
      deliverables: [],
    };
    const existingNames = new Set(lot.deliverables.map((deliverable) => deliverable.name));
    for (const name of row.deliverables.split(",").map((value) => value.trim()).filter(Boolean)) {
      if (existingNames.has(name)) {
        continue;
      }
      lot.deliverables.push({
        key: `deliverable-${lot.deliverables.length + 1}`,
        name,
      });
      existingNames.add(name);
    }
    post.lots.set(lot.key, lot);
    posts.set(post.key, post);
  }

  return {
    posts: Array.from(posts.values()).map((post) => ({
      key: post.key,
      name: post.name,
      lots: Array.from(post.lots.values()),
    })),
  };
}
