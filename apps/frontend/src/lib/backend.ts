import { DEFAULT_API_BASE_URL, type components } from "@waterfall/api-client";

import type { SessionTokens } from "./session";

export type AuthUser = components["schemas"]["UserRead"];
export type AuthUserAdmin = components["schemas"]["UserAdminRead"];
export type ResourceNode = components["schemas"]["ResourceNodeRead"];
export type ResourceRole = components["schemas"]["ResourceRoleRead"];
export type CostType = components["schemas"]["CostTypeRead"];
export type CostCategory = components["schemas"]["CostCategoryRead"];
export type CostRate = components["schemas"]["CostRateRead"];
export type Calendar = components["schemas"]["CalendarRead"];
export type CalendarWeekday = components["schemas"]["CalendarWeekdayRead"];
export type InflationRate = components["schemas"]["InflationRateRead"];
export type RoleCapacity = components["schemas"]["RoleCapacityRead"];
export type Project = components["schemas"]["ProjectRead"];
export type ProjectEstimate = components["schemas"]["ProjectEstimateRead"];
export type EstimateTaskRow = components["schemas"]["EstimateTaskRowRead"];
export type EstimateCostLine = components["schemas"]["EstimateCostLineRead"];
export type EstimateRoleAssignment = components["schemas"]["EstimateRoleAssignmentRead"];
export type ProjectCostCode = components["schemas"]["ProjectCostCodeRead"];
export type Task = components["schemas"]["TaskRead"];
export type PlanningStructureCreate = components["schemas"]["PlanningStructureCreate"];
export type PlanningStructureRead = components["schemas"]["PlanningStructureRead"];
export type PlanningStructureDraftRead = components["schemas"]["PlanningStructureDraftRead"];
export type Planning = components["schemas"]["PlanningRead"];
export type PlanningDetail = components["schemas"]["PlanningDetailRead"];
export type PlanningCreate = components["schemas"]["PlanningCreate"];
export type PlanningTaskMove = components["schemas"]["PlanningTaskMove"];
export type PlanningTaskCreate = components["schemas"]["PlanningTaskCreate"];
export type PlanningTaskDelete = components["schemas"]["PlanningTaskDelete"];
export type PlanningTaskSnapshotWrite = components["schemas"]["PlanningTaskSnapshotWrite"];
export type PlanningLinkSnapshotWrite = components["schemas"]["PlanningLinkSnapshotWrite"];
export type PlanningSnapshotRestore = components["schemas"]["PlanningSnapshotRestore"];
type PlanningTaskDeleteConflictDetail = components["schemas"]["PlanningTaskDeleteConflict"]["detail"];
export type PlanningTaskScheduleUpdate = components["schemas"]["PlanningTaskScheduleUpdate"];
export type TaskLinkWrite = components["schemas"]["TaskLinkWrite"];
export type TaskLinksReplace = components["schemas"]["TaskLinksReplace"];
export type ImportBatch = components["schemas"]["ImportBatchResponse"];
export type ImportBatchStatus = components["schemas"]["ImportBatchStatusResponse"];
export type ImportRunAcceptedResponse = components["schemas"]["ImportRunAcceptedResponse"];
export type ImportDiff = components["schemas"]["ImportDiffResponse"];
export type TokenResponse = components["schemas"]["Token"];

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    // Raw, still-structured `detail` from the response body (e.g. PlanningTaskDeleteConflict's
    // `{code, descendant_uids, task_uids}`), when the backend sent one -- kept alongside the
    // already-formatted `message` so a caller that needs more than a display string (see
    // getPlanningTaskDeleteConflict below) does not have to re-parse the response itself.
    public readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class SessionExpiredError extends Error {
  constructor() {
    super("Session expired");
    this.name = "SessionExpiredError";
  }
}

let refreshInFlight: Promise<TokenResponse> | null = null;

type PydanticValidationErrorItem = { loc?: (string | number)[]; msg?: string; type?: string };

function formatValidationErrors(details: PydanticValidationErrorItem[]): string {
  return details
    .map((item) => {
      const field = item.loc?.at(-1);
      const msg = item.msg ?? "Valeur invalide";
      return field === undefined ? msg : `${field}: ${msg}`;
    })
    .join("; ");
}

type ParsedError = { message: string; detail?: unknown };

// Generic French fallback shown whenever the backend detail code is either the catch-all
// GENERIC_ERROR (see the global FastAPI exception handler, which rewrites any unstructured
// `HTTPException.detail` to `{"code": "GENERIC_ERROR"}`) or a structured code this file does not
// yet translate -- never fall back to the raw response text, which would leak untranslated
// English or raw JSON to the user (see issue #137).
const GENERIC_ERROR_MESSAGE = "Une erreur est survenue. Réessayez ou contactez le support si le problème persiste.";

// Readable French copy for structured detail codes (PlanningTaskDeleteConflict's two codes, see
// that generated schema, plus PLANNING_REVISION_CONFLICT shared by every versioned planning
// mutation, and the two PLANNING_STRUCTURE_REOPEN_* codes raised by the structure reopen
// endpoint); anything else falls back to GENERIC_ERROR_MESSAGE via the caller in parseError.
function describeStructuredDetailCode(code: unknown): string | null {
  if (code === "CASCADE_CONFIRMATION_REQUIRED") {
    return "Cette tâche a des tâches enfants et nécessite une confirmation.";
  }
  if (code === "TASK_REFERENCED") {
    return "Cette tâche est référencée par un devis, une affectation ou une charge.";
  }
  if (code === "PLANNING_REVISION_CONFLICT") {
    return "Ce planning a été modifié entre-temps : recharge-le avant de réessayer.";
  }
  if (code === "PLANNING_STRUCTURE_REOPEN_REQUIRES_VALIDATION") {
    return "Cette structure doit d'abord être validée avant de pouvoir être rouverte.";
  }
  if (code === "PLANNING_STRUCTURE_REOPEN_INTEGRITY_CONFLICT") {
    return "Cette structure ne peut pas être rouverte : son intégrité a été compromise depuis sa validation.";
  }
  if (code === "ESTIMATE_TASK_CREATE_REQUIRES_PLANNING_DRAFT") {
    return "Le planning affiché n'est plus un brouillon : rouvre sa structure depuis l'onglet Planning avant d'ajouter une tâche depuis le devis.";
  }
  if (code === "GENERIC_ERROR") {
    return GENERIC_ERROR_MESSAGE;
  }
  return null;
}

