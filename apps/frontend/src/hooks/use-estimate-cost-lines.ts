import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import type { useRouter } from "next/navigation";

import {
  ApiError,
  applyEstimateCostLineMilestoneTemplate,
  createEstimateCostLine,
  createEstimateRoleAssignment,
  createEstimateTask,
  createProjectEstimate,
  deleteEstimateCostLine,
  deleteEstimateRoleAssignment,
  describeMissingRateCoverage,
  EstimateCostLine,
  EstimateCostLineMilestonesCreate,
  type EstimateGridNodeMove,
  EstimateRoleAssignment,
  EstimateRoleAssignmentCreate,
  EstimateTaskRow,
  EstimateValidationWarning,
  exportEstimateExcel,
  getCalendar,
  getEstimateRevisionConflict,
  getMissingRateCoverage,
  getPlanning,
  getProjectCostCodes,
  getResourceRoles,
  isEstimateTaskCreateRequiresPlanningDraft,
  listEstimateCostLines,
  listEstimateRoleAssignments,
  listEstimateTaskRows,
  moveEstimateGridNodes,
  PlanningDetail,
  Project,
  ProjectCostCode,
  ProjectEstimate,
  ResourceNode,
  ResourceRole,
  SessionExpiredError,
  updateEstimateCostLine,
  updateEstimateRoleAssignment,
  updateTaskName,
  validateProjectEstimate,
} from "@/lib/backend";
import { clearSession, type SessionTokens } from "@/lib/session";
import type { ProjectTab } from "@/components/project-tabs";

type AppRouter = ReturnType<typeof useRouter>;

export type CostLineDraft = {
  categoryId: string;
  label: string;
  quantity: string;
  unitCost: string;
  plannedDate: string;
  // E12-04/#276: optional task attachment, wired straight to EstimateCostLineCreate/Update's own
  // `task_id`. "" means "Aucune" (task_id: null) -- same empty-string-means-null convention as
  // `plannedDate` above, kept as a string throughout the draft since it round-trips through a
  // plain `<select>`.
  taskId: string;
};

// `planned_date` (#66 / E6-05) round-trips through a plain `<input type="date">`, so the draft
// state is always a `yyyy-MM-dd` string (or "" for "no date"), converted to/from the backend's
// payload only at the API call boundary -- same convention as `quantity`/`unitCost` above.
//
// Unlike lib/planning-schedule.ts's schedule fields, `planned_date` is a `DateTime(timezone=True)`
// column: the backend always returns a string carrying an explicit UTC offset/timezone. On write,
// though, Pydantic parses a bare `yyyy-MM-dd` string as a *naive* datetime (verified against the
// installed pydantic version -- no tzinfo attached), not as "UTC midnight": whether that ends up
// stored as UTC midnight depends on the database session's own timezone setting, which nothing in
// this codebase pins explicitly. Appending an explicit `T00:00:00Z` removes that ambiguity
// entirely at the client boundary, independently of server-side configuration.
function plannedDateDraftToPayload(value: string): string | null {
  return value ? `${value}T00:00:00Z` : null;
}

interface UseEstimateCostLinesParams {
  session: SessionTokens | null;
  project: Project | null;
  projectId: number;
  selectedEstimateId: number | null;
  estimates: ProjectEstimate[];
  setEstimates: (updater: (previous: ProjectEstimate[]) => ProjectEstimate[]) => void;
  setSelectedEstimateId: (id: number) => void;
  setActiveTab: (tab: ProjectTab) => void;
  setCostLines: (updater: (previous: EstimateCostLine[]) => EstimateCostLine[]) => void;
  // E12-04/#276: a direct setter (not an updater), since every writer below now refetches the
  // full list rather than approximating it via an increment -- see
  // refreshEstimateTaskRowsAfterTaskCreation's doc comment for why an exact refetch replaced the
  // former `setEstimateTaskRowCount((previous) => previous + n)` bumps.
  setEstimateTaskRows: (rows: EstimateTaskRow[]) => void;
  // Wiring for the post-creation planning refetch below (Haute review finding on E6-06/#67):
  // submitCreateTask attaches the new task to the project's *displayed* planning, so
  // `planningDetail` -- otherwise only loaded by usePlanningDetailEffect -- must be refreshed
  // here too, or the "Tâche parente" selector and the Planning tab never see it without a
  // full page reload. `selectedPlanningIdRef` mirrors the same ref page.tsx already threads
  // through use-planning-tree-mutations.ts, so the guard after the refetch's `await` uses the
  // exact same up-to-date-read pattern as the rest of the codebase.
  selectedPlanningId: number | null;
  selectedPlanningIdRef: RefObject<number | null>;
  setPlanningDetail: (detail: PlanningDetail | null) => void;
  // E12-06/#278: same direct-setter/full-refetch convention as setEstimateTaskRows above --
  // every role-assignment mutation refetches the exact list rather than approximating it.
  setEstimateRoleAssignments: (assignments: EstimateRoleAssignment[]) => void;
  // E12-10/#292: the organization referential, used by the "Ajouter une ligne MO" dialog's
  // Dpt 1er niveau -> Dpt 2eme niveau cascade (root nodes / a chosen root's direct children) --
  // already loaded once per project by page.tsx for CostLinesTable's own Dept column, reused
  // here rather than fetched again.
  resourceNodes: ResourceNode[];
  onSessionRefresh: (next: SessionTokens) => void;
  router: AppRouter;
  setError: (message: string | null) => void;
}

