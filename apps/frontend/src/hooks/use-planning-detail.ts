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
import {
  getPlanningStructureDraftRows,
  structureToDraftRows,
  type PlanningStructureDraftRow,
} from "@/lib/planning-structure";

type AppRouter = ReturnType<typeof useRouter>;

// E14-10 (#336): this hook no longer belongs to the planning editor. The Planning tab reads a
// **revision** now (see use-revision-planning.ts); what is left here is the legacy planning detail
// the *Devis* tab still needs -- its parent-task selector and its post-create refresh -- until
// E14-11 (#337) moves it too, plus the structure draft the lotissement editor hydrates from.
//
// The revision-conflict tracking that used to live here went with the undo/redo stacks it served:
// `PUT .../tasks/restore` no longer exists, and the revision model carries its own optimistic lock
// (REVISION_LOCK_CONFLICT, see use-revision-planning.ts).

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
  setPlanningDetail: (detail: PlanningDetail | null) => void;
  setPlanningDetailBusy: (busy: boolean) => void;
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
  setPlanningDetail,
  setPlanningDetailBusy,
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
          setPlanningDetail(detail);
          const rows = deriveStructureDraftRows(savedDraft, detail);
          if (rows) {
            setStructureDraft(rows);
          }
        }
      } catch (cause) {
        if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
          clearSession();
          router.push("/login");
          return;
        }
        if (!isPlanningLoadStillActive(cancelled, loadGeneration, planningLoadGenerationRef.current)) {
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
    planningLoadGenerationRef,
    selectedPlanningIdRef,
    setError,
    setPlanningDetail,
    setPlanningDetailBusy,
    setStructureDraft,
  ]);
}
