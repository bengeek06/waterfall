import type { PlanningDetail, PlanningStructureCreate } from "./backend";

export type PlanningStructureDraftRow = {
  rowId: string;
  postKey: string;
  postName: string;
  lotKey: string;
  lotName: string;
  deliverables: string;
  // Preserves the original key of each known deliverable (name -> key) so a
  // round-trip through the payload keeps stable structure_key values.
  // Known limitation: renaming a deliverable is treated as new (loses its UID);
  // non-destructive rename is deferred to E3 tree mutations.
  deliverableKeys?: Record<string, string>;
};

export function structureToDraftRows(structure: PlanningStructureCreate): PlanningStructureDraftRow[] {
  return structure.posts.flatMap((post) =>
    post.lots.map((lot) => ({
      rowId: `${post.key}/${lot.key}`,
      postKey: post.key,
      postName: post.name,
      lotKey: lot.key,
      lotName: lot.name,
      deliverables: lot.deliverables.map((deliverable) => deliverable.name).join(", "),
      deliverableKeys: Object.fromEntries(
        lot.deliverables.map((deliverable) => [deliverable.name, deliverable.key]),
      ),
    })),
  );
}

export function getPlanningStructureDraftRows(
  detail: PlanningDetail | null,
): PlanningStructureDraftRow[] {
  const rows = (detail?.tasks ?? [])
    .filter((task) => task.structure_kind === "livrable")
    .map((task) => {
      const [postKey = "", lotKey = "", deliverableKey = ""] = (task.structure_key ?? "").split("/");
      const lot = detail?.tasks.find(
        (candidate) => candidate.structure_kind === "lot" && candidate.structure_key === `${postKey}/${lotKey}`,
      );
      const post = detail?.tasks.find(
        (candidate) => candidate.structure_kind === "poste" && candidate.structure_key === postKey,
      );
      return {
        rowId: task.structure_key ?? `task-${task.uid}`,
        postKey,
        postName: post?.name ?? "",
        lotKey,
        lotName: lot?.name ?? "",
        deliverables: task.name,
        deliverableKeys: deliverableKey ? { [task.name]: deliverableKey } : undefined,
      };
    });
  return rows;
}

type PlanningStructureLotDraft = {
  key: string;
  name: string;
  deliverables: { key: string; name: string }[];
  usedKeys: Set<string>;
};

type PlanningStructurePostDraft = {
  key: string;
  name: string;
  lots: Map<string, PlanningStructureLotDraft>;
};

function nextDeliverableKey(usedKeys: Set<string>): string {
  let maxIndex = 0;
  for (const key of usedKeys) {
    const match = /^deliverable-(\d+)$/.exec(key);
    if (match) {
      maxIndex = Math.max(maxIndex, Number(match[1]));
    }
  }
  let index = maxIndex + 1;
  while (usedKeys.has(`deliverable-${index}`)) {
    index += 1;
  }
  return `deliverable-${index}`;
}

export function buildPlanningStructurePayload(
  rows: PlanningStructureDraftRow[],
): PlanningStructureCreate {
  const posts = new Map<string, PlanningStructurePostDraft>();

  for (const row of rows) {
    const postKey = row.postKey.trim();
    const lotKey = row.lotKey.trim();
    if (!postKey || !row.postName.trim() || !lotKey || !row.lotName.trim()) {
      continue;
    }
    let post = posts.get(postKey);
    if (!post) {
      post = {
        key: postKey,
        name: row.postName.trim(),
        lots: new Map<string, PlanningStructureLotDraft>(),
      };
      posts.set(post.key, post);
    }
    let lot = post.lots.get(lotKey);
    if (!lot) {
      lot = {
        key: lotKey,
        name: row.lotName.trim(),
        deliverables: [],
        usedKeys: new Set<string>(),
      };
      post.lots.set(lot.key, lot);
    }
    const existingNames = new Set(lot.deliverables.map((deliverable) => deliverable.name));
    for (const name of row.deliverables.split(",").map((value) => value.trim()).filter(Boolean)) {
      if (existingNames.has(name)) {
        continue;
      }
      const knownKey = row.deliverableKeys?.[name];
      const key =
        knownKey && !lot.usedKeys.has(knownKey) ? knownKey : nextDeliverableKey(lot.usedKeys);
      lot.deliverables.push({ key, name });
      lot.usedKeys.add(key);
      existingNames.add(name);
    }
  }

  return {
    posts: Array.from(posts.values()).map((post) => ({
      key: post.key,
      name: post.name,
      lots: Array.from(post.lots.values()).map((lot) => ({
        key: lot.key,
        name: lot.name,
        deliverables: lot.deliverables,
      })),
    })),
  };
}
