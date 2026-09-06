import type { RefObject } from "react";
import type { useRouter } from "next/navigation";

import {
  ApiError,
  createPlanningTask,
  deletePlanningTasks,
  getPlanning,
  getPlanningRevisionConflict,
  getPlanningStructureDraft,
  getPlanningTaskDeleteConflict,
  listPlannings,
  movePlanningTasks,
  Planning,
  PlanningDetail,
  Project,
  replaceTaskPredecessorLinks,
  reopenPlanningStructure,
  SessionExpiredError,
  setDisplayedPlanning,
  setPlanningReference,
  type PlanningTaskScheduleUpdate,
  type TaskLinkWrite,
  updatePlanningTaskSchedule,
  validatePlanning,
} from "@/lib/backend";
import { clearSession, type SessionTokens } from "@/lib/session";
import {
  getPlanningStructureDraftRows,
  structureToDraftRows,
  type PlanningStructureDraftRow,
} from "@/lib/planning-structure";
import {
  getPlanningHistory,
  nextPlanningCommandId,
  pushCommand,
  resetPlanningHistory,
  setPlanningHistory,
  snapshotFromPlanningDetail,
  type PlanningCommand,
  type PlanningCommandKind,
  type PlanningHistoryByPlanningId,
} from "@/lib/planning-history";
import type { PlanningMoveCommand } from "@/lib/planning-tree";
import type { PlanningRevisionConflict } from "@/hooks/use-planning-detail";

type AppRouter = ReturnType<typeof useRouter>;

// Backend link validation errors come back as raw English detail strings (see
// PlanningLinkError subclasses); translate the ones surfaced by the predecessor
// links dialog into actionable French copy instead of leaking backend internals.
function describePredecessorLinksError(cause: unknown): string {
  if (!(cause instanceof ApiError)) {
    return "Impossible de mettre à jour les prédécesseurs.";
  }
  if (cause.status === 404) {
    return "Une des tâches référencées est introuvable dans ce planning.";
  }
  if (cause.status === 409) {
    if (cause.message.includes("is not a draft")) {
      return "Le planning n'est plus modifiable (il a été validé entre-temps).";
    }
    if (cause.message.includes("read-only")) {
      return "Le projet est passé en lecture seule et ne peut plus être modifié.";
    }
    if (cause.message.includes("cycle")) {
      return "Cette combinaison de prédécesseurs créerait un cycle dans le planning.";
    }
    return "Cette modification entre en conflit avec l'état actuel du planning.";
  }
  if (cause.status === 400) {
    if (cause.message.includes("own predecessor")) {
      return "Une tâche ne peut pas être son propre prédécesseur.";
    }
    if (cause.message.includes("Duplicate predecessor link")) {
      return "Deux lignes ne peuvent pas référencer la même tâche prédécesseure avec le même type de lien.";
    }
    return "Requête de prédécesseurs invalide.";
  }
  return cause.message || "Impossible de mettre à jour les prédécesseurs.";
}

// A CASCADE_CONFIRMATION_REQUIRED 409 is deliberately excluded here: it is not a failure, it is
// the expected first response of a cascading delete, and PlanningTreeTable's own confirmation
// dialog reacts to it directly (see getPlanningTaskDeleteConflict) instead of this page-level
// error banner.
function describeDeleteTasksError(cause: unknown): string {
  if (!(cause instanceof ApiError)) {
    return "Impossible de supprimer les tâches sélectionnées.";
  }
  if (cause.status === 404) {
    return "Une des tâches sélectionnées est introuvable dans ce planning.";
  }
  if (cause.status === 409) {
    const conflict = getPlanningTaskDeleteConflict(cause);
    if (conflict?.code === "TASK_REFERENCED") {
      return "Une des tâches sélectionnées est référencée par un devis, une affectation ou une charge et ne peut pas être supprimée.";
    }
    return cause.message || "Cette suppression entre en conflit avec l'état actuel du planning.";
  }
  return cause.message || "Impossible de supprimer les tâches sélectionnées.";
}

