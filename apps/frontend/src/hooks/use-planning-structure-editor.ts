import { useMemo, useState } from "react";
import type { useRouter } from "next/navigation";

import {
  ApiError,
  createPlanningStructure,
  getPlanning,
  getProject,
  listPlannings,
  Planning,
  PlanningDetail,
  Project,
  savePlanningStructureDraft,
  SessionExpiredError,
  skipPlanningStructure,
} from "@/lib/backend";
import { clearSession, type SessionTokens } from "@/lib/session";
import {
  buildPlanningStructurePayload,
  type PlanningStructureDraftRow,
} from "@/lib/planning-structure";
import type { PlanningStructureGroup } from "@/components/planning-structure-editor";

type AppRouter = ReturnType<typeof useRouter>;

let nextStructureRowId = 2;

interface UsePlanningStructureEditorParams {
  session: SessionTokens | null;
  projectId: number;
  isReadOnlyProject: boolean;
  onSessionRefresh: (next: SessionTokens) => void;
  router: AppRouter;
  setError: (message: string | null) => void;
  setProject: (project: Project) => void;
  setPlannings: (plannings: Planning[]) => void;
  updateSelectedPlanningId: (next: number | null) => void;
  setPlanningDetail: (detail: PlanningDetail | null) => void;
  setStructureOpen: (open: boolean) => void;
}

