import type { useRouter } from "next/navigation";

import {
  ApiError,
  getImportBatchStatus,
  getPlanning,
  getProject,
  listPlannings,
  Planning,
  PlanningDetail,
  Project,
  runImportBatch,
  SessionExpiredError,
  type ImportBatchStatus,
  type ImportDiff,
} from "@/lib/backend";
import { clearSession, type SessionTokens } from "@/lib/session";

type AppRouter = ReturnType<typeof useRouter>;

// Polls an import batch's status until it reaches a terminal state ("success" or "failed") or the
// retry budget (20 attempts, 300ms apart) is exhausted, then throws if the batch didn't succeed.
// Extracted from confirmPlanningImport (E4-19 / #205) -- mechanical move, same iteration count,
// delay and error message as before.
export async function pollImportBatchStatus(
  batchId: number,
  session: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<ImportBatchStatus> {
  let batchStatus = await getImportBatchStatus(batchId, session, onSessionRefresh);
  for (let index = 0; index < 20; index += 1) {
    if (batchStatus.status === "success" || batchStatus.status === "failed") {
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
    batchStatus = await getImportBatchStatus(batchId, session, onSessionRefresh);
  }
  if (batchStatus.status !== "success") {
    throw new Error(batchStatus.errorMessage ?? "Import en échec.");
  }
  return batchStatus;
}

// Picks the planning to display after a successful import: the project's displayed planning if
// the project refresh succeeded, otherwise the most recent planning, or `null` if there is none.
// Extracted from confirmPlanningImport (E4-19 / #205).
export function pickNextPlanningId(refreshedProject: Project | null, refreshedPlannings: Planning[]): number | null {
  return refreshedProject?.displayed_planning_id ?? refreshedPlannings.at(-1)?.id ?? null;
}

// Builds the post-import feedback message: the happy-path message, or a combined "partial
// failure" message listing what couldn't be refreshed. Extracted from confirmPlanningImport
// (E4-19 / #205).
export function buildImportFeedbackMessage(refreshFailures: string[]): string {
  return refreshFailures.length
    ? `Import réussi, mais ${refreshFailures.join(" et ")} n'ont pas pu être actualisés. Recharge la page pour voir l'état à jour.`
    : "Import réussi. Le planning affiché a été actualisé.";
}

// Classifies a settled promise result from the post-import refresh: applies the success value via
// `onSuccess`, flags a session expiry so the caller can redirect, or records `failureLabel` for the
// combined "partial failure" feedback message. Extracted from confirmPlanningImport (E4-19 / #205).
export function applySettledRefresh<T>(
  result: PromiseSettledResult<T>,
  onSuccess: (value: T) => void,
  failureLabel: string,
): { sessionExpired: boolean; failureLabel: string | null } {
  if (result.status === "fulfilled") {
    onSuccess(result.value);
    return { sessionExpired: false, failureLabel: null };
  }
  if (result.reason instanceof SessionExpiredError) {
    return { sessionExpired: true, failureLabel: null };
  }
  return { sessionExpired: false, failureLabel };
}

// Applies both post-import settled refreshes (project + plannings), aggregating failure labels
// and short-circuiting on a session expiry from either one. Extracted from confirmPlanningImport
// (E4-19 / #205) to fold the two near-identical `applySettledRefresh` branches into one call.
export function applyImportRefreshes(
  projectRefresh: PromiseSettledResult<Project>,
  planningsRefresh: PromiseSettledResult<Planning[]>,
  setProject: (project: Project) => void,
  setPlannings: (plannings: Planning[]) => void,
): { sessionExpired: boolean; refreshFailures: string[] } {
  const refreshFailures: string[] = [];

  const projectOutcome = applySettledRefresh(projectRefresh, setProject, "le projet");
  if (projectOutcome.sessionExpired) {
    return { sessionExpired: true, refreshFailures };
  }
  if (projectOutcome.failureLabel) {
    refreshFailures.push(projectOutcome.failureLabel);
  }

  const planningsOutcome = applySettledRefresh(planningsRefresh, setPlannings, "les versions de planning");
  if (planningsOutcome.sessionExpired) {
    return { sessionExpired: true, refreshFailures };
  }
  if (planningsOutcome.failureLabel) {
    refreshFailures.push(planningsOutcome.failureLabel);
  }

  return { sessionExpired: false, refreshFailures };
}

// Refreshes the planning detail for `nextPlanningId` (or clears it if there is none), pushing a
// failure label into `refreshFailures` on error. Returns `true` if the session expired, in which
// case the caller must redirect and stop. Extracted from confirmPlanningImport (E4-19 / #205).
export async function refreshPlanningDetailAfterImport(
  projectId: number,
  nextPlanningId: number | null,
  activeSession: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
  setPlanningDetail: (detail: PlanningDetail | null) => void,
  refreshFailures: string[],
): Promise<boolean> {
  if (!nextPlanningId) {
    setPlanningDetail(null);
    return false;
  }
  try {
    const updatedDetail = await getPlanning(projectId, nextPlanningId, activeSession, onSessionRefresh);
    setPlanningDetail(updatedDetail);
    return false;
  } catch (cause) {
    if (cause instanceof SessionExpiredError) {
      return true;
    }
    refreshFailures.push("le détail du planning");
    return false;
  }
}

interface UsePlanningImportParams {
  session: SessionTokens | null;
  project: Project | null;
  importReview: { batchId: number; diff: ImportDiff } | null;
  projectId: number;
  onSessionRefresh: (next: SessionTokens) => void;
  router: AppRouter;
  plannings: Planning[];
  setProject: (project: Project) => void;
  setPlannings: (plannings: Planning[]) => void;
  setPlanningDetail: (detail: PlanningDetail | null) => void;
  updateSelectedPlanningId: (next: number | null) => void;
  setImportReview: (review: { batchId: number; diff: ImportDiff } | null) => void;
  setImportFile: (file: File | null) => void;
  setImportFeedback: (message: string | null) => void;
  setImportBusy: (busy: boolean) => void;
  setError: (message: string | null) => void;
}

// Extracted verbatim from ProjectDetailsPage (E4-10 / #150): confirms a previously-reviewed
// MS Project import batch, polls it to completion, then refreshes the project/plannings/planning
// detail state. Pure mechanical move -- see page.tsx call site (import review "Confirmer" button)
// for wiring. preparePlanningImport (the earlier step of the same import flow) is out of scope
// for this ticket and stays in page.tsx.
export function usePlanningImport({
  session,
  project,
  importReview,
  projectId,
  onSessionRefresh,
  router,
  plannings,
  setProject,
  setPlannings,
  setPlanningDetail,
  updateSelectedPlanningId,
  setImportReview,
  setImportFile,
  setImportFeedback,
  setImportBusy,
  setError,
}: UsePlanningImportParams) {
  async function confirmPlanningImport() {
    if (!session || !project || !importReview) {
      return;
    }
    setImportBusy(true);
    setError(null);
    setImportFeedback(null);
    try {
      await runImportBatch(importReview.batchId, session, onSessionRefresh, false, true);
      await pollImportBatchStatus(importReview.batchId, session, onSessionRefresh);

      setImportReview(null);
      setImportFile(null);
      setImportFeedback("Import réussi. Actualisation du projet en cours...");

      const [projectRefresh, planningsRefresh] = await Promise.allSettled([
        getProject(projectId, session, onSessionRefresh),
        listPlannings(projectId, session, onSessionRefresh),
      ]);
      const refreshesOutcome = applyImportRefreshes(projectRefresh, planningsRefresh, setProject, setPlannings);
      if (refreshesOutcome.sessionExpired) {
        clearSession();
        router.push("/login");
        return;
      }
      const refreshFailures = refreshesOutcome.refreshFailures;

      const refreshedProject = projectRefresh.status === "fulfilled" ? projectRefresh.value : project;
      const refreshedPlannings = planningsRefresh.status === "fulfilled" ? planningsRefresh.value : plannings;
      const nextPlanningId = pickNextPlanningId(refreshedProject, refreshedPlannings);

      const detailSessionExpired = await refreshPlanningDetailAfterImport(
        projectId,
        nextPlanningId,
        session,
        onSessionRefresh,
        setPlanningDetail,
        refreshFailures,
      );
      if (detailSessionExpired) {
        clearSession();
        router.push("/login");
        return;
      }

      updateSelectedPlanningId(nextPlanningId);
      setImportFeedback(buildImportFeedbackMessage(refreshFailures));
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible d'importer le planning.");
    } finally {
      setImportBusy(false);
    }
  }

  return confirmPlanningImport;
}
