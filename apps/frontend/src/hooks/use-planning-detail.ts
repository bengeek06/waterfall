import { useEffect } from "react";
import type { RefObject } from "react";
import type { useRouter } from "next/navigation";

import {
  ApiError,
  getPlanning,
  getPlanningStructureDraft,
  PlanningDetail,
  SessionExpiredError,
} from "@/lib/backend";
import { clearSession, type SessionTokens } from "@/lib/session";
import { getPlanningHistory, type PlanningHistoryByPlanningId } from "@/lib/planning-history";
import {
  getPlanningStructureDraftRows,
  structureToDraftRows,
  type PlanningStructureDraftRow,
} from "@/lib/planning-structure";

type AppRouter = ReturnType<typeof useRouter>;

// Mirrors the inline conflict record type declared alongside planningConflictByPlanningId in
// ProjectDetailsPage (page.tsx) -- kept as a local duplicate rather than imported, so this hook
// has no coupling to the component beyond the parameters it is passed.
export type PlanningRevisionConflict = {
  projectId: number;
  expectedRevision: number;
  currentRevision: number;
  message: string;
};

interface UsePlanningDetailEffectParams {
  session: SessionTokens | null;
  selectedPlanningId: number | null;
  projectId: number;
  onSessionRefresh: (next: SessionTokens) => void;
  router: AppRouter;
  planningLoadGenerationRef: RefObject<number>;
  selectedPlanningIdRef: RefObject<number | null>;
  historyByPlanningIdRef: RefObject<PlanningHistoryByPlanningId>;
  setPlanningDetail: (detail: PlanningDetail | null) => void;
  setPlanningDetailBusy: (busy: boolean) => void;
  setPlanningConflictByPlanningId: (
    updater: (
      previous: Record<number, PlanningRevisionConflict>,
    ) => Record<number, PlanningRevisionConflict>,
  ) => void;
  setStructureDraft: (rows: PlanningStructureDraftRow[]) => void;
  setError: (message: string | null) => void;
}

// Extracted verbatim from ProjectDetailsPage (E4-10 / #150): loads the currently-selected
// planning's detail (and applies the saved structure draft) whenever the selection, session or
// project changes. Pure mechanical move -- see page.tsx call site for wiring.
export function usePlanningDetailEffect({
  session,
  selectedPlanningId,
  projectId,
  onSessionRefresh,
  router,
  planningLoadGenerationRef,
  selectedPlanningIdRef,
  historyByPlanningIdRef,
  setPlanningDetail,
  setPlanningDetailBusy,
  setPlanningConflictByPlanningId,
  setStructureDraft,
  setError,
}: UsePlanningDetailEffectParams) {
  useEffect(() => {
    let cancelled = false;

    async function loadPlanningDetail() {
      const loadGeneration = ++planningLoadGenerationRef.current;
      if (!session || selectedPlanningId === null) {
        setPlanningDetail(null);
        setPlanningDetailBusy(false);
        return;
      }
      setPlanningDetail(null);
      setPlanningDetailBusy(true);
      try {
        const detail = await getPlanning(projectId, selectedPlanningId, session, onSessionRefresh);
        const savedDraft = await getPlanningStructureDraft(projectId, session, onSessionRefresh);
        if (
          !cancelled &&
          loadGeneration === planningLoadGenerationRef.current &&
          selectedPlanningIdRef.current === selectedPlanningId
        ) {
          const history = getPlanningHistory(historyByPlanningIdRef.current, selectedPlanningId);
          const historyRevision = history.revision;
          if (historyRevision !== null && historyRevision !== detail.revision) {
            setPlanningConflictByPlanningId((previous) => ({
              ...previous,
              [selectedPlanningId]: {
                projectId,
                expectedRevision: historyRevision,
                currentRevision: detail.revision,
                message: "Ce planning a été modifié entre-temps : recharge-le avant de continuer.",
              },
            }));
          }
          setPlanningDetail(detail);
          const rows = savedDraft
            ? structureToDraftRows(savedDraft.structure)
            : getPlanningStructureDraftRows(detail);
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
        }
      } catch (cause) {
        if (cancelled || loadGeneration !== planningLoadGenerationRef.current) {
          return;
        }
        if (cause instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        setError(cause instanceof ApiError ? cause.message : "Impossible de charger le planning.");
      } finally {
        if (!cancelled && loadGeneration === planningLoadGenerationRef.current) {
          setPlanningDetailBusy(false);
        }
      }
    }

    void loadPlanningDetail();
    return () => {
      cancelled = true;
    };
  }, [
    onSessionRefresh,
    projectId,
    router,
    selectedPlanningId,
    session,
    historyByPlanningIdRef,
    planningLoadGenerationRef,
    selectedPlanningIdRef,
    setError,
    setPlanningConflictByPlanningId,
    setPlanningDetail,
    setPlanningDetailBusy,
    setStructureDraft,
  ]);
}