async function parseError(response: Response): Promise<ParsedError> {
  const text = await response.text();
  if (!text) {
    return { message: `HTTP ${response.status}` };
  }

  try {
    const payload = JSON.parse(text) as {
      detail?: string | PydanticValidationErrorItem[] | { code?: string };
      message?: string;
      error?: string;
    };
    if (Array.isArray(payload.detail)) {
      return { message: formatValidationErrors(payload.detail) || text, detail: payload.detail };
    }
    // A structured (object) `detail`, e.g. PlanningTaskDeleteConflict's
    // `{code, descendant_uids, task_uids}`, must never be handed to callers as the `message`
    // string as-is (it would stringify to something like "[object Object]"): translate it to
    // readable copy here, but also keep the raw object on ApiError.detail so a caller that needs
    // the structured fields (see getPlanningTaskDeleteConflict) does not have to re-parse it.
    if (payload.detail && typeof payload.detail === "object") {
      return {
        message: describeStructuredDetailCode(payload.detail.code) ?? GENERIC_ERROR_MESSAGE,
        detail: payload.detail,
      };
    }
    return { message: payload.detail ?? payload.message ?? payload.error ?? text };
  } catch {
    return { message: text };
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${DEFAULT_API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
  });
  if (!response.ok) {
    const parsed = await parseError(response);
    throw new ApiError(response.status, parsed.message, parsed.detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

async function authFetch(
  path: string,
  tokens: SessionTokens,
  init: RequestInit,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<Response> {
  const headers = new Headers(init.headers ?? {});
  headers.set("Authorization", `Bearer ${tokens.accessToken}`);

  const firstResponse = await fetch(`${DEFAULT_API_BASE_URL}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (firstResponse.status !== 401) {
    if (!firstResponse.ok) {
      const parsed = await parseError(firstResponse);
      throw new ApiError(firstResponse.status, parsed.message, parsed.detail);
    }
    return firstResponse;
  }

  let refreshed: TokenResponse;
  try {
    refreshed = await refreshOnce();
  } catch (cause) {
    if (cause instanceof ApiError && (cause.status === 401 || cause.status === 403)) {
      throw new SessionExpiredError();
    }
    throw cause;
  }
  const nextSession: SessionTokens = {
    accessToken: refreshed.access_token,
  };
  onSessionRefresh(nextSession);

  const retryHeaders = new Headers(init.headers ?? {});
  retryHeaders.set("Authorization", `Bearer ${nextSession.accessToken}`);

  const secondResponse = await fetch(`${DEFAULT_API_BASE_URL}${path}`, {
    ...init,
    headers: retryHeaders,
    credentials: "include",
  });

  if (!secondResponse.ok) {
    const parsed = await parseError(secondResponse);
    throw new ApiError(secondResponse.status, parsed.message, parsed.detail);
  }
  return secondResponse;
}

// Inspects an error thrown by deletePlanningTasks for the structured 409 conflict body
// (PlanningTaskDeleteConflict): CASCADE_CONFIRMATION_REQUIRED means the deletion needs the user's
// confirmation to also remove the listed descendants; TASK_REFERENCED means the deletion cannot
// proceed at all (referenced by an estimate/assignment/charge), regardless of confirm_cascade.
// Returns null for anything else (a different status, no structured detail, or an unrelated
// error), so callers can fall back to a generic error message.
export function getPlanningTaskDeleteConflict(cause: unknown): {
  code: "CASCADE_CONFIRMATION_REQUIRED" | "TASK_REFERENCED";
  descendantUids?: number[];
  taskUids?: number[];
} | null {
  if (!(cause instanceof ApiError) || cause.status !== 409) {
    return null;
  }
  const detail = cause.detail as PlanningTaskDeleteConflictDetail | undefined;
  if (!detail || (detail.code !== "CASCADE_CONFIRMATION_REQUIRED" && detail.code !== "TASK_REFERENCED")) {
    return null;
  }
  return {
    code: detail.code,
    descendantUids: detail.descendant_uids,
    taskUids: detail.task_uids,
  };
}

// Inspects an error thrown by any versioned planning mutation (move/create/delete/schedule/
// links/restore) for the structured PLANNING_REVISION_CONFLICT 409 body (E4-01). Returns null
// for anything else, so callers can fall back to a generic error message.
export function getPlanningRevisionConflict(cause: unknown): {
  projectId: number;
  planningId: number;
  expectedRevision: number;
  currentRevision: number;
} | null {
  if (!(cause instanceof ApiError) || cause.status !== 409) {
    return null;
  }
  const detail = cause.detail as
    | {
        code?: string;
        project_id?: number;
        planning_id?: number;
        expected_revision?: number;
        current_revision?: number;
      }
    | undefined;
  if (!detail || detail.code !== "PLANNING_REVISION_CONFLICT") {
    return null;
  }
  return {
    projectId: detail.project_id ?? 0,
    planningId: detail.planning_id ?? 0,
    expectedRevision: detail.expected_revision ?? 0,
    currentRevision: detail.current_revision ?? 0,
  };
}

// E6-11/#175: the structured 400 body `POST .../role-assignments` raises when a labor
// assignment covers a (cost category, year) with no `CostRate`, or a year with no
// `InflationRate`, and the task it's attached to is already dated (start_at/finish_at set).
// `describeStructuredDetailCode` above never learns this code (it has no fixed French sentence:
// the message must list the actual missing combinations/years), so `cause.message` alone would
// only carry the generic fallback -- callers needing the details go through
// getMissingRateCoverage/describeMissingRateCoverage below instead, same precedent as
// getPlanningTaskDeleteConflict/getPlanningRevisionConflict.
export type MissingRateCoverageDetail = components["schemas"]["MissingRateCoverage"]["detail"];

// Basse review finding #4 (E12-06/#278): the `409` branch below isn't dead code, even though
// neither of this file's current callers (submitCreateRoleAssignment/saveRoleAssignment in
// use-estimate-cost-lines.ts) ever actually gets a 409 with this code -- POST .../
// role-assignments (create) only ever raises MISSING_RATE_COVERAGE as a 400, and PATCH .../
// role-assignments/{id} (update) never raises it at all (task_id/role_id, the only fields the
// rate-coverage check depends on, are immutable once created -- its own 409s are the generic
// "estimate no longer a draft" conflict). It's kept because `validate_project_estimate`
// (apps/backend/.../routes/estimates.py) *does* raise this exact structured detail as a 409
// (see its own `responses` docstring: "au moins une (categorie de cout, annee) ... sans
// CostRate/InflationRate (detail.code=MISSING_RATE_COVERAGE)") -- this helper is a small,
// generic, cause-agnostic detector, not tied to one specific caller, so it stays able to
// recognize that shape from any endpoint that might raise it this way, present or future.
export function getMissingRateCoverage(cause: unknown): MissingRateCoverageDetail | null {
  if (!(cause instanceof ApiError) || (cause.status !== 400 && cause.status !== 409)) {
    return null;
  }
  const detail = cause.detail as { code?: string } | undefined;
  if (!detail || detail.code !== "MISSING_RATE_COVERAGE") {
    return null;
  }
  return detail as MissingRateCoverageDetail;
}

// Builds a readable French message listing every missing (cost category, year) hourly-rate
// combination and every missing inflation year from a MissingRateCoverage detail -- rather than
// only the generic "Une erreur est survenue..." fallback describeStructuredDetailCode would
// otherwise produce for this code.
export function describeMissingRateCoverage(detail: MissingRateCoverageDetail): string {
  const parts: string[] = [];
  if (detail.missing_cost_rates.length) {
    const list = detail.missing_cost_rates
      .map((entry) => `${entry.accounting_code} ${entry.category_name} (${entry.year})`)
      .join(", ");
    parts.push(`taux horaire manquant pour ${list}`);
  }
  if (detail.missing_inflation_years.length) {
    parts.push(`taux d'inflation manquant pour ${detail.missing_inflation_years.join(", ")}`);
  }
  const suffix = parts.length ? ` : ${parts.join(" ; ")}.` : ".";
  return `Couverture de taux incomplète pour cette tâche déjà datée${suffix}`;
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const body = new URLSearchParams();
  body.set("username", email);
  body.set("password", password);

  return requestJson<TokenResponse>("/auth/token", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: body.toString(),
  });
}

export async function refresh(): Promise<TokenResponse> {
  return requestJson<TokenResponse>("/auth/refresh", {
    method: "POST",
  });
}

export async function restoreSession(): Promise<SessionTokens> {
  const tokens = await refreshOnce();
  return { accessToken: tokens.access_token };
}

function refreshOnce(): Promise<TokenResponse> {
  if (!refreshInFlight) {
    refreshInFlight = refresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

export async function authRequest<T>(
  path: string,
  tokens: SessionTokens,
  init: RequestInit,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<T> {
  const response = await authFetch(path, tokens, init, onSessionRefresh);
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function authDownload(
  path: string,
  tokens: SessionTokens,
  init: RequestInit,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<Blob> {
  const response = await authFetch(path, tokens, init, onSessionRefresh);
  return await response.blob();
}

export function getMe(tokens: SessionTokens, onSessionRefresh: (next: SessionTokens) => void) {
  return authRequest<AuthUser>("/auth/me", tokens, { method: "GET" }, onSessionRefresh);
}

export async function getUsers(
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
  listParams: ListQueryParams = {},
): Promise<ListPage<AuthUserAdmin>> {
  const query = buildListQuery(listParams);
  const page = await authRequest<components["schemas"]["UserAdminListRead"]>(
    `/auth/users${query}`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return { items: page.items, total: page.total };
}

export function createUser(
  email: string,
  password: string,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<AuthUserAdmin>(
    "/auth/users",
    tokens,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, password }),
    },
    onSessionRefresh,
  );
}

export function deleteUser(
  userId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<void>(
    `/auth/users/${userId}`,
    tokens,
    { method: "DELETE" },
    onSessionRefresh,
  );
}

export async function getResourceNodes(
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
  includeInactive = false,
): Promise<ResourceNode[]> {
  const query = includeInactive ? "?include_inactive=true" : "";
  const page = await authRequest<components["schemas"]["ResourceNodeListRead"]>(
    `/resources/nodes${query}`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return page.items;
}

export function createResourceNode(
  payload: { code: string; name: string; parent_id?: number | null },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<ResourceNode>(
    "/resources/nodes",
    tokens,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export function updateResourceNode(
  nodeId: number,
  payload: { code?: string; name?: string; parent_id?: number | null; is_active?: boolean },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<ResourceNode>(
    `/resources/nodes/${nodeId}`,
    tokens,
    { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export function deleteResourceNode(
  nodeId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<void>(
    `/resources/nodes/${nodeId}`,
    tokens,
    { method: "DELETE" },
    onSessionRefresh,
  );
}

// `listParams` mirrors `getCostTypes`'s own extension for EPIC E8's DataTable
// migrations (#123 onward): absent (the default), the backend's "no limit -> tout"
// rule (see `ListParams`/`list_params` on the backend) means every existing caller
// -- the `roles` reference list feeding RolesPanel/CapacityTable's per-role drafts/
// RoleCalendarsTable -- keeps getting the complete, unfiltered set exactly as
// before. A caller that does pass `listParams` (the capacity table's own paginated
// view) gets the server-driven page instead.
export async function getResourceRoles(
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
  nodeId?: number,
  includeDescendants = false,
  listParams: ListQueryParams = {},
  includeInactive = false,
): Promise<ListPage<ResourceRole>> {
  const extra: Record<string, string> = {};
  if (nodeId) {
    extra.node_id = String(nodeId);
    extra.include_descendants = String(includeDescendants);
  }
  if (includeInactive) {
    extra.include_inactive = "true";
  }
  const query = buildListQuery(listParams, Object.keys(extra).length > 0 ? extra : undefined);
  const page = await authRequest<components["schemas"]["ResourceRoleListRead"]>(
    `/resources/roles${query}`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return { items: page.items, total: page.total };
}

export function createResourceRole(
  payload: { name: string; node_id: number; cost_category_id: number; calendar_id?: number | null },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<ResourceRole>(
    "/resources/roles",
    tokens,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export function updateResourceRole(
  roleId: number,
  payload: { name?: string; node_id?: number; cost_category_id?: number; calendar_id?: number | null; is_active?: boolean },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<ResourceRole>(
    `/resources/roles/${roleId}`,
    tokens,
    { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

// Generic envelope for a server-paginated list, and the query parameters a caller
// supplies to request one page of it. `limit`/`offset` are known to the caller
// already (it's what it asked for) and don't round-trip back through this type --
// only `items`/`total` come from the response. Introduced for EPIC E8's DataTable
// migrations (#120 onward): reuse this rather than a bespoke `{items, total}` shape
// per endpoint.
export interface ListPage<T> {
  items: T[];
  total: number;
}

// `offset` without `limit` mirrors the backend's own rule that such a request is
// under-specified and rejected with 400 (see PaginationMeta.yaml): typing them as a
// single all-or-nothing pair, rather than two independent optionals, turns a caller
// passing one without the other into a compile error instead of a silently dropped
// `offset` (buildListQuery would otherwise just omit both params rather than send an
// invalid request, quietly defaulting to page one instead of surfacing the mistake).
export type ListQueryParams = ({ limit?: undefined; offset?: undefined } | { limit: number; offset: number }) & {
  sort?: string | null;
  q?: string;
};

// Builds a query string for a paginated list endpoint. `offset` is only ever sent
// alongside `limit` (never alone), matching the backend's rule that an `offset`
// without `limit` is rejected as ambiguous.
function buildListQuery(params: ListQueryParams, extra?: Record<string, string>): string {
  const searchParams = new URLSearchParams(extra);
  if (params.limit !== undefined) {
    searchParams.set("limit", String(params.limit));
    searchParams.set("offset", String(params.offset ?? 0));
  }
  if (params.sort) {
    searchParams.set("sort", params.sort);
  }
  if (params.q) {
    searchParams.set("q", params.q);
  }
  const queryString = searchParams.toString();
  return queryString ? `?${queryString}` : "";
}

// `listParams` defaults to `{}` (no `limit`/`offset`/`sort`/`q`), which
// `buildListQuery` turns into an empty query string -- the backend then returns the
// full, unpaginated list. This preserves the pre-E8 behavior for every existing
// caller (e.g. the role-calendar assignment dropdown, which needs the complete set
// of calendars, not one server-sorted/paginated page) while letting the calendars
// table opt into pagination/sort/search by passing `listParams` explicitly, exactly
// like `getCostTypes`.
export async function getCalendars(
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
  includeInactive = false,
  listParams: ListQueryParams = {},
): Promise<ListPage<Calendar>> {
  const query = buildListQuery(listParams, includeInactive ? { include_inactive: "true" } : undefined);
  const page = await authRequest<components["schemas"]["CalendarListRead"]>(
    `/resources/calendars${query}`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return { items: page.items, total: page.total };
}

// E12-10/#292: fetches a single calendar (with its `weekdays`, `CalendarRead` embeds them
// inline -- no separate weekday-listing endpoint) so the "Ajouter une ligne MO" dialog can
// prefill "Heures" from the selected role's own calendar once `getResourceRoles` has resolved
// its `calendar_id`. Deliberately a single-resource GET, not folded into `getCalendars` above:
// this is fetched on demand per role selection, not as part of the calendar referential list.
export function getCalendar(
  calendarId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<Calendar> {
  return authRequest<Calendar>(
    `/resources/calendars/${calendarId}`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
}

export function createCalendar(
  payload: { code: string; name: string; weeks_per_year: number; weekdays: { day_type: number; hours_per_day: string }[] },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Calendar>(
    "/resources/calendars",
    tokens,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export function updateCalendar(
  calendarId: number,
  payload: {
    code?: string;
    name?: string;
    weeks_per_year?: number;
    is_active?: boolean;
    is_default?: boolean;
    weekdays?: { day_type: number; hours_per_day: string }[];
  },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Calendar>(
    `/resources/calendars/${calendarId}`,
    tokens,
    { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export function deleteCalendar(
  calendarId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<void>(
    `/resources/calendars/${calendarId}`,
    tokens,
    { method: "DELETE" },
    onSessionRefresh,
  );
}

export async function getCostTypes(
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
  includeInactive = false,
  listParams: ListQueryParams = {},
): Promise<ListPage<CostType>> {
  const query = buildListQuery(listParams, includeInactive ? { include_inactive: "true" } : undefined);
  const page = await authRequest<components["schemas"]["CostTypeListRead"]>(
    `/resources/cost-types${query}`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return { items: page.items, total: page.total };
}

export async function getCostCategories(
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
  includeInactive = false,
  listParams: ListQueryParams = {},
): Promise<ListPage<CostCategory>> {
  const query = buildListQuery(listParams, includeInactive ? { include_inactive: "true" } : undefined);
  const page = await authRequest<components["schemas"]["CostCategoryListRead"]>(
    `/resources/categories${query}`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return { items: page.items, total: page.total };
}

export function createCostType(
  payload: { code: string; name: string; kind: CostType["kind"] },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<CostType>(
    "/resources/cost-types",
    tokens,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export function updateCostType(
  costTypeId: number,
  payload: { name?: string; is_active?: boolean },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<CostType>(
    `/resources/cost-types/${costTypeId}`,
    tokens,
    { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export function createCostCategory(
  payload: {
    cost_type_id: number;
    accounting_code: string;
    category_code?: string | null;
    name: string;
  },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<CostCategory>(
    "/resources/categories",
    tokens,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export function updateCostCategory(
  categoryId: number,
  payload: {
    cost_type_id?: number;
    accounting_code?: string;
    category_code?: string | null;
    name?: string;
    is_active?: boolean;
  },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<CostCategory>(
    `/resources/categories/${categoryId}`,
    tokens,
    { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export async function getCostRates(
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<CostRate[]> {
  const page = await authRequest<components["schemas"]["CostRateListRead"]>(
    "/resources/rates",
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return page.items;
}

export function createCostRate(
  payload: { cost_category_id: number; year: number; hourly_rate: string; currency_code: string },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<CostRate>(
    "/resources/rates",
    tokens,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export function updateCostRate(
  rateId: number,
  payload: { hourly_rate?: string; currency_code?: string; year?: number },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<CostRate>(
    `/resources/rates/${rateId}`,
    tokens,
    { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export async function getInflationRates(
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<InflationRate[]> {
  const page = await authRequest<components["schemas"]["InflationRateListRead"]>(
    "/resources/inflation",
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return page.items;
}

export function setInflationRate(
  year: number,
  coefficient: string,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<InflationRate>(
    `/resources/inflation/${year}`,
    tokens,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ coefficient }) },
    onSessionRefresh,
  );
}

export async function getRoleCapacities(
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<RoleCapacity[]> {
  const page = await authRequest<components["schemas"]["RoleCapacityListRead"]>(
    "/resources/capacities",
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return page.items;
}

export function createRoleCapacity(
  payload: {
    role_id: number;
    person_count: string;
    available_hours: string;
  },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<RoleCapacity>(
    "/resources/capacities",
    tokens,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export function updateRoleCapacity(
  capacityId: number,
  payload: { person_count?: string; available_hours?: string },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<RoleCapacity>(
    `/resources/capacities/${capacityId}`,
    tokens,
    { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export function setUserStatus(
  userId: number,
  isActive: boolean,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<AuthUserAdmin>(
    `/auth/users/${userId}/status`,
    tokens,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ is_active: isActive }),
    },
    onSessionRefresh,
  );
}

export function setUserRole(
  userId: number,
  isAdmin: boolean,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<AuthUserAdmin>(
    `/auth/users/${userId}/role`,
    tokens,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ is_admin: isAdmin }),
    },
    onSessionRefresh,
  );
}

// `listParams` mirrors `getCostTypes`'s own EPIC E8 DataTable extension (#128, the
// last of the 9 migrations): `sort` is constrained server-side to `name`/`status`/
// `id` (and their `-` descending forms) only -- see `openapi/spec/paths/
// projects.yaml`'s `sort` enum -- so `projects-table.tsx` only ever sends one of
// those, never e.g. "code" (that column has no server-sortable equivalent).
export async function getProjects(
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
  includeArchived = false,
  listParams: ListQueryParams = {},
): Promise<ListPage<Project>> {
  const query = buildListQuery(listParams, includeArchived ? { include_archived: "true" } : undefined);
  const page = await authRequest<components["schemas"]["ProjectListRead"]>(
    `/projects${query}`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return { items: page.items, total: page.total };
}

export function getProject(
  projectId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Project>(
    `/projects/${projectId}`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
}

export async function listProjectEstimates(
  projectId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<ProjectEstimate[]> {
  const page = await authRequest<components["schemas"]["ProjectEstimateListRead"]>(
    `/projects/${projectId}/estimates`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return page.items;
}

export function createProjectEstimate(
  projectId: number,
  payload: { kind: ProjectEstimate["kind"]; currency_code: string; note?: string | null },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<ProjectEstimate>(
    `/projects/${projectId}/estimates`,
    tokens,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

export async function listEstimateTaskRows(
  projectId: number,
  estimateId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<EstimateTaskRow[]> {
  const page = await authRequest<components["schemas"]["EstimateTaskRowListRead"]>(
    `/projects/${projectId}/estimates/${estimateId}/task-rows`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return page.items;
}

export type EstimateTaskCreate = components["schemas"]["EstimateTaskCreate"];

// Adds a task directly from the Devis screen (E6-06/#67): creates a snapshot task in the
// project's *displayed* planning (which must be a draft) and a matching EstimateTaskRow in
// this estimate (which must also be a draft) in one backend transaction. `target_parent_uid`/
// `insert_after_uid`, when set, must be uids of the displayed planning's own tasks -- never an
// EstimateTaskRow id/task_id, which the read model doesn't expose a uid for.
export function createEstimateTask(
  projectId: number,
  estimateId: number,
  payload: EstimateTaskCreate,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<EstimateTaskRow>(
    `/projects/${projectId}/estimates/${estimateId}/tasks`,
    tokens,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

// Inspects an error thrown by createEstimateTask for the structured 409 raised when the
// project's displayed planning is not a draft (most commonly because it was validated and no
// draft has been reopened since). Distinct from reading cause.message (already a full French
// sentence via describeStructuredDetailCode above) because the caller needs to know this
// specific case to also offer a "reopen the structure" action, not just display text.
export function isEstimateTaskCreateRequiresPlanningDraft(cause: unknown): boolean {
  if (!(cause instanceof ApiError) || cause.status !== 409) {
    return false;
  }
  const detail = cause.detail as { code?: string } | undefined;
  return detail?.code === "ESTIMATE_TASK_CREATE_REQUIRES_PLANNING_DRAFT";
}

export async function listEstimateCostLines(
  projectId: number,
  estimateId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<EstimateCostLine[]> {
  const page = await authRequest<components["schemas"]["EstimateCostLineListRead"]>(
    `/projects/${projectId}/estimates/${estimateId}/cost-lines`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return page.items;
}

export type EstimateCostLineCreate = components["schemas"]["EstimateCostLineCreate"];
export type EstimateCostLineUpdate = components["schemas"]["EstimateCostLineUpdate"];

export function createEstimateCostLine(
  projectId: number,
  estimateId: number,
  payload: EstimateCostLineCreate,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<EstimateCostLine>(
    `/projects/${projectId}/estimates/${estimateId}/cost-lines`,
    tokens,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

export function updateEstimateCostLine(
  projectId: number,
  estimateId: number,
  lineId: number,
  payload: EstimateCostLineUpdate,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<EstimateCostLine>(
    `/projects/${projectId}/estimates/${estimateId}/cost-lines/${lineId}`,
    tokens,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

export function deleteEstimateCostLine(
  projectId: number,
  estimateId: number,
  lineId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<void>(
    `/projects/${projectId}/estimates/${estimateId}/cost-lines/${lineId}`,
    tokens,
    { method: "DELETE" },
    onSessionRefresh,
  );
}

// E12-06/#278: CRUD for EstimateRoleAssignment ("MO"/labor) rows -- same shape as the
// EstimateCostLine wrappers just above. `EstimateRoleAssignmentCreate`/`Update` distinguish
// themselves from EstimateCostLine's own: `task_id`/`role_id` are only ever set at creation
// (immutable afterward, see EstimateRoleAssignmentUpdate's own doc comment in the OpenAPI spec),
// so `EstimateRoleAssignmentUpdate` doesn't carry either field at all.
export type EstimateRoleAssignmentCreate = components["schemas"]["EstimateRoleAssignmentCreate"];
export type EstimateRoleAssignmentUpdate = components["schemas"]["EstimateRoleAssignmentUpdate"];

export async function listEstimateRoleAssignments(
  projectId: number,
  estimateId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<EstimateRoleAssignment[]> {
  const page = await authRequest<components["schemas"]["EstimateRoleAssignmentListRead"]>(
    `/projects/${projectId}/estimates/${estimateId}/role-assignments`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return page.items;
}

export function createEstimateRoleAssignment(
  projectId: number,
  estimateId: number,
  payload: EstimateRoleAssignmentCreate,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<EstimateRoleAssignment>(
    `/projects/${projectId}/estimates/${estimateId}/role-assignments`,
    tokens,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

export function updateEstimateRoleAssignment(
  projectId: number,
  estimateId: number,
  assignmentId: number,
  payload: EstimateRoleAssignmentUpdate,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<EstimateRoleAssignment>(
    `/projects/${projectId}/estimates/${estimateId}/role-assignments/${assignmentId}`,
    tokens,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

export function deleteEstimateRoleAssignment(
  projectId: number,
  estimateId: number,
  assignmentId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<void>(
    `/projects/${projectId}/estimates/${estimateId}/role-assignments/${assignmentId}`,
    tokens,
    { method: "DELETE" },
    onSessionRefresh,
  );
}

export type EstimateCostLineMilestonesCreate = components["schemas"]["EstimateCostLineMilestonesCreate"];

// Applies a chained-milestone template to a non-labor cost line (E6-07/#68): creates 2
// ("fourniture") or `2 + intermediate_milestones_count` ("sous_traitance") milestone tasks in the
// project's *displayed* draft planning -- same snapshot/MsTask-twin/EstimateTaskRow wiring as
// createEstimateTask above, one call for the whole chain -- then chains them pairwise with
// Finish-to-Start links all carrying `payload.lag_minutes`. Rejects a labor cost line, a
// non-draft estimate, or a non-draft displayed planning
// (ESTIMATE_TASK_CREATE_REQUIRES_PLANNING_DRAFT, the exact same code createEstimateTask raises --
// see isEstimateTaskCreateRequiresPlanningDraft above, reusable as-is by this endpoint's callers
// too). Returns the created rows directly (not the envelope) since no caller here ever paginates
// this fixed-size, single-shot result.
export async function applyEstimateCostLineMilestoneTemplate(
  projectId: number,
  estimateId: number,
  lineId: number,
  payload: EstimateCostLineMilestonesCreate,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<EstimateTaskRow[]> {
  const page = await authRequest<components["schemas"]["EstimateTaskRowListRead"]>(
    `/projects/${projectId}/estimates/${estimateId}/cost-lines/${lineId}/milestones`,
    tokens,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
  return page.items;
}

// #65 (E6-04): `validate` returns `warnings` (unassigned real tasks) on top of the usual
// `ProjectEstimateRead` fields -- distinct from `ProjectEstimate` since no other estimate
// endpoint computes/returns this field.
export type EstimateValidationWarning = components["schemas"]["EstimateValidationWarning"];
export type EstimateValidationResult = components["schemas"]["EstimateValidationRead"];

export function validateProjectEstimate(
  projectId: number,
  estimateId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<EstimateValidationResult>(
    `/projects/${projectId}/estimates/${estimateId}/validate`,
    tokens,
    { method: "POST" },
    onSessionRefresh,
  );
}

// E12-07/#289: moves/reorders a selection of a draft devis grid's cost-line/role-assignment
// nodes (E12-10/#292's tree table toolbar) -- mirrors movePlanningTasks. Unlike that endpoint,
// the response here is only the estimate's own metadata (`ProjectEstimateRead`, revision
// incremented) -- not the moved rows themselves -- so a caller must follow a successful move
// with a fresh `listEstimateCostLines`/`listEstimateRoleAssignments`/`listEstimateTaskRows` to
// see the tree's new `row_number`/`position`/`parent_uid` (see this issue's own review note:
// never recompute those client-side after a move).
export type EstimateGridNodeMove = components["schemas"]["EstimateGridNodeMove"];

export function moveEstimateGridNodes(
  projectId: number,
  estimateId: number,
  payload: EstimateGridNodeMove,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<ProjectEstimate>(
    `/projects/${projectId}/estimates/${estimateId}/grid-nodes/move`,
    tokens,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

// Inspects an error thrown by moveEstimateGridNodes for the structured ESTIMATE_REVISION_CONFLICT
// 409 body -- mirrors getPlanningRevisionConflict above, one level up (an estimate's own
// `revision`, not a planning's).
export function getEstimateRevisionConflict(cause: unknown): {
  projectId: number;
  estimateId: number;
  expectedRevision: number;
  currentRevision: number;
} | null {
  if (!(cause instanceof ApiError) || cause.status !== 409) {
    return null;
  }
  const detail = cause.detail as
    | {
        code?: string;
        project_id?: number;
        estimate_id?: number;
        expected_revision?: number;
        current_revision?: number;
      }
    | undefined;
  if (!detail || detail.code !== "ESTIMATE_REVISION_CONFLICT") {
    return null;
  }
  return {
    projectId: detail.project_id ?? 0,
    estimateId: detail.estimate_id ?? 0,
    expectedRevision: detail.expected_revision ?? 0,
    currentRevision: detail.current_revision ?? 0,
  };
}

export async function getProjectCostCodes(
  projectId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<ProjectCostCode[]> {
  const page = await authRequest<components["schemas"]["ProjectCostCodeListRead"]>(
    `/projects/${projectId}/cost-codes`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return page.items;
}

export type EstimateAggregates = components["schemas"]["EstimateAggregatesRead"];

export function getEstimateAggregates(
  projectId: number,
  estimateId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<EstimateAggregates>(
    `/projects/${projectId}/estimates/${estimateId}/aggregates`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
}

export function exportEstimateExcel(
  projectId: number,
  estimateId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authDownload(
    `/projects/${projectId}/estimates/${estimateId}/export.xlsx`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
}

export type ProjectCreateInput = components["schemas"]["ProjectCreate"];
export type ProjectUpdateInput = components["schemas"]["ProjectUpdate"];
export type ProjectSetupWarningCode = components["schemas"]["ProjectSetupWarningCode"];
export type ProjectSetupWarning = components["schemas"]["ProjectSetupWarning"];
export type ProjectSetupWarningsRead = components["schemas"]["ProjectSetupWarningsRead"];

// French messages for each `ProjectSetupWarning.code`, naming the /resources tab where
// the missing global prerequisite can be fixed (#109). `ProjectSetupWarning.message`
// itself is an English diagnostic string never meant for direct display (see the
// schema's own doc comment) -- callers must always go through this mapping instead of
// showing it, same principle as `describeStructuredDetailCode` above.
const projectSetupWarningMessages: Record<ProjectSetupWarningCode, string> = {
  no_default_calendar:
    "Aucun calendrier par défaut actif n'est défini. Définissez-en un dans l'onglet Ressources de la page Paramètres (/resources).",
  default_calendar_has_no_working_day:
    "Le calendrier par défaut n'a aucun jour travaillé. Ajoutez au moins un jour travaillé dans l'onglet Ressources de la page Paramètres (/resources).",
  no_active_cost_category:
    "Aucune catégorie de coût active n'est définie. Activez-en une dans l'onglet Coûts de la page Paramètres (/resources).",
  no_active_resource_role:
    "Aucun rôle actif n'est défini. Activez-en un dans l'onglet Ressources de la page Paramètres (/resources).",
};

// Falls back to a generic message for a code added server-side before this mapping is
// updated, rather than crashing or rendering nothing.
export function describeProjectSetupWarningCode(code: string): string {
  return (
    projectSetupWarningMessages[code as ProjectSetupWarningCode] ??
    "Le paramétrage global comporte un point à vérifier avant de créer un projet. Consultez la page Paramètres (/resources)."
  );
}

export function createProject(
  payload: ProjectCreateInput,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Project>(
    "/projects",
    tokens,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

export function updateProject(
  projectId: number,
  payload: ProjectUpdateInput,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Project>(
    `/projects/${projectId}`,
    tokens,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

export function deleteProject(
  projectId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<void>(
    `/projects/${projectId}`,
    tokens,
    {
      method: "DELETE",
    },
    onSessionRefresh,
  );
}

export function getProjectSetupWarnings(
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<ProjectSetupWarningsRead>(
    "/projects/setup-warnings",
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
}

export function createImportBatch(
  projectId: number,
  sourceName: string,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<ImportBatch>(
    "/imports/v1/batches",
    tokens,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ projectId, importMode: "standard", sourceName }),
    },
    onSessionRefresh,
  );
}

export function uploadImportSourceXml(
  batchId: number,
  file: File,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  const form = new FormData();
  form.append("file", file, file.name);
  return authRequest<ImportBatch>(
    `/imports/v1/batches/${batchId}/xml`,
    tokens,
    {
      method: "POST",
      body: form,
    },
    onSessionRefresh,
  );
}

export function runImportBatch(
  batchId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
  dryRun = false,
  confirm = false,
) {
  return authRequest<ImportRunAcceptedResponse>(
    `/imports/v1/batches/${batchId}/run`,
    tokens,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ dryRun, confirm }),
    },
    onSessionRefresh,
  );
}

export function getImportBatchDiff(
  batchId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<ImportDiff>(
    `/imports/v1/batches/${batchId}/diff`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
}

export function getImportBatchStatus(
  batchId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<ImportBatchStatus>(
    `/imports/v1/batches/${batchId}`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
}

export async function getProjectTasks(
  projectId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<Task[]> {
  const page = await authRequest<components["schemas"]["TaskListRead"]>(
    `/projects/${projectId}/tasks`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return page.items;
}

export function createPlanningStructure(
  projectId: number,
  payload: PlanningStructureCreate,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<PlanningStructureRead>(
    `/projects/${projectId}/planning-structure`,
    tokens,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

export function savePlanningStructureDraft(
  projectId: number,
  payload: PlanningStructureCreate,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<PlanningStructureDraftRead>(
    `/projects/${projectId}/planning-structure/draft`,
    tokens,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

export async function getPlanningStructureDraft(
  projectId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<PlanningStructureDraftRead | null> {
  try {
    return await authRequest<PlanningStructureDraftRead>(
      `/projects/${projectId}/planning-structure/draft`,
      tokens,
      { method: "GET" },
      onSessionRefresh,
    );
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) {
      return null;
    }
    throw cause;
  }
}

export async function listPlannings(
  projectId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<Planning[]> {
  const page = await authRequest<components["schemas"]["PlanningListRead"]>(
    `/projects/${projectId}/plannings`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
  return page.items;
}

export function getPlanning(
  projectId: number,
  planningId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return getCompletePlanning(projectId, planningId, tokens, onSessionRefresh);
}

// Creates a brand new planning version, optionally cloning `source_planning_id`'s tasks/links
// into a fresh draft (see #143: this is what lets the UI offer an explicit "new version from a
// validated planning" action, distinct from the planning-structure wizard).
export function createPlanning(
  projectId: number,
  payload: PlanningCreate,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<PlanningDetail>(
    `/projects/${projectId}/plannings`,
    tokens,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

const PLANNING_PAGE_SIZE = 200;

async function getCompletePlanning(
  projectId: number,
  planningId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  let offset = 0;
  let completePlanning: PlanningDetail | null = null;

  while (true) {
    const page = await authRequest<PlanningDetail>(
      `/projects/${projectId}/plannings/${planningId}?limit=${PLANNING_PAGE_SIZE}&offset=${offset}`,
      tokens,
      { method: "GET" },
      onSessionRefresh,
    );
    if (!completePlanning) {
      completePlanning = page;
    } else {
      completePlanning = Object.assign({}, completePlanning, {
        tasks: [...completePlanning.tasks, ...page.tasks],
        links: [...completePlanning.links, ...page.links],
      });
    }
    if (page.tasks.length < PLANNING_PAGE_SIZE) {
      return completePlanning;
    }
    offset += PLANNING_PAGE_SIZE;
  }
}

export function validatePlanning(
  projectId: number,
  planningId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Planning>(
    `/projects/${projectId}/plannings/${planningId}/validate`,
    tokens,
    { method: "POST" },
    onSessionRefresh,
  );
}

export function movePlanningTasks(
  projectId: number,
  planningId: number,
  payload: PlanningTaskMove,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<PlanningDetail>(
    `/projects/${projectId}/plannings/${planningId}/tasks/move`,
    tokens,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

export function createPlanningTask(
  projectId: number,
  planningId: number,
  payload: PlanningTaskCreate,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<PlanningDetail>(
    `/projects/${projectId}/plannings/${planningId}/tasks`,
    tokens,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

export function deletePlanningTasks(
  projectId: number,
  planningId: number,
  payload: PlanningTaskDelete,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<PlanningDetail>(
    `/projects/${projectId}/plannings/${planningId}/tasks/delete`,
    tokens,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

export function updatePlanningTaskSchedule(
  projectId: number,
  planningId: number,
  taskUid: number,
  payload: PlanningTaskScheduleUpdate,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<PlanningDetail>(
    `/projects/${projectId}/plannings/${planningId}/tasks/${taskUid}`,
    tokens,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

export function replaceTaskPredecessorLinks(
  projectId: number,
  planningId: number,
  taskUid: number,
  payload: TaskLinksReplace,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<PlanningDetail>(
    `/projects/${projectId}/plannings/${planningId}/tasks/${taskUid}/links`,
    tokens,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

// Drives undo/redo (E4-01): replaces every task/link of a draft planning with an exact
// prior snapshot the caller already received from a previous response.
export function restorePlanningSnapshot(
  projectId: number,
  planningId: number,
  payload: PlanningSnapshotRestore,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<PlanningDetail>(
    `/projects/${projectId}/plannings/${planningId}/tasks/restore`,
    tokens,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    onSessionRefresh,
  );
}

export function setPlanningReference(
  projectId: number,
  planningId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Project>(
    `/projects/${projectId}/plannings/${planningId}/reference`,
    tokens,
    { method: "POST" },
    onSessionRefresh,
  );
}

export function setDisplayedPlanning(
  projectId: number,
  planningId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Project>(
    `/projects/${projectId}/plannings/${planningId}/display`,
    tokens,
    { method: "POST" },
    onSessionRefresh,
  );
}

export function reopenPlanningStructure(
  projectId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Project>(
    `/projects/${projectId}/planning-structure/reopen`,
    tokens,
    { method: "POST" },
    onSessionRefresh,
  );
}

export function skipPlanningStructure(
  projectId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Project>(
    `/projects/${projectId}/planning-structure/skip`,
    tokens,
    { method: "POST" },
    onSessionRefresh,
  );
}

export function updateTaskDescription(
  projectId: number,
  taskUid: number,
  description: string | null,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Task>(
    `/projects/${projectId}/tasks/${taskUid}`,
    tokens,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ description }),
    },
    onSessionRefresh,
  );
}

// E12-08/#290: renames a task straight from a Devis grid row (E12-10/#292) -- the same
// `PATCH .../tasks/{taskUid}` endpoint as updateTaskDescription just above, generalized (the
// backend's own `TaskUpdate` schema now carries an optional `name` alongside `description`), but
// kept as its own function rather than a shared `{description, name}` signature: every existing
// caller of updateTaskDescription only ever sends `description`, and a single combined function
// would force those call sites to also pass a meaningless `name: undefined`.
export function updateTaskName(
  projectId: number,
  taskUid: number,
  name: string,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Task>(
    `/projects/${projectId}/tasks/${taskUid}`,
    tokens,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ name }),
    },
    onSessionRefresh,
  );
}

export function exportProjectXml(
  projectId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authDownload(`/projects/${projectId}/export.xml`, tokens, { method: "GET" }, onSessionRefresh);
}
