import { useEffect } from "react";
import type { RefObject } from "react";
import type { useRouter } from "next/navigation";

import {
  ApiError,
  getPlanning,
  getPlanningStructureDraft,
  PlanningDetail,
  PlanningStructureDraftRead,
  SessionExpiredError,
} from "@/lib/backend";
import { clearSession, type SessionTokens } from "@/lib/session";
import { getPlanningHistory, type PlanningHistoryByPlanningId, type PlanningHistoryState } from "@/lib/planning-history";
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

// Derives the structure-draft rows to apply after loading a planning: the saved draft's rows if
// there is one, otherwise the rows inferred from the planning detail itself -- but only if every
// row is fully filled in (post/lot keys, names and deliverables all non-blank); an incomplete
// derivation returns `null` so the caller leaves the current draft untouched. Extracted from
// loadPlanningDetail (E4-20 / #206) -- same ternary + `every(...)` validation as before.
export function deriveStructureDraftRows(
  savedDraft: PlanningStructureDraftRead | null,
  detail: PlanningDetail,
): PlanningStructureDraftRow[] | null {
  const rows = savedDraft ? structureToDraftRows(savedDraft.structure) : getPlanningStructureDraftRows(detail);
  const isComplete =
    rows.length > 0 &&
    rows.every(
      (row) =>
        row.postKey.trim() &&
        row.postName.trim() &&
        row.lotKey.trim() &&
        row.lotName.trim() &&
        row.deliverables.trim(),
    );
  return isComplete ? rows : null;
}

// Detects a revision conflict between the locally-tracked undo/redo history and the just-loaded
// planning detail, and records it via `setPlanningConflictByPlanningId` if one is found (no-op
// when the history has no tracked revision yet, or when it still matches). Extracted from
// loadPlanningDetail (E4-20 / #206) -- same condition and conflict payload as before.
export function recordRevisionConflictIfAny(
  history: PlanningHistoryState,
  detail: PlanningDetail,
  selectedPlanningId: number,
  projectId: number,
  setPlanningConflictByPlanningId: (
    updater: (
      previous: Record<number, PlanningRevisionConflict>,
    ) => Record<number, PlanningRevisionConflict>,
  ) => void,
): void {
  const historyRevision = history.revision;
  if (historyRevision === null || historyRevision === detail.revision) {
    return;
  }
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

// Guards `loadPlanningDetail`'s catch/finally branches: whether a load that was scheduled as
// `loadGeneration` is still the most recent one and hasn't been cancelled (by the effect's
// cleanup running -- e.g. selection/session/project changed, or the component unmounted).
// Extracted from loadPlanningDetail (E4-20 / #206).
export function isPlanningLoadStillActive(
  cancelled: boolean,
  loadGeneration: number,
  currentGeneration: number,
): boolean {
  return !cancelled && loadGeneration === currentGeneration;
}

// Guards `loadPlanningDetail`'s try branch: same as `isPlanningLoadStillActive`, plus the
// additional check (not needed in the catch/finally branches) that the selection hasn't moved on
// to a different planning while this load was in flight. Extracted from loadPlanningDetail
// (E4-20 / #206) -- kept distinct from `isPlanningLoadStillActive` rather than merged, since the
// two guards are not equivalent.
export function isPlanningLoadResultCurrent(
  cancelled: boolean,
  loadGeneration: number,
  currentGeneration: number,
  selectedPlanningIdRefCurrent: number | null,
  selectedPlanningId: number,
): boolean {
  return (
    isPlanningLoadStillActive(cancelled, loadGeneration, currentGeneration) &&
    selectedPlanningIdRefCurrent === selectedPlanningId
  );
}

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
          isPlanningLoadResultCurrent(
            cancelled,
            loadGeneration,
            planningLoadGenerationRef.current,
            selectedPlanningIdRef.current,
            selectedPlanningId,
          )
        ) {
          const history = getPlanningHistory(historyByPlanningIdRef.current, selectedPlanningId);
          recordRevisionConflictIfAny(
            history,
            detail,
            selectedPlanningId,
            projectId,
            setPlanningConflictByPlanningId,
          );
          setPlanningDetail(detail);
          const rows = deriveStructureDraftRows(savedDraft, detail);
          if (rows) {
            setStructureDraft(rows);
          }
        }
      } catch (cause) {
        if (!isPlanningLoadStillActive(cancelled, loadGeneration, planningLoadGenerationRef.current)) {
          return;
        }
        if (cause instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        setError(cause instanceof ApiError ? cause.message : "Impossible de charger le planning.");
      } finally {
        if (isPlanningLoadStillActive(cancelled, loadGeneration, planningLoadGenerationRef.current)) {
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
