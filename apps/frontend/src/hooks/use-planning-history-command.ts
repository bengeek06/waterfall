import type { RefObject } from "react";
import type { useRouter } from "next/navigation";

import {
  ApiError,
  getPlanningRevisionConflict,
  Planning,
  PlanningDetail,
  restorePlanningSnapshot,
  SessionExpiredError,
} from "@/lib/backend";
import { clearSession, type SessionTokens } from "@/lib/session";
import {
  commitRedo,
  commitUndo,
  getPlanningHistory,
  peekRedo,
  peekUndo,
  setPlanningHistory,
  type PlanningHistoryByPlanningId,
} from "@/lib/planning-history";
import type { PlanningRevisionConflict } from "@/hooks/use-planning-detail";

type AppRouter = ReturnType<typeof useRouter>;

interface UsePlanningHistoryCommandParams {
  session: SessionTokens | null;
  selectedPlanning: Planning | null;
  isReadOnlyProject: boolean;
  planningDetail: PlanningDetail | null;
  historyByPlanningId: PlanningHistoryByPlanningId;
  projectId: number;
  onSessionRefresh: (next: SessionTokens) => void;
  router: AppRouter;
  selectedPlanningIdRef: RefObject<number | null>;
  setPlanningMutationBusy: (busy: boolean) => void;
  setError: (message: string | null) => void;
  setRetryableAction: (action: { message: string; retry: () => void } | null) => void;
  setPlanningDetail: (detail: PlanningDetail | null) => void;
  setPlanningConflictByPlanningId: (
    updater: (
      previous: Record<number, PlanningRevisionConflict>,
    ) => Record<number, PlanningRevisionConflict>,
  ) => void;
  setHistoryByPlanningId: (
    updater: (current: PlanningHistoryByPlanningId) => PlanningHistoryByPlanningId,
  ) => void;
  setRetryableError: (message: string, retry: () => void) => void;
}

// Extracted verbatim from ProjectDetailsPage (E4-10 / #150): applies an undo/redo command against
// the currently-selected planning. Pure mechanical move -- see page.tsx call sites (undo/redo
// buttons) for wiring.
export function usePlanningHistoryCommand({
  session,
  selectedPlanning,
  isReadOnlyProject,
  planningDetail,
  historyByPlanningId,
  projectId,
  onSessionRefresh,
  router,
  selectedPlanningIdRef,
  setPlanningMutationBusy,
  setError,
  setRetryableAction,
  setPlanningDetail,
  setPlanningConflictByPlanningId,
  setHistoryByPlanningId,
  setRetryableError,
}: UsePlanningHistoryCommandParams) {
  async function applyPlanningHistoryCommand(direction: "undo" | "redo") {
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
    const planningId = selectedPlanning.id;
    const history = getPlanningHistory(historyByPlanningId, planningId);
    const command = direction === "undo" ? peekUndo(history) : peekRedo(history);
    if (!command) {
      return;
    }
    const delta = direction === "undo" ? command.before : command.after;
    setPlanningMutationBusy(true);
    setError(null);
    setRetryableAction(null);
    try {
      const updated = await restorePlanningSnapshot(
        projectId,
        planningId,
        { ...delta, expected_revision: planningDetail.revision },
        session,
        onSessionRefresh,
      );
      // The stack transition is unconditional: the undo/redo genuinely succeeded server-side
      // for this planning_id, so the command must move between stacks regardless of which
      // planning is currently displayed -- only the visible detail update is guarded.
      if (selectedPlanningIdRef.current === planningId) {
        setPlanningDetail(updated);
      }
      setHistoryByPlanningId((current) => {
        const currentHistory = getPlanningHistory(current, planningId);
        const nextHistory = direction === "undo" ? commitUndo(currentHistory) : commitRedo(currentHistory);
        return setPlanningHistory(current, planningId, { ...nextHistory, revision: updated.revision });
      });
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
          [planningId]: {
            projectId: revisionConflict.projectId,
            expectedRevision: revisionConflict.expectedRevision,
            currentRevision: revisionConflict.currentRevision,
            message: "Ce planning a été modifié entre-temps : recharge-le avant de continuer.",
          },
        }));
        return;
      }
      if (selectedPlanningIdRef.current === planningId) {
        const message =
          cause instanceof ApiError
            ? cause.message
            : direction === "undo"
              ? "Impossible d'annuler la dernière modification."
              : "Impossible de rétablir la modification annulée.";
        setRetryableError(message, () => void applyPlanningHistoryCommand(direction));
      }
    } finally {
      setPlanningMutationBusy(false);
    }
  }

  return applyPlanningHistoryCommand;
}
