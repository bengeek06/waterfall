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
  type ImportDiff,
} from "@/lib/backend";
import { clearSession, type SessionTokens } from "@/lib/session";

type AppRouter = ReturnType<typeof useRouter>;

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
      let batchStatus = await getImportBatchStatus(importReview.batchId, session, onSessionRefresh);
      for (let index = 0; index < 20; index += 1) {
        if (batchStatus.status === "success" || batchStatus.status === "failed") {
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 300));
        batchStatus = await getImportBatchStatus(importReview.batchId, session, onSessionRefresh);
      }
      if (batchStatus.status !== "success") {
        throw new Error(batchStatus.errorMessage ?? "Import en échec.");
      }

      setImportReview(null);
      setImportFile(null);
      setImportFeedback("Import réussi. Actualisation du projet en cours...");

      const [projectRefresh, planningsRefresh] = await Promise.allSettled([
        getProject(projectId, session, onSessionRefresh),
        listPlannings(projectId, session, onSessionRefresh),
      ]);
      const refreshFailures: string[] = [];
      if (projectRefresh.status === "fulfilled") {
        setProject(projectRefresh.value);
      } else {
        if (projectRefresh.reason instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        refreshFailures.push("le projet");
      }
      if (planningsRefresh.status === "fulfilled") {
        setPlannings(planningsRefresh.value);
      } else {
        if (planningsRefresh.reason instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        refreshFailures.push("les versions de planning");
      }

      const refreshedProject = projectRefresh.status === "fulfilled" ? projectRefresh.value : project;
      const refreshedPlannings = planningsRefresh.status === "fulfilled" ? planningsRefresh.value : plannings;
      const nextPlanningId =
        refreshedProject?.displayed_planning_id ?? refreshedPlannings.at(-1)?.id ?? null;
      if (nextPlanningId) {
        try {
          const updatedDetail = await getPlanning(projectId, nextPlanningId, session, onSessionRefresh);
          setPlanningDetail(updatedDetail);
        } catch (cause) {
          if (cause instanceof SessionExpiredError) {
            clearSession();
            router.push("/login");
            return;
          }
          refreshFailures.push("le détail du planning");
        }
      } else {
        setPlanningDetail(null);
      }
      updateSelectedPlanningId(nextPlanningId);
      setImportFeedback(
        refreshFailures.length
          ? `Import réussi, mais ${refreshFailures.join(" et ")} n'ont pas pu être actualisés. Recharge la page pour voir l'état à jour.`
          : "Import réussi. Le planning affiché a été actualisé.",
      );
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