interface UsePlanningTreeMutationsParams {
  session: SessionTokens | null;
  projectId: number;
  setProject: (project: Project) => void;
  setPlannings: (plannings: Planning[] | ((previous: Planning[]) => Planning[])) => void;
  selectedPlanningId: number | null;
  selectedPlanning: Planning | null;
  isReadOnlyProject: boolean;
  planningDetail: PlanningDetail | null;
  setPlanningDetail: (detail: PlanningDetail | null) => void;
  selectedPlanningIdRef: RefObject<number | null>;
  updateSelectedPlanningId: (next: number | null) => void;
  setHistoryByPlanningId: (
    updater: (current: PlanningHistoryByPlanningId) => PlanningHistoryByPlanningId,
  ) => void;
  planningConflictByPlanningId: Record<number, PlanningRevisionConflict>;
  setPlanningConflictByPlanningId: (
    updater: (previous: Record<number, PlanningRevisionConflict>) => Record<number, PlanningRevisionConflict>,
  ) => void;
  onSessionRefresh: (next: SessionTokens) => void;
  router: AppRouter;
  setError: (message: string | null) => void;
  setRetryableAction: (action: { message: string; retry: () => void } | null) => void;
  setRetryableError: (message: string, retry: () => void) => void;
  setPlanningBusy: (busy: boolean) => void;
  setPlanningDetailBusy: (busy: boolean) => void;
  setPlanningMutationBusy: (busy: boolean) => void;
  setStructureDraft: (rows: PlanningStructureDraftRow[]) => void;
  setStructureOpen: (open: boolean) => void;
}