// Extracted from ProjectDetailsPage (E4-11 / #151): owns every piece of state and every handler
// specific to the "Devis" tab's cost lines (add/edit/delete/validate/export/new-draft). Pure
// mechanical move -- see page.tsx call site (Devis tab) for wiring.
export function useEstimateCostLines({
  session,
  project,
  projectId,
  selectedEstimateId,
  estimates,
  setEstimates,
  setSelectedEstimateId,
  setActiveTab,
  setCostLines,
  setEstimateTaskRows,
  selectedPlanningId,
  selectedPlanningIdRef,
  setPlanningDetail,
  setEstimateRoleAssignments,
  resourceNodes,
  onSessionRefresh,
  router,
  setError,
}: UseEstimateCostLinesParams) {
  const [costLineDraft, setCostLineDraft] = useState<CostLineDraft>({
    categoryId: "",
    label: "",
    quantity: "1",
    unitCost: "0",
    plannedDate: "",
    taskId: "",
  });
  const [costLinePendingDelete, setCostLinePendingDelete] = useState<EstimateCostLine | null>(null);
  // E12-06/#278: same AlertDialog pending-delete pattern as costLinePendingDelete above, for a
  // role-assignment ("MO") row -- see EstimateRoleAssignmentDeleteDialog (page.tsx call site).
  const [roleAssignmentPendingDelete, setRoleAssignmentPendingDelete] = useState<EstimateRoleAssignment | null>(null);
  const [estimateValidationOpen, setEstimateValidationOpen] = useState(false);
  const [estimateBusy, setEstimateBusy] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [projectCostCodes, setProjectCostCodes] = useState<ProjectCostCode[]>([]);
  const [selectedCostLineIds, setSelectedCostLineIds] = useState<Set<number>>(new Set());
  const [bulkCostCodeId, setBulkCostCodeId] = useState("");
  const [bulkAssignBusy, setBulkAssignBusy] = useState(false);
  const [validationWarnings, setValidationWarnings] = useState<EstimateValidationWarning[]>([]);

  // E6-06/#67: "add a task to the planning" dialog, launched from this tab. Kept here rather
  // than a standalone hook so it can reuse this hook's selectedEstimateIdRef guard below
  // instead of duplicating its own -- see submitCreateTask for the guarded mutation.
  const [taskDialogOpen, setTaskDialogOpen] = useState(false);
  const [taskDraftName, setTaskDraftName] = useState("");
  const [taskDraftIsMilestone, setTaskDraftIsMilestone] = useState(false);
  const [taskDraftParentUid, setTaskDraftParentUid] = useState("");
  const [taskCreateError, setTaskCreateError] = useState<string | null>(null);
  // True only for the specific 409 raised when the project's displayed planning is not a
  // draft -- lets the dialog offer a "reopen the structure" action instead of just text.
  const [taskCreateRequiresPlanningDraft, setTaskCreateRequiresPlanningDraft] = useState(false);

  // E6-07/#68: "apply a milestone template" dialog, launched from a single cost line row in
  // CostLinesTable. Kept alongside the task-creation dialog's state above for the same reason:
  // it reuses this hook's selectedEstimateIdRef guard and refreshPlanningDetailAfterTaskCreation
  // helper rather than duplicating either. `milestoneLineId` identifies which cost line the
  // dialog currently targets (the backend, not this dialog, decides whether that line is a
  // labor line and rejects it with a 400 -- see submitMilestoneTemplate's error handling).
  const [milestoneDialogOpen, setMilestoneDialogOpen] = useState(false);
  const [milestoneLineId, setMilestoneLineId] = useState<number | null>(null);
  const [milestoneTemplate, setMilestoneTemplate] = useState<EstimateCostLineMilestonesCreate["template"]>(
    "fourniture",
  );
  const [milestoneIntermediateCount, setMilestoneIntermediateCount] = useState("0");
  const [milestoneLagMinutes, setMilestoneLagMinutes] = useState("0");
  const [milestoneError, setMilestoneError] = useState<string | null>(null);
  // Same meaning as taskCreateRequiresPlanningDraft above -- both endpoints raise the exact same
  // structured 409 code.
  const [milestoneRequiresPlanningDraft, setMilestoneRequiresPlanningDraft] = useState(false);

  // E12-06/#278: "Ajouter une ligne MO" dialog, launched from this tab -- creates an
  // EstimateRoleAssignment. Kept alongside the task-creation/milestone-template dialogs' state
  // above for the same reason: it reuses this hook's selectedEstimateIdRef guard and a
  // refetch-after-mutation helper of its own (refreshEstimateRoleAssignments below), rather than
  // duplicating either.
  const [roleAssignmentDialogOpen, setRoleAssignmentDialogOpen] = useState(false);
  // E12-10/#292: two-level department cascade (replaces the single "Nœud organisationnel"
  // selector) -- "Dpt 1er niveau" only ever lists root nodes (`ResourceNode.parent_id === null`),
  // "Dpt 2eme niveau" only that root's own direct children (empty when it has none, in which case
  // dept1 itself is the effective node the role list below is fetched for).
  const [roleAssignmentDept1Id, setRoleAssignmentDept1Id] = useState("");
  const [roleAssignmentDept2Id, setRoleAssignmentDept2Id] = useState("");
  // The node id the currently-loading/loaded `roleAssignmentRoles` request was actually fetched
  // for -- updated synchronously at every write site below (not via a `useEffect`, which would
  // introduce exactly the race window this exists to close), so a slower-resolving request for a
  // department the user has since navigated away from can detect that once it comes back:
  // network latency isn't guaranteed to preserve request order, so the *first* department's roles
  // could otherwise land in the selector after the user has already moved on to the second,
  // letting them pick a role that actually belongs to the wrong department. Exact same guard
  // shape as `selectedNodeIdRef`/`rolesPanelGenerationRef` in app/resources/page.tsx, which fixes
  // the identical race for the identical "roles filtered by node" fetch.
  const roleAssignmentRolesRequestNodeIdRef = useRef("");
  // Same race-guard shape as roleAssignmentRolesRequestNodeIdRef above, for the "Heures"
  // calendar-prefill fetch triggered by picking a role (see updateRoleAssignmentRoleId).
  const roleAssignmentHoursPrefillRoleIdRef = useRef("");
  // The roles of the node currently chosen in the dialog -- loaded on demand (never the whole
  // referential up front), see loadRoleAssignmentRolesForNode below.
  const [roleAssignmentRoles, setRoleAssignmentRoles] = useState<ResourceRole[]>([]);
  const [roleAssignmentRolesLoading, setRoleAssignmentRolesLoading] = useState(false);
  const [roleAssignmentRoleId, setRoleAssignmentRoleId] = useState("");
  const [roleAssignmentTaskId, setRoleAssignmentTaskId] = useState("");
  const [roleAssignmentQuantity, setRoleAssignmentQuantity] = useState("1");
  const [roleAssignmentHours, setRoleAssignmentHours] = useState("0");
  const [roleAssignmentCostCodeId, setRoleAssignmentCostCodeId] = useState("");
  const [roleAssignmentComment, setRoleAssignmentComment] = useState("");
  const [roleAssignmentError, setRoleAssignmentError] = useState<string | null>(null);

  const selectedEstimate = estimates.find((estimate) => estimate.id === selectedEstimateId) ?? null;

  // Loaded once per project, non-blocking: mirrors ProjectDetailsPage's loadCostCategories (the
  // cost-line "add" form's category picker) -- if it fails, the bulk-assignment selector below
  // simply has no options, it doesn't block or degrade the rest of the tab.
  useEffect(() => {
    async function loadProjectCostCodes() {
      if (!session) {
        return;
      }
      try {
        const codes = await getProjectCostCodes(projectId, session, onSessionRefresh);
        setProjectCostCodes(codes);
      } catch {
        // Non-blocking: the bulk-assignment selector simply stays empty without cost codes.
      }
    }

    void loadProjectCostCodes();
  }, [onSessionRefresh, projectId, session]);

  // A selection made on one estimate version's cost lines has no meaning once the user switches
  // to another version -- clear it so a stale set of ids can't silently carry over. Deliberate
  // synchronous render-body write (not a useEffect), same precedent as PlanningTreeTable's
  // versionKey-change reset: it must land within the same render as the selectedEstimateId prop
  // change, so no frame is ever painted with the previous version's selection still applied.
  const [renderedEstimateId, setRenderedEstimateId] = useState(selectedEstimateId);
  if (selectedEstimateId !== renderedEstimateId) {
    setRenderedEstimateId(selectedEstimateId);
    setSelectedCostLineIds(new Set());
    // A validation warning banner on one estimate version has no meaning once the user
    // switches to another version -- same rationale as the selection reset above.
    setValidationWarnings([]);
  }
  // Read through this ref (not `selectedEstimateId` directly) after an `await` in
  // `bulkAssignCostCode`: the estimate version can switch while a bulk PATCH batch is
  // still in flight (nothing currently disables the version selector while busy), and a
  // stale batch's success/failure banner must never be attributed to whatever version
  // happens to be displayed once it resolves. React forbids writing to a ref during
  // render, so this is kept fresh via useLayoutEffect rather than a synchronous body
  // write -- same precedent as use-planning-delete-selection.ts's versionKeyRef.
  const selectedEstimateIdRef = useRef(selectedEstimateId);
  useLayoutEffect(() => {
    selectedEstimateIdRef.current = selectedEstimateId;
  }, [selectedEstimateId]);

  function updateCostLineDraftCategory(value: string) {
    setCostLineDraft((prev) => ({ ...prev, categoryId: value }));
  }
  function updateCostLineDraftLabel(value: string) {
    setCostLineDraft((prev) => ({ ...prev, label: value }));
  }
  function updateCostLineDraftQuantity(value: string) {
    setCostLineDraft((prev) => ({ ...prev, quantity: value }));
  }
  function updateCostLineDraftUnitCost(value: string) {
    setCostLineDraft((prev) => ({ ...prev, unitCost: value }));
  }
  function updateCostLineDraftPlannedDate(value: string) {
    setCostLineDraft((prev) => ({ ...prev, plannedDate: value }));
  }
  function updateCostLineDraftTaskId(value: string) {
    setCostLineDraft((prev) => ({ ...prev, taskId: value }));
  }
  function requestDeleteCostLine(line: EstimateCostLine) {
    setCostLinePendingDelete(line);
  }
  function cancelDeleteCostLine() {
    setCostLinePendingDelete(null);
  }
  function requestDeleteRoleAssignment(assignment: EstimateRoleAssignment) {
    setRoleAssignmentPendingDelete(assignment);
  }
  function cancelDeleteRoleAssignment() {
    setRoleAssignmentPendingDelete(null);
  }
  function openEstimateValidation() {
    setEstimateValidationOpen(true);
  }
  function dismissValidationWarnings() {
    setValidationWarnings([]);
  }

  function updateBulkCostCodeId(value: string) {
    setBulkCostCodeId(value);
  }

  function openCreateTaskDialog() {
    setTaskDraftName("");
    setTaskDraftIsMilestone(false);
    setTaskDraftParentUid("");
    setTaskCreateError(null);
    setTaskCreateRequiresPlanningDraft(false);
    setTaskDialogOpen(true);
  }

  function closeCreateTaskDialog() {
    setTaskDialogOpen(false);
    setTaskDraftName("");
    setTaskDraftIsMilestone(false);
    setTaskDraftParentUid("");
    setTaskCreateError(null);
    setTaskCreateRequiresPlanningDraft(false);
  }

  function updateTaskDraftName(value: string) {
    setTaskDraftName(value);
  }
  function updateTaskDraftIsMilestone(value: boolean) {
    setTaskDraftIsMilestone(value);
  }
  function updateTaskDraftParentUid(value: string) {
    setTaskDraftParentUid(value);
  }

  // Haute review finding on #67: the backend just attached the new task to the project's
  // displayed planning (bumping its revision), but nothing else in this hook ever touches
  // `planningDetail` -- a full refetch (rather than an optimistic patch) is simpler and safer,
  // and createEstimateTask's response doesn't even carry the new task's `uid` (EstimateTaskRowRead
  // only exposes `task_id`) to build one from anyway. Extracted out of submitCreateTask purely to
  // keep that function under this file's complexity budget -- same stale-response guard
  // (`selectedPlanningIdRef`) as every other await in this file, and the same
  // session-expiry-first catch shape, just applied to a call whose own failure must never be
  // reported as a task-creation failure (the task itself was already created successfully).
  async function refreshPlanningDetailAfterTaskCreation(launchedPlanningId: number, tokens: SessionTokens) {
    try {
      const freshPlanningDetail = await getPlanning(projectId, launchedPlanningId, tokens, onSessionRefresh);
      if (selectedPlanningIdRef.current === launchedPlanningId) {
        setPlanningDetail(freshPlanningDetail);
      }
    } catch (refetchCause) {
      if (refetchCause instanceof SessionExpiredError || (refetchCause instanceof ApiError && refetchCause.status === 401)) {
        clearSession();
        router.push("/login");
      }
      // Otherwise non-blocking: a failed refresh only means the Planning tab/parent-task
      // selector show stale data until the next reload, not that the mutation itself failed.
    }
  }

  // E12-04/#276: refetches this estimate's task rows after a task-creating operation (task
  // creation #67 below, milestone template application #68 further down) -- replaces the
  // former approximate `setEstimateTaskRowCount((previous) => previous + n)` bumps with the
  // exact list, which the Devis grid now needs in full (task names/hierarchy/position), not
  // just a count. Same shape/guard as refreshPlanningDetailAfterTaskCreation just above:
  // `selectedEstimateIdRef` (not `selectedPlanningIdRef` -- task rows belong to the estimate,
  // not the planning) is read *after* the `await` since the estimate version can switch while
  // this request is in flight (nothing currently disables the version selector while busy), and
  // a stale response must never overwrite whatever version's task rows are displayed once it
  // resolves. Session-expiry-first catch shape, applied to a call whose own failure must never
  // be reported as the triggering mutation's failure (that mutation already succeeded).
  async function refreshEstimateTaskRowsAfterTaskCreation(launchedEstimateId: number, tokens: SessionTokens) {
    try {
      const freshTaskRows = await listEstimateTaskRows(projectId, launchedEstimateId, tokens, onSessionRefresh);
      if (selectedEstimateIdRef.current === launchedEstimateId) {
        setEstimateTaskRows(freshTaskRows);
      }
    } catch (refetchCause) {
      if (refetchCause instanceof SessionExpiredError || (refetchCause instanceof ApiError && refetchCause.status === 401)) {
        clearSession();
        router.push("/login");
      }
      // Otherwise non-blocking: a failed refresh only means the Devis grid shows a stale task
      // list until the next reload, not that the mutation itself failed.
    }
  }

  // E12-06/#278: refetches this estimate's role-assignment ("MO") rows after a create/update/
  // delete mutation, on the exact same shape/guard as refreshEstimateTaskRowsAfterTaskCreation
  // above -- an exact refetch rather than a local patch, per the deliver-batch convention already
  // established for this hook's other mutations.
  async function refreshEstimateRoleAssignments(launchedEstimateId: number, tokens: SessionTokens) {
    try {
      const fresh = await listEstimateRoleAssignments(projectId, launchedEstimateId, tokens, onSessionRefresh);
      if (selectedEstimateIdRef.current === launchedEstimateId) {
        setEstimateRoleAssignments(fresh);
      }
    } catch (refetchCause) {
      if (refetchCause instanceof SessionExpiredError || (refetchCause instanceof ApiError && refetchCause.status === 401)) {
        clearSession();
        router.push("/login");
      }
      // Otherwise non-blocking: a failed refresh only means the Devis grid shows a stale
      // role-assignment list until the next reload, not that the mutation itself failed.
    }
  }

  function openRoleAssignmentDialog() {
    roleAssignmentRolesRequestNodeIdRef.current = "";
    roleAssignmentHoursPrefillRoleIdRef.current = "";
    setRoleAssignmentDept1Id("");
    setRoleAssignmentDept2Id("");
    setRoleAssignmentRoles([]);
    setRoleAssignmentRoleId("");
    setRoleAssignmentTaskId("");
    setRoleAssignmentQuantity("1");
    setRoleAssignmentHours("0");
    setRoleAssignmentCostCodeId("");
    setRoleAssignmentComment("");
    setRoleAssignmentError(null);
    setRoleAssignmentDialogOpen(true);
  }

  function closeRoleAssignmentDialog() {
    setRoleAssignmentDialogOpen(false);
    setRoleAssignmentError(null);
  }

  // Loads the roles available for `nodeId` (E12-06/#278, E12-10/#292's Dpt1/Dpt2 cascade above
  // it) -- deliberately on demand (not preloaded for the whole referential up front, unlike
  // resourceNodes/resourceRoles/costRates in page.tsx): most Devis sessions never open this
  // dialog at all. `include_descendants: true` matches the org-tree convention already used
  // elsewhere in this codebase (getResourceRoles's own doc comment) -- a role attached anywhere
  // under `nodeId` is a legitimate candidate, not only one attached to it directly.
  async function loadRoleAssignmentRolesForNode(nodeId: string) {
    // Updated synchronously, before the `await` below -- see
    // `roleAssignmentRolesRequestNodeIdRef`'s own doc comment above for the exact race this closes.
    roleAssignmentRolesRequestNodeIdRef.current = nodeId;
    setRoleAssignmentRoleId("");
    setRoleAssignmentRoles([]);
    if (!session || !nodeId) {
      return;
    }
    setRoleAssignmentRolesLoading(true);
    try {
      const page = await getResourceRoles(session, onSessionRefresh, Number(nodeId), true);
      // Stale-response guard: see roleAssignmentRolesRequestNodeIdRef's own doc comment.
      if (roleAssignmentRolesRequestNodeIdRef.current === nodeId) {
        setRoleAssignmentRoles(page.items);
      }
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return;
      }
      // Non-blocking: the role selector simply stays empty, same convention as
      // loadProjectCostCodes (page.tsx).
    } finally {
      // Same guard as above: a stale request's `finally` must not clear the loading indicator
      // for the (still in-flight) current node's own request.
      if (roleAssignmentRolesRequestNodeIdRef.current === nodeId) {
        setRoleAssignmentRolesLoading(false);
      }
    }
  }

  // E12-10/#292: "Dpt 1er niveau" only ever lists root nodes (see roleAssignmentDept1Id's own
  // doc comment) -- picking one resets "Dpt 2eme niveau"/the role list, and, when that root has
  // no children at all, fetches roles directly against it (there is no more granular department
  // left to pick, matching this issue's own spec: "liste vide si aucun enfant").
  async function updateRoleAssignmentDept1Id(value: string) {
    setRoleAssignmentDept1Id(value);
    setRoleAssignmentDept2Id("");
    const hasChildren = resourceNodes.some((node) => String(node.parent_id ?? "") === value);
    if (!hasChildren) {
      await loadRoleAssignmentRolesForNode(value);
      return;
    }
    roleAssignmentRolesRequestNodeIdRef.current = "";
    setRoleAssignmentRoleId("");
    setRoleAssignmentRoles([]);
  }

  async function updateRoleAssignmentDept2Id(value: string) {
    setRoleAssignmentDept2Id(value);
    await loadRoleAssignmentRolesForNode(value);
  }

  // E12-10/#292: prefills "Heures" from the selected role's own calendar (the maximum
  // `hours_per_day` among its `CalendarWeekday`s with `hours_per_day > 0`) -- a role with no
  // `calendar_id`, or whose calendar has no such weekday, leaves the field untouched rather than
  // clearing it, matching this issue's own spec ("le champ reste vide" only ever means "never
  // force-prefilled", not "force-cleared").
  async function updateRoleAssignmentRoleId(value: string) {
    roleAssignmentHoursPrefillRoleIdRef.current = value;
    setRoleAssignmentRoleId(value);
    if (!session || !value) {
      return;
    }
    const role = roleAssignmentRoles.find((candidate) => String(candidate.id) === value);
    if (!role?.calendar_id) {
      return;
    }
    try {
      const calendar = await getCalendar(role.calendar_id, session, onSessionRefresh);
      if (roleAssignmentHoursPrefillRoleIdRef.current !== value) {
        return;
      }
      const maxHoursPerDay = Math.max(
        0,
        ...(calendar.weekdays ?? []).map((weekday) => Number(weekday.hours_per_day)).filter((hours) => hours > 0),
      );
      if (maxHoursPerDay > 0) {
        setRoleAssignmentHours(String(maxHoursPerDay));
      }
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
      }
      // Non-blocking otherwise: "Heures" simply stays whatever it already was.
    }
  }

  function updateRoleAssignmentTaskId(value: string) {
    setRoleAssignmentTaskId(value);
  }
  function updateRoleAssignmentQuantity(value: string) {
    setRoleAssignmentQuantity(value);
  }
  function updateRoleAssignmentHours(value: string) {
    setRoleAssignmentHours(value);
  }
  function updateRoleAssignmentCostCodeId(value: string) {
    setRoleAssignmentCostCodeId(value);
  }
  function updateRoleAssignmentComment(value: string) {
    setRoleAssignmentComment(value);
  }

  // Validates the dialog's numeric fields before any network call, mirroring the backend's own
  // constraints (quantity strictly positive, hours >= 0 -- see EstimateRoleAssignmentCreate.yaml)
  // -- extracted purely to keep submitCreateRoleAssignment under this file's complexity budget.
  function parseRoleAssignmentDraft(): { taskId: number; roleId: number; quantity: number; hours: number } | { error: string } {
    const taskId = Number(roleAssignmentTaskId);
    const roleId = Number(roleAssignmentRoleId);
    const quantity = Number(roleAssignmentQuantity);
    const hours = Number(roleAssignmentHours);
    if (!taskId || !roleId || !(quantity > 0) || !(hours >= 0)) {
      return { error: "Renseigne une tâche, un rôle, une quantité et un nombre d'heures valides." };
    }
    return { taskId, roleId, quantity, hours };
  }

  // Translates a submitCreateRoleAssignment/saveRoleAssignment failure into a French message --
  // extracted purely to keep those functions under this file's complexity budget. Callers must
  // handle SessionExpiredError/a post-refresh 401 before reaching this. `getMissingRateCoverage`
  // only ever matches createEstimateRoleAssignment's own 400 (E6-11/#175) -- harmless (returns
  // null) when called on updateEstimateRoleAssignment's generic 400/409, so both callers can share
  // this one helper.
  function describeRoleAssignmentError(cause: unknown, genericMessage: string): string {
    const missingRateCoverage = getMissingRateCoverage(cause);
    if (missingRateCoverage) {
      return describeMissingRateCoverage(missingRateCoverage);
    }
    if (cause instanceof ApiError && cause.status === 409) {
      return "Ce devis n'est plus modifiable.";
    }
    return cause instanceof ApiError ? cause.message : genericMessage;
  }

  // E12-06/#278: creates an EstimateRoleAssignment attached to a task of the selected (draft)
  // estimate. `selectedEstimateIdRef` guard mirrors submitCreateTask above: the user could switch
  // estimate version while this request is in flight (nothing currently disables the version
  // selector while busy), and a stale response must never be applied to whatever version is
  // displayed once it resolves.
  async function submitCreateRoleAssignment() {
    if (!session || selectedEstimateId === null) {
      return;
    }
    const draft = parseRoleAssignmentDraft();
    if ("error" in draft) {
      setRoleAssignmentError(draft.error);
      return;
    }

    const launchedEstimateId = selectedEstimateId;
    const payload: EstimateRoleAssignmentCreate = {
      task_id: draft.taskId,
      role_id: draft.roleId,
      cost_code_id: roleAssignmentCostCodeId ? Number(roleAssignmentCostCodeId) : null,
      quantity: draft.quantity,
      hours: draft.hours,
      comment: roleAssignmentComment.trim() ? roleAssignmentComment.trim() : null,
    };

    setEstimateBusy(true);
    setRoleAssignmentError(null);
    try {
      await createEstimateRoleAssignment(projectId, launchedEstimateId, payload, session, onSessionRefresh);
      if (selectedEstimateIdRef.current === launchedEstimateId) {
        await refreshEstimateRoleAssignments(launchedEstimateId, session);
        closeRoleAssignmentDialog();
      }
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return;
      }
      if (selectedEstimateIdRef.current !== launchedEstimateId) {
        return;
      }
      setRoleAssignmentError(describeRoleAssignmentError(cause, "Impossible d'ajouter la ligne de main d'œuvre."));
    } finally {
      setEstimateBusy(false);
    }
  }

  // E12-10/#292: inline, per-cell update of an existing role assignment's Qté/Heures from the
  // Devis grid (use-estimate-grid-drafts.ts's blur-commit) -- same
  // "PATCH, then refetch the full list" convention as every other role-assignment mutation in
  // this file (refreshEstimateRoleAssignments), rather than approximating the patched row
  // locally. Reports whether the update actually persisted, so the caller's draft is only
  // discarded on confirmed success.
  async function updateRoleAssignmentField(
    id: number,
    payload: { quantity?: number; hours?: number },
  ): Promise<boolean> {
    if (!session || selectedEstimateId === null) {
      return false;
    }
    const launchedEstimateId = selectedEstimateId;
    setEstimateBusy(true);
    setError(null);
    try {
      await updateEstimateRoleAssignment(projectId, launchedEstimateId, id, payload, session, onSessionRefresh);
      if (selectedEstimateIdRef.current === launchedEstimateId) {
        await refreshEstimateRoleAssignments(launchedEstimateId, session);
      }
      return true;
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return false;
      }
      if (selectedEstimateIdRef.current === launchedEstimateId) {
        setError(describeRoleAssignmentError(cause, "Impossible de modifier la ligne de main d'œuvre."));
      }
      return false;
    } finally {
      setEstimateBusy(false);
    }
  }

  // Deletes a role assignment once confirmed via EstimateRoleAssignmentDeleteDialog (page.tsx
  // call site) -- same requestDelete/cancelDelete/remove split as costLinePendingDelete's own
  // non-labor sibling above.
  async function removeRoleAssignment(assignment: EstimateRoleAssignment) {
    if (!session || selectedEstimateId === null) {
      return;
    }
    const launchedEstimateId = selectedEstimateId;
    setEstimateBusy(true);
    setError(null);
    try {
      await deleteEstimateRoleAssignment(projectId, launchedEstimateId, assignment.id, session, onSessionRefresh);
      if (selectedEstimateIdRef.current === launchedEstimateId) {
        await refreshEstimateRoleAssignments(launchedEstimateId, session);
      }
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return;
      }
      if (selectedEstimateIdRef.current !== launchedEstimateId) {
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de supprimer la ligne de main d'œuvre.");
    } finally {
      setEstimateBusy(false);
    }
  }

  // Applies a successful createEstimateTask response: refetches the task-row list, closes the
  // dialog, and triggers the planning refetch above -- but only if the estimate version hasn't
  // since changed (same stale-response guard as every other handler in this file). Extracted out
  // of submitCreateTask purely to keep that function under this file's complexity budget.
  async function applyCreateTaskSuccess(launchedEstimateId: number, tokens: SessionTokens) {
    if (selectedEstimateIdRef.current !== launchedEstimateId) {
      return;
    }
    await refreshEstimateTaskRowsAfterTaskCreation(launchedEstimateId, tokens);
    closeCreateTaskDialog();
    if (selectedPlanningId !== null) {
      await refreshPlanningDetailAfterTaskCreation(selectedPlanningId, tokens);
    }
  }

  // E6-06/#67: creates a task straight from this screen, attaching it to the project's
  // displayed draft planning and snapshotting it into the current (draft) estimate in one
  // backend call. `selectedEstimateIdRef` guard mirrors addCostLine/saveCostLine above: the
  // user could switch estimate version while this request is in flight (nothing currently
  // disables the version selector while busy), and a stale response must never be applied to
  // whatever version is displayed once it resolves.
  async function submitCreateTask() {
    if (!session || selectedEstimateId === null) {
      return;
    }
    const trimmedName = taskDraftName.trim();
    if (!trimmedName) {
      setTaskCreateError("Le nom de la tâche est obligatoire.");
      return;
    }

    const launchedEstimateId = selectedEstimateId;
    const targetParentUid = taskDraftParentUid ? Number(taskDraftParentUid) : undefined;

    setEstimateBusy(true);
    setTaskCreateError(null);
    setTaskCreateRequiresPlanningDraft(false);
    try {
      await createEstimateTask(
        projectId,
        launchedEstimateId,
        { name: trimmedName, is_milestone: taskDraftIsMilestone, target_parent_uid: targetParentUid },
        session,
        onSessionRefresh,
      );
      await applyCreateTaskSuccess(launchedEstimateId, session);
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return;
      }
      if (selectedEstimateIdRef.current !== launchedEstimateId) {
        return;
      }
      if (cause instanceof ApiError && cause.status === 409) {
        if (isEstimateTaskCreateRequiresPlanningDraft(cause)) {
          // cause.message already carries the "reopen the structure" guidance (see
          // describeStructuredDetailCode in lib/backend.ts) -- the dialog additionally offers
          // a direct action button for it via taskCreateRequiresPlanningDraft.
          setTaskCreateRequiresPlanningDraft(true);
          setTaskCreateError(cause.message);
        } else {
          // A different 409 on this endpoint means either the estimate is no longer a draft
          // or the project became read-only while the dialog was open -- both collapse to the
          // backend's generic {"code": "GENERIC_ERROR"} detail, so cause.message alone would
          // only say "Une erreur est survenue...". Distinct, actionable copy instead.
          setTaskCreateError("Ce devis ou le planning affiché ne sont plus modifiables.");
        }
      } else {
        setTaskCreateError(cause instanceof ApiError ? cause.message : "Impossible d'ajouter la tâche.");
      }
    } finally {
      setEstimateBusy(false);
    }
  }

  function openMilestoneDialog(line: EstimateCostLine) {
    setMilestoneLineId(line.id);
    setMilestoneTemplate("fourniture");
    setMilestoneIntermediateCount("0");
    setMilestoneLagMinutes("0");
    setMilestoneError(null);
    setMilestoneRequiresPlanningDraft(false);
    setMilestoneDialogOpen(true);
  }

  function closeMilestoneDialog() {
    setMilestoneDialogOpen(false);
    setMilestoneLineId(null);
    setMilestoneTemplate("fourniture");
    setMilestoneIntermediateCount("0");
    setMilestoneLagMinutes("0");
    setMilestoneError(null);
    setMilestoneRequiresPlanningDraft(false);
  }

  function updateMilestoneTemplate(value: EstimateCostLineMilestonesCreate["template"]) {
    setMilestoneTemplate(value);
    // "fourniture" never takes an intermediate-milestone count (rejected with a 400 if non-zero,
    // see EstimateCostLineMilestonesCreate.yaml) -- reset it here so switching templates back and
    // forth can never silently carry over a stale, now-invalid value into the request.
    if (value === "fourniture") {
      setMilestoneIntermediateCount("0");
    }
  }
  function updateMilestoneIntermediateCount(value: string) {
    setMilestoneIntermediateCount(value);
  }
  function updateMilestoneLagMinutes(value: string) {
    setMilestoneLagMinutes(value);
  }

  // Applies a successful applyEstimateCostLineMilestoneTemplate response: refetches the
  // task-row list (E12-04/#276 -- see refreshEstimateTaskRowsAfterTaskCreation's doc comment for
  // why an exact refetch replaced the former count-bump-by-however-many-milestones-were-created),
  // closes the dialog, and triggers the same planning refetch as applyCreateTaskSuccess above --
  // but only if the estimate version hasn't since changed (same stale-response guard as every
  // other handler in this file).
  async function applyMilestoneTemplateSuccess(launchedEstimateId: number, tokens: SessionTokens) {
    if (selectedEstimateIdRef.current !== launchedEstimateId) {
      return;
    }
    await refreshEstimateTaskRowsAfterTaskCreation(launchedEstimateId, tokens);
    closeMilestoneDialog();
    if (selectedPlanningId !== null) {
      await refreshPlanningDetailAfterTaskCreation(selectedPlanningId, tokens);
    }
  }

  // Validates the two numeric milestone-dialog fields before any network call -- returns the
  // parsed `{lagMinutes, intermediateCount}` pair, or an error message to show instead.
  // Extracted purely to keep submitMilestoneTemplate under this file's complexity budget.
  function parseMilestoneTemplateDraft(): { lagMinutes: number; intermediateCount: number } | { error: string } {
    const lagMinutes = Number(milestoneLagMinutes);
    if (!Number.isFinite(lagMinutes) || lagMinutes < 0) {
      return { error: "Le délai entre jalons doit être un nombre de minutes positif ou nul." };
    }
    const intermediateCount = milestoneTemplate === "sous_traitance" ? Number(milestoneIntermediateCount) : 0;
    if (!Number.isInteger(intermediateCount) || intermediateCount < 0 || intermediateCount > 50) {
      return { error: "Le nombre de jalons intermédiaires doit être un entier compris entre 0 et 50." };
    }
    return { lagMinutes, intermediateCount };
  }

  // Translates a submitMilestoneTemplate failure into `{message, requiresPlanningDraft}` --
  // extracted purely to keep that function under this file's complexity budget. Callers must
  // handle SessionExpiredError/a post-refresh 401 before reaching this (those redirect to
  // /login instead of showing any of this copy).
  //
  // The backend has no code to distinguish its several possible 400s (a labor cost line, a
  // non-zero intermediate count sent with "fourniture", an orphaned task reference, or a generic
  // PlanningTreeMoveError/PlanningLinkError) from one another -- the global exception handler
  // rewrites every plain-string HTTPException.detail to {"code": "GENERIC_ERROR"} (see
  // lib/backend.ts's describeStructuredDetailCode doc comment). The "fourniture" case can never
  // actually happen here since updateMilestoneTemplate always resets the count to 0 when
  // "fourniture" is selected (and parseMilestoneTemplateDraft above validates it client-side
  // regardless), and the orphaned-task-reference/generic-planning-tree-error cases are
  // theoretical edge cases not expected in normal usage (they'd require the cost line's task_id
  // to point outside the project, or a planning-tree invariant violation this endpoint doesn't
  // otherwise trigger) -- so the only client-reachable-in-practice 400 is the labor line: distinct,
  // actionable copy for it below, keyed on the status code alone rather than an inspectable detail
  // code.
  function describeMilestoneTemplateError(cause: unknown): { message: string; requiresPlanningDraft: boolean } {
    if (!(cause instanceof ApiError)) {
      return { message: "Impossible d'appliquer ce gabarit de jalons.", requiresPlanningDraft: false };
    }
    if (cause.status === 409 && isEstimateTaskCreateRequiresPlanningDraft(cause)) {
      // Same structured code/copy as submitCreateTask's own draft-required 409 above.
      return { message: cause.message, requiresPlanningDraft: true };
    }
    if (cause.status === 409) {
      return { message: "Ce devis ou le planning affiché ne sont plus modifiables.", requiresPlanningDraft: false };
    }
    if (cause.status === 404) {
      return { message: "Cette ligne de coût est introuvable dans ce devis.", requiresPlanningDraft: false };
    }
    if (cause.status === 400) {
      return {
        message: "Ce gabarit de jalons ne s'applique qu'aux lignes de coût qui ne sont pas de la main d'œuvre.",
        requiresPlanningDraft: false,
      };
    }
    return { message: cause.message, requiresPlanningDraft: false };
  }

  // E6-07/#68: applies a chained-milestone template to the cost line targeted by
  // openMilestoneDialog. `selectedEstimateIdRef` guard mirrors submitCreateTask above: the user
  // could switch estimate version while this request is in flight (nothing currently disables
  // the version selector while busy), and a stale response must never be applied to whatever
  // version is displayed once it resolves.
  async function submitMilestoneTemplate() {
    if (!session || selectedEstimateId === null || milestoneLineId === null) {
      return;
    }
    const draft = parseMilestoneTemplateDraft();
    if ("error" in draft) {
      setMilestoneError(draft.error);
      return;
    }

    const launchedEstimateId = selectedEstimateId;
    const lineId = milestoneLineId;

    setEstimateBusy(true);
    setMilestoneError(null);
    setMilestoneRequiresPlanningDraft(false);
    try {
      await applyEstimateCostLineMilestoneTemplate(
        projectId,
        launchedEstimateId,
        lineId,
        {
          template: milestoneTemplate,
          intermediate_milestones_count: draft.intermediateCount,
          lag_minutes: Math.round(draft.lagMinutes),
        },
        session,
        onSessionRefresh,
      );
      await applyMilestoneTemplateSuccess(launchedEstimateId, session);
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return;
      }
      if (selectedEstimateIdRef.current !== launchedEstimateId) {
        return;
      }
      const described = describeMilestoneTemplateError(cause);
      setMilestoneRequiresPlanningDraft(described.requiresPlanningDraft);
      setMilestoneError(described.message);
    } finally {
      setEstimateBusy(false);
    }
  }

  // Applies each settled `updateEstimateCostLine` result to `costLines` (success only -- a
  // rejected line is simply left as-is so the user can retry it) and reports how many of each
  // there were, plus whether any failure was a session expiry (which, unlike a per-line error,
  // must interrupt the whole flow the same way every other handler in this file does).
  function applyBulkAssignResults(results: PromiseSettledResult<EstimateCostLine>[]) {
    let successCount = 0;
    let sessionExpired = false;
    for (const result of results) {
      if (result.status === "fulfilled") {
        successCount += 1;
        const updated = result.value;
        setCostLines((previous) => previous.map((item) => (item.id === updated.id ? updated : item)));
        continue;
      }
      const cause = result.reason;
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        sessionExpired = true;
      }
    }
    return { successCount, sessionExpired };
  }

  async function bulkAssignCostCode() {
    if (!session || selectedEstimateId === null || !bulkCostCodeId || selectedCostLineIds.size === 0) {
      return;
    }
    const costCodeId = Number(bulkCostCodeId);
    const lineIds = Array.from(selectedCostLineIds);
    const launchedEstimateId = selectedEstimateId;

    setBulkAssignBusy(true);
    setError(null);
    const results = await Promise.allSettled(
      lineIds.map((lineId) =>
        updateEstimateCostLine(
          projectId,
          launchedEstimateId,
          lineId,
          { cost_code_id: costCodeId },
          session,
          onSessionRefresh,
        ),
      ),
    );
    setBulkAssignBusy(false);
    const { successCount, sessionExpired } = applyBulkAssignResults(results);

    if (sessionExpired) {
      clearSession();
      router.push("/login");
      return;
    }
    // The estimate version may have changed while this batch was in flight (nothing
    // currently disables the version selector while busy) -- a stale batch must never
    // clear whatever selection the user has made since, nor attribute its
    // success/failure banner to a version it doesn't belong to.
    if (selectedEstimateIdRef.current !== launchedEstimateId) {
      return;
    }
    setSelectedCostLineIds(new Set());
    const failureCount = lineIds.length - successCount;
    if (failureCount > 0) {
      setError(
        `${successCount}/${lineIds.length} lignes affectées, ${failureCount} échec${failureCount > 1 ? "s" : ""}.`,
      );
    }
  }

  async function exportExcel() {
    if (!session || selectedEstimateId === null) {
      return;
    }
    setExportBusy(true);
    setError(null);
    try {
      const blob = await exportEstimateExcel(projectId, selectedEstimateId, session, onSessionRefresh);
      const objectUrl = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `devis-${project?.name ?? projectId}-v${selectedEstimate?.version_number ?? ""}.xlsx`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(objectUrl);
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible d'exporter le devis.");
    } finally {
      setExportBusy(false);
    }
  }

  async function createDraftEstimate() {
    if (!session) {
      router.push("/login");
      return;
    }
    setError(null);
    try {
      const estimate = await createProjectEstimate(
        projectId,
        { kind: "initial", currency_code: project?.currency_code ?? "EUR" },
        session,
        onSessionRefresh,
      );
      setEstimates((previous) => [...previous, estimate]);
      setSelectedEstimateId(estimate.id);
      setActiveTab("estimate");
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de créer le devis.");
    }
  }

  async function addCostLine() {
    if (!session || selectedEstimateId === null) {
      return;
    }
    const categoryId = Number(costLineDraft.categoryId);
    const quantity = Number(costLineDraft.quantity);
    const unitCost = Number(costLineDraft.unitCost);
    if (!categoryId || !costLineDraft.label.trim() || !(quantity > 0) || unitCost < 0) {
      setError("Renseigne une catégorie, un libellé, une quantité et un coût unitaire valides.");
      return;
    }

    const launchedEstimateId = selectedEstimateId;

    setEstimateBusy(true);
    setError(null);
    try {
      const line = await createEstimateCostLine(
        projectId,
        launchedEstimateId,
        {
          cost_category_id: categoryId,
          label: costLineDraft.label.trim(),
          quantity,
          unit_cost: unitCost,
          planned_date: plannedDateDraftToPayload(costLineDraft.plannedDate),
          // E12-04/#276: "" (the "Aucune" option) means task_id: null, same empty-string-means-
          // null convention as plannedDateDraftToPayload above.
          task_id: costLineDraft.taskId ? Number(costLineDraft.taskId) : null,
        },
        session,
        onSessionRefresh,
      );
      // The estimate version may have changed while this request was in flight (nothing
      // disables the version selector while busy, same as bulkAssignCostCode/
      // validateEstimate above) -- a stale response must never be applied to whatever
      // version is displayed now.
      if (selectedEstimateIdRef.current === launchedEstimateId) {
        setCostLines((previous) => [...previous, line]);
        setCostLineDraft({ categoryId: "", label: "", quantity: "1", unitCost: "0", plannedDate: "", taskId: "" });
      }
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return;
      }
      if (selectedEstimateIdRef.current === launchedEstimateId) {
        setError(cause instanceof ApiError ? cause.message : "Impossible d'ajouter la ligne de coût.");
      }
    } finally {
      setEstimateBusy(false);
    }
  }

  // E12-10/#292: inline, per-cell update of an existing cost line's Libellé/Qté/Débours/Type
  // from the Devis grid (use-estimate-grid-drafts.ts's blur-commit, or the "Type" `<select>`'s
  // own immediate onChange) -- patches `costLines` in place from the PATCH response itself, same
  // convention as addCostLine's own success path. Reports whether the update actually persisted,
  // so the caller's draft is only discarded on confirmed success.
  async function updateCostLineField(
    lineId: number,
    payload: { label?: string; quantity?: number; unit_cost?: number; cost_category_id?: number },
  ): Promise<boolean> {
    if (!session || selectedEstimateId === null) {
      return false;
    }
    const launchedEstimateId = selectedEstimateId;
    setEstimateBusy(true);
    setError(null);
    try {
      const updated = await updateEstimateCostLine(projectId, launchedEstimateId, lineId, payload, session, onSessionRefresh);
      if (selectedEstimateIdRef.current === launchedEstimateId) {
        setCostLines((previous) => previous.map((item) => (item.id === updated.id ? updated : item)));
      }
      return true;
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return false;
      }
      if (selectedEstimateIdRef.current === launchedEstimateId) {
        setError(cause instanceof ApiError ? cause.message : "Impossible de modifier la ligne de coût.");
      }
      return false;
    } finally {
      setEstimateBusy(false);
    }
  }

  // E12-08/#290 + E12-10/#292: renames a task straight from the Devis grid's Libellé column (a
  // task row only, see use-estimate-grid-drafts.ts's own doc comment) -- the backend resolves
  // `EstimateTaskRow.task_name` live for a draft estimate (see updateTaskName's own doc comment
  // in lib/backend.ts), so a full task-row refetch (mirroring
  // refreshEstimateTaskRowsAfterTaskCreation's own "PATCH, then refetch" shape) is what actually
  // surfaces the new name in this grid, not the raw `TaskRead` response itself (a different shape
  // entirely from `EstimateTaskRow`). Also refreshes `planningDetail` on success, same as
  // applyCreateTaskSuccess/applyMilestoneTemplateSuccess above -- the task's new name must show up
  // immediately in the Planning tab/parent-task selector too, not just this grid.
  async function renameGridTask(taskUid: number, name: string): Promise<boolean> {
    if (!session || selectedEstimateId === null) {
      return false;
    }
    const launchedEstimateId = selectedEstimateId;
    setEstimateBusy(true);
    setError(null);
    try {
      await updateTaskName(projectId, taskUid, name, session, onSessionRefresh);
      if (selectedEstimateIdRef.current === launchedEstimateId) {
        await refreshEstimateTaskRowsAfterTaskCreation(launchedEstimateId, session);
      }
      if (selectedPlanningId !== null) {
        await refreshPlanningDetailAfterTaskCreation(selectedPlanningId, session);
      }
      return true;
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return false;
      }
      if (selectedEstimateIdRef.current === launchedEstimateId) {
        setError(cause instanceof ApiError ? cause.message : "Impossible de renommer la tâche.");
      }
      return false;
    } finally {
      setEstimateBusy(false);
    }
  }

  // E12-07/#289 + E12-10/#292: moves/reorders a selection of the Devis grid's cost-line/role
  // -assignment rows (EstimateGridTreeTable's Indenter/Désindenter/Monter/Descendre toolbar).
  // `expected_revision` is the selected estimate's own `revision` (bumped by every grid-node
  // move, mirroring a planning's own revision-conflict guard) -- resolved here, not accepted as
  // a caller-supplied argument, so the toolbar's command builders (lib/estimate-grid-move.ts)
  // never need to know about it at all. The move endpoint's own response is only the estimate's
  // updated metadata, not the moved rows themselves (see moveEstimateGridNodes's own doc comment
  // in lib/backend.ts) -- a full task-row/cost-line/role-assignment refetch afterward is what
  // actually shows the tree's new row_number/position, never a client-side recomputation of
  // either.
  async function moveGridSelection(command: Omit<EstimateGridNodeMove, "expected_revision">) {
    if (!session || selectedEstimateId === null || !selectedEstimate) {
      return;
    }
    const launchedEstimateId = selectedEstimateId;
    const expectedRevision = selectedEstimate.revision;
    setEstimateBusy(true);
    setError(null);
    try {
      const updatedEstimate = await moveEstimateGridNodes(
        projectId,
        launchedEstimateId,
        { ...command, expected_revision: expectedRevision },
        session,
        onSessionRefresh,
      );
      if (selectedEstimateIdRef.current !== launchedEstimateId) {
        return;
      }
      setEstimates((previous) => previous.map((item) => (item.id === updatedEstimate.id ? updatedEstimate : item)));
      const [freshTaskRows, freshCostLines, freshRoleAssignments] = await Promise.all([
        listEstimateTaskRows(projectId, launchedEstimateId, session, onSessionRefresh),
        listEstimateCostLines(projectId, launchedEstimateId, session, onSessionRefresh),
        listEstimateRoleAssignments(projectId, launchedEstimateId, session, onSessionRefresh),
      ]);
      if (selectedEstimateIdRef.current === launchedEstimateId) {
        setEstimateTaskRows(freshTaskRows);
        setCostLines(() => freshCostLines);
        setEstimateRoleAssignments(freshRoleAssignments);
      }
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return;
      }
      if (selectedEstimateIdRef.current !== launchedEstimateId) {
        return;
      }
      if (getEstimateRevisionConflict(cause)) {
        setError("Ce devis a été modifié entre-temps : recharge-le avant de continuer.");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de déplacer la sélection.");
    } finally {
      setEstimateBusy(false);
    }
  }

  async function removeCostLine(line: EstimateCostLine) {
    if (!session || selectedEstimateId === null) {
      return;
    }

    setEstimateBusy(true);
    setError(null);
    try {
      await deleteEstimateCostLine(projectId, selectedEstimateId, line.id, session, onSessionRefresh);
      setCostLines((previous) => previous.filter((item) => item.id !== line.id));
      // A deleted line can no longer be part of a pending bulk cost-code assignment --
      // otherwise the selection count stays inflated and "Affecter" would send a doomed
      // PATCH for a line that no longer exists (#64/E6-03 review finding).
      setSelectedCostLineIds((previous) => {
        if (!previous.has(line.id)) {
          return previous;
        }
        const next = new Set(previous);
        next.delete(line.id);
        return next;
      });
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de supprimer la ligne de coût.");
    } finally {
      setEstimateBusy(false);
    }
  }

  async function validateEstimate() {
    if (!session || selectedEstimateId === null) {
      return;
    }
    const launchedEstimateId = selectedEstimateId;

    setEstimateBusy(true);
    setError(null);
    try {
      const validated = await validateProjectEstimate(projectId, launchedEstimateId, session, onSessionRefresh);
      setEstimates((previous) => previous.map((item) => (item.id === validated.id ? validated : item)));
      // The estimate version may have changed while this request was in flight (nothing
      // disables the version selector while busy, same as bulkAssignCostCode above) -- a
      // stale response's warning banner must never be attributed to whatever version is
      // displayed now. Purely informative, never blocks the validation above from
      // succeeding -- see dismissValidationWarnings for how the banner gets
      // acknowledged/closed.
      if (selectedEstimateIdRef.current === launchedEstimateId) {
        setValidationWarnings(validated.warnings ?? []);
      }
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return;
      }
      if (selectedEstimateIdRef.current === launchedEstimateId) {
        setError(cause instanceof ApiError ? cause.message : "Impossible de valider le devis.");
      }
    } finally {
      setEstimateBusy(false);
    }
  }

  return {
    costLineDraft,
    costLinePendingDelete,
    estimateValidationOpen,
    setEstimateValidationOpen,
    estimateBusy,
    exportBusy,
    projectCostCodes,
    selectedCostLineIds,
    setSelectedCostLineIds,
    bulkCostCodeId,
    bulkAssignBusy,
    validationWarnings,
    dismissValidationWarnings,
    updateBulkCostCodeId,
    bulkAssignCostCode,
    updateCostLineDraftCategory,
    updateCostLineDraftLabel,
    updateCostLineDraftQuantity,
    updateCostLineDraftUnitCost,
    updateCostLineDraftPlannedDate,
    updateCostLineDraftTaskId,
    requestDeleteCostLine,
    cancelDeleteCostLine,
    openEstimateValidation,
    exportExcel,
    createDraftEstimate,
    addCostLine,
    removeCostLine,
    validateEstimate,
    taskDialogOpen,
    taskDraftName,
    taskDraftIsMilestone,
    taskDraftParentUid,
    taskCreateError,
    taskCreateRequiresPlanningDraft,
    openCreateTaskDialog,
    closeCreateTaskDialog,
    updateTaskDraftName,
    updateTaskDraftIsMilestone,
    updateTaskDraftParentUid,
    submitCreateTask,
    milestoneDialogOpen,
    milestoneLineId,
    milestoneTemplate,
    milestoneIntermediateCount,
    milestoneLagMinutes,
    milestoneError,
    milestoneRequiresPlanningDraft,
    openMilestoneDialog,
    closeMilestoneDialog,
    updateMilestoneTemplate,
    updateMilestoneIntermediateCount,
    updateMilestoneLagMinutes,
    submitMilestoneTemplate,
    roleAssignmentDialogOpen,
    roleAssignmentDept1Id,
    roleAssignmentDept2Id,
    roleAssignmentRoles,
    roleAssignmentRolesLoading,
    roleAssignmentRoleId,
    roleAssignmentTaskId,
    roleAssignmentQuantity,
    roleAssignmentHours,
    roleAssignmentCostCodeId,
    roleAssignmentComment,
    roleAssignmentError,
    openRoleAssignmentDialog,
    closeRoleAssignmentDialog,
    updateRoleAssignmentDept1Id,
    updateRoleAssignmentDept2Id,
    updateRoleAssignmentRoleId,
    updateRoleAssignmentTaskId,
    updateRoleAssignmentQuantity,
    updateRoleAssignmentHours,
    updateRoleAssignmentCostCodeId,
    updateRoleAssignmentComment,
    submitCreateRoleAssignment,
    roleAssignmentPendingDelete,
    requestDeleteRoleAssignment,
    cancelDeleteRoleAssignment,
    removeRoleAssignment,
    updateCostLineField,
    updateRoleAssignmentField,
    renameGridTask,
    moveGridSelection,
  };
}
