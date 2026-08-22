import type { Planning, PlanningDetail, PlanningStructureCreate } from "./backend";

export type PlanningStructureDraftRow = {
  rowId: string;
  postKey: string;
  postName: string;
  lotKey: string;
  lotName: string;
  deliverables: string;
};

const DRAFT_NOTE_PREFIX = "planning-structure-draft:";

function rowsFromStructure(structure: PlanningStructureCreate): PlanningStructureDraftRow[] {
  return structure.posts.flatMap((post) =>
    post.lots.map((lot) => ({
      rowId: `${post.key}/${lot.key}`,
      postKey: post.key,
      postName: post.name,
      lotKey: lot.key,
      lotName: lot.name,
      deliverables: lot.deliverables.map((deliverable) => deliverable.name).join(", "),
    })),
  );
}

export function getPlanningStructureDraftRows(
  planning: Planning | null,
  detail: PlanningDetail | null,
): PlanningStructureDraftRow[] {
  if (planning?.note?.startsWith(DRAFT_NOTE_PREFIX)) {
    try {
      const structure = JSON.parse(planning.note.slice(DRAFT_NOTE_PREFIX.length)) as PlanningStructureCreate;
      const rows = rowsFromStructure(structure);
      if (rows.length) {
        return rows;
      }
    } catch {
      // Fall back to the selected planning when an older draft is malformed.
    }
  }

  const rows = (detail?.tasks ?? [])
    .filter((task) => task.structure_kind === "livrable")
    .map((task) => {
      const [postKey = "", lotKey = ""] = (task.structure_key ?? "").split("/");
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
      };
    });
  return rows;
}

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