// Extracted from ProjectDetailsPage (E4-11 / #151): every handler that mutates the currently
// selected planning version (select/validate/move/schedule/links/create/delete tasks, set
// reference, reopen structure) plus the undo/redo history bookkeeping they share
// (recordPlanningCommand). Pure mechanical move -- see page.tsx call site (Planning tab) for
// wiring.
export function usePlanningTreeMutations({
  session,
  projectId,
  setProject,
  setPlannings,
  selectedPlanningId,
  selectedPlanning,
  isReadOnlyProject,
  planningDetail,
  setPlanningDetail,
  selectedPlanningIdRef,
  updateSelectedPlanningId,
  setHistoryByPlanningId,
  planningConflictByPlanningId,
  setPlanningConflictByPlanningId,
  onSessionRefresh,
  router,
  setError,
  setRetryableAction,
  setRetryableError,
  setPlanningBusy,
  setPlanningDetailBusy,
  setPlanningMutationBusy,
  setStructureDraft,
  setStructureOpen,
}: UsePlanningTreeMutationsParams) {
  async function selectPlanning(planningId: number) {
    if (!session || planningId === selectedPlanningId) {
      return;
    }
    if (isReadOnlyProject) {
      updateSelectedPlanningId(planningId);
      return;
    }
    setPlanningBusy(true);
    setError(null);
    try {
      const updatedProject = await setDisplayedPlanning(projectId, planningId, session, onSessionRefresh);
      updateSelectedPlanningId(planningId);
      setProject(updatedProject);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de sélectionner le planning.");
    } finally {
      setPlanningBusy(false);
    }
  }

  async function validateSelectedPlanning() {
    if (
      !session ||
      !selectedPlanning ||
      selectedPlanning.status !== "draft" ||
      isReadOnlyProject ||
      (selectedPlanning ? !!planningConflictByPlanningId[selectedPlanning.id] : false)
    ) {
      return;
    }
    setPlanningBusy(true);
    setError(null);
    try {
      const validated = await validatePlanning(projectId, selectedPlanning.id, session, onSessionRefresh);
      setPlannings((previous) => previous.map((item) => (item.id === validated.id ? validated : item)));
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de valider le planning.");
    } finally {
      setPlanningBusy(false);
    }
  }

  function recordPlanningCommand(
    planningId: number,
    kind: PlanningCommandKind,
    label: string,
    before: PlanningDetail,
    after: PlanningDetail,
  ) {
    const command: PlanningCommand = {
      id: nextPlanningCommandId(),
      kind,
      label,
      before: snapshotFromPlanningDetail(before),
      after: snapshotFromPlanningDetail(after),
    };
    setHistoryByPlanningId((current) =>
      setPlanningHistory(current, planningId, {
        ...pushCommand(getPlanningHistory(current, planningId), command),
        revision: after.revision,
      }),
    );
  }

  async function movePlanningTaskSelection(command: PlanningMoveCommand) {
    if (
      !session ||
      !selectedPlanning ||
      selectedPlanning.status !== "draft" ||
      isReadOnlyProject ||
      !planningDetail ||
      planningDetail.id !== selectedPlanning.id
    ) {
      return;
    }
    const requestedPlanningId = selectedPlanning.id;
    const expectedRevision = planningDetail.revision;
    setPlanningMutationBusy(true);
    setError(null);
    setRetryableAction(null);
    try {
      const updated = await movePlanningTasks(
        projectId,
        requestedPlanningId,
        { ...command, expected_revision: expectedRevision },
        session,
        onSessionRefresh,
      );
      // The user may have switched to another planning version while this request was in flight;
      // applying it now would silently replace that version's tree with a stale one. The
      // history bookkeeping below is unconditional though: the mutation genuinely succeeded
      // for requestedPlanningId, and history is isolated per planning_id, so recording it
      // never affects whatever planning is currently displayed.
      if (selectedPlanningIdRef.current === requestedPlanningId) {
        setPlanningDetail(updated);
      }
      recordPlanningCommand(requestedPlanningId, "move", "Déplacement de tâches", planningDetail, updated);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      const revisionConflict = getPlanningRevisionConflict(cause);
      if (revisionConflict) {
        setPlanningConflictByPlanningId((prev) => ({
          ...prev,
          [requestedPlanningId]: {
            projectId: revisionConflict.projectId,
            expectedRevision: revisionConflict.expectedRevision,
            currentRevision: revisionConflict.currentRevision,
            message: "Ce planning a été modifié entre-temps : recharge-le avant de continuer.",
          },
        }));
        return;
      }
      if (selectedPlanningIdRef.current === requestedPlanningId) {
        const message = cause instanceof ApiError ? cause.message : "Impossible de déplacer les tâches sélectionnées.";
        setRetryableError(message, () => void movePlanningTaskSelection(command));
      }
    } finally {
      setPlanningMutationBusy(false);
    }
  }

  async function reloadPlanningAfterConflict() {
    if (!selectedPlanning || !session || !planningConflictByPlanningId[selectedPlanning.id]) {
      return;
    }
    const planningId = selectedPlanning.id;
    setPlanningDetailBusy(true);
    try {
      const detail = await getPlanning(projectId, planningId, session, onSessionRefresh);
      // Only clear the conflict banner and the stale history once the reload actually
      // succeeded: if getPlanning fails, the user still needs both to retry the reload.
      setPlanningConflictByPlanningId((prev) => {
        const next = { ...prev };
        delete next[planningId];
        return next;
      });
      setHistoryByPlanningId((current) => resetPlanningHistory(current, planningId));
      if (selectedPlanningIdRef.current === planningId) {
        setPlanningDetail(detail);
      }
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de recharger le planning.");
    } finally {
      setPlanningDetailBusy(false);
    }
  }

  // Returns whether the update was actually persisted server-side, so the caller (the tree
  // table's inline schedule edit) knows whether it is safe to discard the user's local draft.
  async function updateTaskScheduleSelection(
    taskUid: number,
    payload: Omit<PlanningTaskScheduleUpdate, "expected_revision">,
  ): Promise<boolean> {
    if (
      !session ||
      !selectedPlanning ||
      selectedPlanning.status !== "draft" ||
      isReadOnlyProject ||
      !planningDetail ||
      planningDetail.id !== selectedPlanning.id
    ) {
      return false;
    }
    const requestedPlanningId = selectedPlanning.id;
    const expectedRevision = planningDetail.revision;
    setPlanningMutationBusy(true);
    setError(null);
    setRetryableAction(null);
    try {
      const updated = await updatePlanningTaskSchedule(
        projectId,
        requestedPlanningId,
        taskUid,
        { ...payload, expected_revision: expectedRevision },
        session,
        onSessionRefresh,
      );
      // The user may have switched to another planning version while this request was in flight;
      // applying it now would silently replace that version's tree with a stale one. The update
      // itself did succeed server-side though (only its local rendering is skipped here), so this
      // still reports success to the caller. History bookkeeping is unconditional: it never
      // affects whatever planning is currently displayed (isolated per planning_id).
      if (selectedPlanningIdRef.current === requestedPlanningId) {
        setPlanningDetail(updated);
      }
      recordPlanningCommand(requestedPlanningId, "schedule", "Modification de la planification", planningDetail, updated);
      return true;
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return false;
      }
      const revisionConflict = getPlanningRevisionConflict(cause);
      if (revisionConflict) {
        setPlanningConflictByPlanningId((prev) => ({
          ...prev,
          [requestedPlanningId]: {
            projectId: revisionConflict.projectId,
            expectedRevision: revisionConflict.expectedRevision,
            currentRevision: revisionConflict.currentRevision,
            message: "Ce planning a été modifié entre-temps : recharge-le avant de continuer.",
          },
        }));
        return false;
      }
      if (selectedPlanningIdRef.current === requestedPlanningId) {
        const message = cause instanceof ApiError ? cause.message : "Impossible de mettre à jour la planification de la tâche.";
        setRetryableError(message, () => void updateTaskScheduleSelection(taskUid, payload));
      }
      return false;
    } finally {
      setPlanningMutationBusy(false);
    }
  }

  async function editTaskPredecessorLinksSelection(taskUid: number, links: TaskLinkWrite[]) {
    // Unlike other mutation handlers in this file, this one is awaited by the dialog itself
    // (PlanningTreeTable.submitLinks), which closes on any resolved promise. A silent `return`
    // here would look like a success and close the dialog while discarding the user's edits, so
    // every guard branch must reject explicitly instead.
    if (!session) {
      throw new Error("Session expirée : reconnecte-toi puis réessaie.");
    }
    if (!selectedPlanning || selectedPlanning.status !== "draft" || isReadOnlyProject) {
      throw new Error("Ce planning n'est plus modifiable : les prédécesseurs n'ont pas été enregistrés.");
    }
    if (!planningDetail || planningDetail.id !== selectedPlanning.id) {
      throw new Error("Le planning affiché a changé : relance la modification des prédécesseurs.");
    }
    const requestedPlanningId = selectedPlanning.id;
    const expectedRevision = planningDetail.revision;
    setPlanningMutationBusy(true);
    setError(null);
    setRetryableAction(null);
    try {
      const updated = await replaceTaskPredecessorLinks(
        projectId,
        requestedPlanningId,
        taskUid,
        { links, expected_revision: expectedRevision },
        session,
        onSessionRefresh,
      );
      // The user may have switched to another planning version while this request was in flight;
      // applying it now would silently replace that version's tree with a stale one. History
      // bookkeeping is unconditional (isolated per planning_id, never affects what's displayed).
      if (selectedPlanningIdRef.current === requestedPlanningId) {
        setPlanningDetail(updated);
      }
      recordPlanningCommand(requestedPlanningId, "links", "Modification des prédécesseurs", planningDetail, updated);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        throw cause;
      }
      const revisionConflict = getPlanningRevisionConflict(cause);
      if (revisionConflict) {
        setPlanningConflictByPlanningId((prev) => ({
          ...prev,
          [requestedPlanningId]: {
            projectId: revisionConflict.projectId,
            expectedRevision: revisionConflict.expectedRevision,
            currentRevision: revisionConflict.currentRevision,
            message: "Ce planning a été modifié entre-temps : recharge-le avant de continuer.",
          },
        }));
        throw cause;
      }
      const message = describePredecessorLinksError(cause);
      if (selectedPlanningIdRef.current === requestedPlanningId) {
        setRetryableError(message, () => void editTaskPredecessorLinksSelection(taskUid, links));
      }
      // Rethrown so the dialog itself can also surface a targeted, actionable error message.
      throw new Error(message);
    } finally {
      setPlanningMutationBusy(false);
    }
  }

  async function createPlanningTaskSelection(command: {
    name: string;
    isMilestone: boolean;
    targetParentUid?: number;
    insertAfterUid?: number;
  }) {
    if (!session || !selectedPlanning || selectedPlanning.status !== "draft" || isReadOnlyProject) {
      return;
    }
    if (!planningDetail || planningDetail.id !== selectedPlanning.id) {
      return;
    }
    const requestedPlanningId = selectedPlanning.id;
    const expectedRevision = planningDetail.revision;
    setPlanningMutationBusy(true);
    setError(null);
    setRetryableAction(null);
    try {
      const updated = await createPlanningTask(
        projectId,
        requestedPlanningId,
        {
          name: command.name,
          is_milestone: command.isMilestone,
          target_parent_uid: command.targetParentUid,
          insert_after_uid: command.insertAfterUid,
          expected_revision: expectedRevision,
        },
        session,
        onSessionRefresh,
      );
      // The user may have switched to another planning version while this request was in flight;
      // applying it now would silently replace that version's tree with a stale one. History
      // bookkeeping is unconditional (isolated per planning_id, never affects what's displayed).
      if (selectedPlanningIdRef.current === requestedPlanningId) {
        setPlanningDetail(updated);
      }
      recordPlanningCommand(requestedPlanningId, "create", "Création d'une tâche", planningDetail, updated);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      const revisionConflict = getPlanningRevisionConflict(cause);
      if (revisionConflict) {
        setPlanningConflictByPlanningId((prev) => ({
          ...prev,
          [requestedPlanningId]: {
            projectId: revisionConflict.projectId,
            expectedRevision: revisionConflict.expectedRevision,
            currentRevision: revisionConflict.currentRevision,
            message: "Ce planning a été modifié entre-temps : recharge-le avant de continuer.",
          },
        }));
        return;
      }
      if (selectedPlanningIdRef.current === requestedPlanningId) {
        const message = cause instanceof ApiError ? cause.message : "Impossible de créer la tâche.";
        setRetryableError(message, () => void createPlanningTaskSelection(command));
      }
    } finally {
      setPlanningMutationBusy(false);
    }
  }

  async function deletePlanningTasksSelection(
    taskUids: number[],
    confirmCascade: boolean,
    requestedVersionKey: number | string | null,
  ) {
    // Unlike movePlanningTaskSelection/updateTaskScheduleSelection, this one is awaited by
    // PlanningTreeTable itself (requestDeleteSelection/confirmCascadeDelete), which distinguishes
    // "needs cascade confirmation" from "resolved" by whether the promise rejects. A silent
    // `return` here would look like a success and clear the selection while nothing was deleted,
    // so every guard branch must reject explicitly instead.
    if (!session) {
      throw new Error("Session expirée : reconnecte-toi puis réessaie.");
    }
    if (!selectedPlanning || selectedPlanning.status !== "draft" || isReadOnlyProject) {
      throw new Error("Ce planning n'est plus modifiable : les tâches n'ont pas été supprimées.");
    }
    const requestedPlanningId = selectedPlanning.id;
    // requestDeleteSelection/confirmCascadeDelete are two independent calls into this function
    // (a probe with confirm_cascade=false, then -- if the backend answers with
    // CASCADE_CONFIRMATION_REQUIRED -- a retry with confirm_cascade=true once the user confirms
    // the AlertDialog). Between those two calls the user is free to switch the displayed planning
    // version (the version <select> is only disabled by planningBusy, not planningMutationBusy).
    // Task uids are reused across a planning's versions (see planning_structure.py), so a stale
    // cascade confirmation retried against the now-displayed version could delete the wrong
    // tasks there. requestedVersionKey is what PlanningTreeTable captured when the delete flow
    // that led to this call began; bail out before any network call if it no longer matches the
    // planning currently displayed, instead of trusting the (possibly stale) task uids.
    if (requestedVersionKey !== requestedPlanningId) {
      const message = "Le planning affiché a changé : relance la suppression.";
      setError(message);
      throw new Error(message);
    }
    if (!planningDetail || planningDetail.id !== requestedPlanningId) {
      const message = "Le planning affiché a changé : relance la suppression.";
      setError(message);
      throw new Error(message);
    }
    const expectedRevision = planningDetail.revision;
    setPlanningMutationBusy(true);
    setError(null);
    setRetryableAction(null);
    try {
      const updated = await deletePlanningTasks(
        projectId,
        requestedPlanningId,
        { task_uids: taskUids, confirm_cascade: confirmCascade, expected_revision: expectedRevision },
        session,
        onSessionRefresh,
      );
      // History bookkeeping is unconditional (isolated per planning_id, never affects what's
      // currently displayed); only the visible detail update is guarded against a stale response.
      if (selectedPlanningIdRef.current === requestedPlanningId) {
        setPlanningDetail(updated);
      }
      recordPlanningCommand(requestedPlanningId, "delete", "Suppression de tâches", planningDetail, updated);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        throw cause;
      }
      const revisionConflict = getPlanningRevisionConflict(cause);
      if (revisionConflict) {
        setPlanningConflictByPlanningId((prev) => ({
          ...prev,
          [requestedPlanningId]: {
            projectId: revisionConflict.projectId,
            expectedRevision: revisionConflict.expectedRevision,
            currentRevision: revisionConflict.currentRevision,
            message: "Ce planning a été modifié entre-temps : recharge-le avant de continuer.",
          },
        }));
        throw cause;
      }
      const conflict = getPlanningTaskDeleteConflict(cause);
      if (
        conflict?.code !== "CASCADE_CONFIRMATION_REQUIRED" &&
        selectedPlanningIdRef.current === requestedPlanningId
      ) {
        const message = describeDeleteTasksError(cause);
        setRetryableError(
          message,
          () => void deletePlanningTasksSelection(taskUids, confirmCascade, requestedVersionKey),
        );
      }
      // Rethrown so PlanningTreeTable can also react: open its cascade dialog on
      // CASCADE_CONFIRMATION_REQUIRED, or otherwise just close it -- the failure message itself
      // is only ever shown once, via the setError banner above.
      throw cause;
    } finally {
      setPlanningMutationBusy(false);
    }
  }

  async function setSelectedPlanningAsReference() {
    if (!session || !selectedPlanning || selectedPlanning.status !== "validated" || isReadOnlyProject) {
      return;
    }
    setPlanningBusy(true);
    setError(null);
    try {
      const updatedProject = await setPlanningReference(projectId, selectedPlanning.id, session, onSessionRefresh);
      const planningMetadata = await listPlannings(projectId, session, onSessionRefresh);
      setProject(updatedProject);
      setPlannings(planningMetadata);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de définir la référence.");
    } finally {
      setPlanningBusy(false);
    }
  }

  async function reopenStructure() {
    if (!session || isReadOnlyProject) {
      return;
    }
    setPlanningBusy(true);
    setError(null);
    try {
      const updatedProject = await reopenPlanningStructure(projectId, session, onSessionRefresh);
      const planningMetadata = await listPlannings(projectId, session, onSessionRefresh);
      const nextPlanningId = updatedProject.displayed_planning_id ?? planningMetadata.at(-1)?.id ?? null;
      const reopenedDetail = nextPlanningId
        ? await getPlanning(projectId, nextPlanningId, session, onSessionRefresh)
        : null;
      const savedDraft = await getPlanningStructureDraft(projectId, session, onSessionRefresh);
      setProject(updatedProject);
      setPlannings(planningMetadata);
      updateSelectedPlanningId(nextPlanningId);
      const rows = savedDraft
        ? structureToDraftRows(savedDraft.structure)
        : getPlanningStructureDraftRows(reopenedDetail);
      if (
        rows.length &&
        rows.every(
          (row) =>
            row.postKey.trim() &&
            row.postName.trim() &&
            row.lotKey.trim() &&
            row.lotName.trim() &&
            row.deliverables.trim(),
        )
      ) {
        setStructureDraft(rows);
      }
      setPlanningDetail(reopenedDetail);
      setStructureOpen(true);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de rouvrir la structure.");
    } finally {
      setPlanningBusy(false);
    }
  }

  return {
    selectPlanning,
    validateSelectedPlanning,
    movePlanningTaskSelection,
    reloadPlanningAfterConflict,
    updateTaskScheduleSelection,
    editTaskPredecessorLinksSelection,
    createPlanningTaskSelection,
    deletePlanningTasksSelection,
    setSelectedPlanningAsReference,
    reopenStructure,
  };
}