// Extracted from ProjectDetailsPage (E4-11 / #151): owns the planning "lotissement" structure
// draft state (posts/lots/deliverables) and every handler that edits, saves, generates from, or
// skips it. Pure mechanical move -- see page.tsx call site (Planning tab structure editor) for
// wiring. setStructureDraft is exposed so usePlanningDetailEffect (loading a saved draft) and the
// planning mutation handlers (reopenStructure) can also update this state.
export function usePlanningStructureEditor({
  session,
  projectId,
  isReadOnlyProject,
  onSessionRefresh,
  router,
  setError,
  setProject,
  setPlannings,
  updateSelectedPlanningId,
  setPlanningDetail,
  setStructureOpen,
}: UsePlanningStructureEditorParams) {
  const [structureDraft, setStructureDraft] = useState<PlanningStructureDraftRow[]>([
    { rowId: "row-1", postKey: "post-1", postName: "", lotKey: "lot-1", lotName: "", deliverables: "" },
  ]);
  // A single shared flag (structureBusy) correctly disables all three actions while any one of
  // them runs (they mutate the same project/structure state, so they must be mutually exclusive),
  // but tracking *which* action is running lets each button show its own progress label instead
  // of all three claiming to be busy at once.
  const [structureAction, setStructureAction] = useState<"save" | "generate" | "skip" | null>(null);
  const structureBusy = structureAction !== null;

  const postGroups = useMemo(() => {
    const groups: PlanningStructureGroup[] = [];
    const byPostKey = new Map<string, (typeof groups)[number]>();
    for (const row of structureDraft) {
      let group = byPostKey.get(row.postKey);
      if (!group) {
        group = { groupId: row.rowId, postKey: row.postKey, postName: row.postName, lots: [] };
        byPostKey.set(row.postKey, group);
        groups.push(group);
      }
      group.lots.push({ row });
    }
    return groups;
  }, [structureDraft]);

  function updatePostField(postKey: string, field: "postKey" | "postName", value: string) {
    setStructureDraft((previous) => previous.map((row) => (row.postKey === postKey ? { ...row, [field]: value } : row)));
  }

  function updateLotField(rowId: string, field: "lotKey" | "lotName", value: string) {
    setStructureDraft((previous) => previous.map((row) => (row.rowId === rowId ? { ...row, [field]: value } : row)));
  }

  function updateDeliverable(rowId: string, deliverableIndex: number, value: string) {
    setStructureDraft((previous) =>
      previous.map((row) => {
        if (row.rowId !== rowId) return row;
        const deliverables = row.deliverables.split(",");
        deliverables[deliverableIndex] = value;
        return { ...row, deliverables: deliverables.join(",") };
      }),
    );
  }

  function addDeliverable(rowId: string) {
    setStructureDraft((previous) =>
      previous.map((row) => (row.rowId === rowId ? { ...row, deliverables: `${row.deliverables},` } : row)),
    );
  }

  function removeDeliverable(rowId: string, deliverableIndex: number) {
    setStructureDraft((previous) =>
      previous.map((row) => {
        if (row.rowId !== rowId) return row;
        const deliverables = row.deliverables.split(",").filter((_, index) => index !== deliverableIndex);
        return { ...row, deliverables: deliverables.join(",") };
      }),
    );
  }

  function removeLot(rowId: string) {
    setStructureDraft((previous) => previous.filter((row) => row.rowId !== rowId));
  }

  function addLotToPost(postKey: string, postName: string) {
    const id = nextStructureRowId++;
    setStructureDraft((previous) => [
      ...previous,
      { rowId: `row-${id}`, postKey, postName, lotKey: `lot-${id}`, lotName: "", deliverables: "" },
    ]);
  }

  function addPost() {
    const id = nextStructureRowId++;
    setStructureDraft((previous) => [
      ...previous,
      { rowId: `row-${id}`, postKey: `post-${id}`, postName: "", lotKey: `lot-${id}`, lotName: "", deliverables: "" },
    ]);
  }

  function getPlanningStructurePayload() {
    if (!session || isReadOnlyProject) {
      router.push("/login");
      return null;
    }
    const rows = structureDraft;
    const hasIncompleteRow = rows.some(
      (row) =>
        !row.postKey.trim() ||
        !row.postName.trim() ||
        !row.lotKey.trim() ||
        !row.lotName.trim() ||
        !row.deliverables.trim(),
    );
    if (!rows.length || hasIncompleteRow) {
      setError("Renseigne au moins un poste, un lot et un livrable.");
      return null;
    }
    return buildPlanningStructurePayload(rows);
  }

  async function savePlanningStructure() {
    const payload = getPlanningStructurePayload();
    if (!session || !payload) {
      return;
    }

    setStructureAction("save");
    setError(null);
    try {
      await savePlanningStructureDraft(projectId, payload, session, onSessionRefresh);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible d'enregistrer la structure.");
    } finally {
      setStructureAction(null);
    }
  }

  async function generatePlanningStructure() {
    const payload = getPlanningStructurePayload();
    if (!session || !payload) {
      return;
    }

    setStructureAction("generate");
    setError(null);
    try {
      await createPlanningStructure(projectId, payload, session, onSessionRefresh);
      const [updatedProject, planningMetadata] = await Promise.all([
        getProject(projectId, session, onSessionRefresh),
        listPlannings(projectId, session, onSessionRefresh),
      ]);
      const nextPlanningId = updatedProject.displayed_planning_id ?? planningMetadata.at(-1)?.id ?? null;
      const detail = nextPlanningId
        ? await getPlanning(projectId, nextPlanningId, session, onSessionRefresh)
        : null;
      setProject(updatedProject);
      setPlannings(planningMetadata);
      updateSelectedPlanningId(nextPlanningId);
      setPlanningDetail(detail);
      setStructureOpen(false);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de générer le squelette.");
    } finally {
      setStructureAction(null);
    }
  }

  async function skipStructure() {
    if (!session || isReadOnlyProject) {
      return;
    }
    setStructureAction("skip");
    setError(null);
    try {
      const updatedProject = await skipPlanningStructure(projectId, session, onSessionRefresh);
      setProject(updatedProject);
      setStructureOpen(false);
      try {
        const planningMetadata = await listPlannings(projectId, session, onSessionRefresh);
        const nextPlanningId = updatedProject.displayed_planning_id ?? planningMetadata.at(-1)?.id ?? null;
        const nextDetail = nextPlanningId
          ? await getPlanning(projectId, nextPlanningId, session, onSessionRefresh)
          : null;
        setPlannings(planningMetadata);
        updateSelectedPlanningId(nextPlanningId);
        setPlanningDetail(nextDetail);
      } catch (refreshCause) {
        if (refreshCause instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        setError("Passage effectué, mais impossible de recharger le planning. Recharge la page.");
      }
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de passer cette étape.");
    } finally {
      setStructureAction(null);
    }
  }

  return {
    structureDraft,
    setStructureDraft,
    structureAction,
    structureBusy,
    postGroups,
    updatePostField,
    updateLotField,
    updateDeliverable,
    addDeliverable,
    removeDeliverable,
    removeLot,
    addLotToPost,
    addPost,
    savePlanningStructure,
    generatePlanningStructure,
    skipStructure,
  };
}
