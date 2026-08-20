import type { PlanningStructureCreate } from "./backend";

export type PlanningStructureDraftRow = {
  postKey: string;
  postName: string;
  lotKey: string;
  lotName: string;
  deliverables: string;
};

type PlanningStructureLotDraft = {
  key: string;
  name: string;
  deliverables: { key: string; name: string }[];
};

type PlanningStructurePostDraft = {
  key: string;
  name: string;
  lots: Map<string, PlanningStructureLotDraft>;
};

export function buildPlanningStructurePayload(
  rows: PlanningStructureDraftRow[],
): PlanningStructureCreate {
  const posts = new Map<string, PlanningStructurePostDraft>();

  for (const row of rows) {
    if (!row.postKey.trim() || !row.postName.trim() || !row.lotKey.trim() || !row.lotName.trim()) {
      continue;
    }
    let post = posts.get(row.postKey);
    if (!post) {
      post = {
        key: row.postKey.trim(),
        name: row.postName.trim(),
        lots: new Map<string, PlanningStructureLotDraft>(),
      };
      posts.set(post.key, post);
    }
    let lot = post.lots.get(row.lotKey);
    if (!lot) {
      lot = {
        key: row.lotKey.trim(),
        name: row.lotName.trim(),
        deliverables: [],
      };
      post.lots.set(lot.key, lot);
    }
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
  }

  return {
    posts: Array.from(posts.values()).map((post) => ({
      key: post.key,
      name: post.name,
      lots: Array.from(post.lots.values()),
    })),
  };
}
