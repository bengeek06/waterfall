import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  applyEstimateCostLineMilestoneTemplate,
  createEstimateRoleAssignment,
  createEstimateTask,
  deleteEstimateRoleAssignment,
  deletePlanningTasks,
  describeMissingRateCoverage,
  getCalendars,
  getCostTypes,
  getMissingRateCoverage,
  getPlanning,
  getPlanningTaskDeleteConflict,
  getProjects,
  getResourceNodes,
  getResourceRoles,
  getUsers,
  isEstimateTaskCreateRequiresPlanningDraft,
  listEstimateRoleAssignments,
  movePlanningTasks,
  updateEstimateRoleAssignment,
  updateResourceRole,
} from "./backend";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("getCostTypes query building", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends no query string at all when called with no listParams, for the unpaginated reference-list case", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await getCostTypes({ accessToken: "token" }, vi.fn());

    expect(String(fetchMock.mock.calls[0][0])).not.toContain("?");
  });

  it("sends limit, offset, sort, and q together, plus include_inactive as its own flag", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await getCostTypes({ accessToken: "token" }, vi.fn(), true, {
      limit: 20,
      offset: 40,
      sort: "-name",
      q: "abc",
    });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("include_inactive=true");
    expect(url).toContain("limit=20");
    expect(url).toContain("offset=40");
    expect(url).toContain("sort=-name");
    expect(url).toContain("q=abc");
  });

  it("omits sort and q when absent, rather than sending them empty", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await getCostTypes({ accessToken: "token" }, vi.fn(), false, { limit: 5, offset: 0 });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("limit=5");
    expect(url).toContain("offset=0");
    expect(url).not.toContain("sort=");
    expect(url).not.toContain("q=");
    expect(url).not.toContain("include_inactive");
  });

  it("returns items and total from the response envelope", async () => {
    const items = [{ id: 1, code: "MO", name: "Main d'œuvre", kind: "labor", is_active: true }];
    const fetchMock = vi.fn(async () => jsonResponse({ items, total: 12 }));
    vi.stubGlobal("fetch", fetchMock);

    const page = await getCostTypes({ accessToken: "token" }, vi.fn(), true, { limit: 1, offset: 0 });

    expect(page).toEqual({ items, total: 12 });
  });
});

describe("getProjects query building", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends no query string at all when called with no listParams and includeArchived false", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await getProjects({ accessToken: "token" }, vi.fn());

    expect(String(fetchMock.mock.calls[0][0])).not.toContain("?");
  });

  it("sends limit, offset, sort, and q together, plus include_archived as its own flag", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await getProjects({ accessToken: "token" }, vi.fn(), true, {
      limit: 20,
      offset: 40,
      sort: "-name",
      q: "abc",
    });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("include_archived=true");
    expect(url).toContain("limit=20");
    expect(url).toContain("offset=40");
    expect(url).toContain("sort=-name");
    expect(url).toContain("q=abc");
  });

  it("omits include_archived when false, rather than sending it explicitly", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await getProjects({ accessToken: "token" }, vi.fn(), false, { limit: 5, offset: 0 });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("limit=5");
    expect(url).toContain("offset=0");
    expect(url).not.toContain("include_archived");
  });

  it("returns items and total from the response envelope", async () => {
    const items = [{ id: 1, name: "Projet test", status: "en_cours" }];
    const fetchMock = vi.fn(async () => jsonResponse({ items, total: 3 }));
    vi.stubGlobal("fetch", fetchMock);

    const page = await getProjects({ accessToken: "token" }, vi.fn(), false, { limit: 1, offset: 0 });

    expect(page).toEqual({ items, total: 3 });
  });
});

describe("getCalendars query building", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends no query string at all when called with no listParams, for the unpaginated reference-list case", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await getCalendars({ accessToken: "token" }, vi.fn());

    expect(String(fetchMock.mock.calls[0][0])).not.toContain("?");
  });

  it("sends limit, offset, sort, and q together, plus include_inactive as its own flag", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await getCalendars({ accessToken: "token" }, vi.fn(), true, {
      limit: 20,
      offset: 40,
      sort: "-name",
      q: "abc",
    });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("include_inactive=true");
    expect(url).toContain("limit=20");
    expect(url).toContain("offset=40");
    expect(url).toContain("sort=-name");
    expect(url).toContain("q=abc");
  });

  it("returns items and total from the response envelope", async () => {
    const items = [{ id: 1, code: "STANDARD", name: "Calendrier standard", weeks_per_year: 47, is_active: true, weekdays: [] }];
    const fetchMock = vi.fn(async () => jsonResponse({ items, total: 3 }));
    vi.stubGlobal("fetch", fetchMock);

    const page = await getCalendars({ accessToken: "token" }, vi.fn(), true, { limit: 1, offset: 0 });

    expect(page).toEqual({ items, total: 3 });
  });
});

describe("getResourceRoles query building", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends no query string at all when called with no nodeId or listParams, for the unpaginated reference-list case", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await getResourceRoles({ accessToken: "token" }, vi.fn());

    expect(String(fetchMock.mock.calls[0][0])).not.toContain("?");
  });

  it("combines the structural node_id/include_descendants filter with limit/offset/sort/q", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await getResourceRoles({ accessToken: "token" }, vi.fn(), 3, true, {
      limit: 20,
      offset: 40,
      sort: "-name",
      q: "dev",
    });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("node_id=3");
    expect(url).toContain("include_descendants=true");
    expect(url).toContain("limit=20");
    expect(url).toContain("offset=40");
    expect(url).toContain("sort=-name");
    expect(url).toContain("q=dev");
  });

  it("omits node_id/include_descendants when no node is given, even with pagination params", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await getResourceRoles({ accessToken: "token" }, vi.fn(), undefined, false, { limit: 20, offset: 0 });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).not.toContain("node_id");
    expect(url).not.toContain("include_descendants");
    expect(url).toContain("limit=20");
    expect(url).toContain("offset=0");
  });

  it("returns items and total from the response envelope", async () => {
    const items = [{ id: 1, name: "Développeur", node_id: 1, cost_category_id: 1, calendar_id: null, is_active: true }];
    const fetchMock = vi.fn(async () => jsonResponse({ items, total: 7 }));
    vi.stubGlobal("fetch", fetchMock);

    const page = await getResourceRoles({ accessToken: "token" }, vi.fn(), 1, false, { limit: 1, offset: 0 });

    expect(page).toEqual({ items, total: 7 });
  });

  it("sends include_inactive=true only when explicitly requested (E12-06/#278)", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await getResourceRoles({ accessToken: "token" }, vi.fn(), undefined, false, {}, true);

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("include_inactive=true");
  });

  it("omits include_inactive by default, preserving the active-only on-demand dialog lookup", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await getResourceRoles({ accessToken: "token" }, vi.fn(), 3, true);

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).not.toContain("include_inactive");
  });
});

describe("getResourceNodes query building", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends no query string at all by default", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await getResourceNodes({ accessToken: "token" }, vi.fn());

    expect(String(fetchMock.mock.calls[0][0])).not.toContain("?");
  });

  it("sends include_inactive=true when explicitly requested (E12-06/#278)", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await getResourceNodes({ accessToken: "token" }, vi.fn(), true);

    expect(String(fetchMock.mock.calls[0][0])).toContain("include_inactive=true");
  });
});

describe("getUsers query building", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends no query string at all when called with no listParams, for the unpaginated reference-list case", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await getUsers({ accessToken: "token" }, vi.fn());

    expect(String(fetchMock.mock.calls[0][0])).not.toContain("?");
  });

  it("sends limit, offset, sort, and q together", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await getUsers({ accessToken: "token" }, vi.fn(), {
      limit: 20,
      offset: 40,
      sort: "-email",
      q: "alice",
    });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("limit=20");
    expect(url).toContain("offset=40");
    expect(url).toContain("sort=-email");
    expect(url).toContain("q=alice");
  });

  it("omits sort and q when absent, rather than sending them empty", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await getUsers({ accessToken: "token" }, vi.fn(), { limit: 5, offset: 0 });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("limit=5");
    expect(url).toContain("offset=0");
    expect(url).not.toContain("sort=");
    expect(url).not.toContain("q=");
  });

  it("returns items and total from the response envelope", async () => {
    const items = [{ id: 1, email: "alice@example.com", is_active: true, is_admin: false }];
    const fetchMock = vi.fn(async () => jsonResponse({ items, total: 9 }));
    vi.stubGlobal("fetch", fetchMock);

    const page = await getUsers({ accessToken: "token" }, vi.fn(), { limit: 1, offset: 0 });

    expect(page).toEqual({ items, total: 9 });
  });
});

describe("planning detail pagination", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("concatenates every task and link page", async () => {
    const firstTasks = Array.from({ length: 200 }, (_, index) => ({ uid: index + 1 }));
    const secondTasks = Array.from({ length: 200 }, (_, index) => ({ uid: index + 201 }));
    const finalTasks = Array.from({ length: 5 }, (_, index) => ({ uid: index + 401 }));
    const pages = [firstTasks, secondTasks, finalTasks];
    const firstLinks = [{ task_uid: 2, predecessor_uid: 1 }];
    const secondLinks = [{ task_uid: 202, predecessor_uid: 201 }];
    const finalLinks = [{ task_uid: 402, predecessor_uid: 401 }];
    const linkPages = [firstLinks, secondLinks, finalLinks];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const offset = Number(new URL(url).searchParams.get("offset"));
      return new Response(
        JSON.stringify({
          id: 7,
          project_id: 1,
          version_number: 3,
          status: "validated",
          note: null,
          created_at: "2026-08-21T00:00:00Z",
          validated_at: null,
          tasks: pages[offset / 200],
          links: linkPages[offset / 200],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await getPlanning(1, 7, { accessToken: "token" }, vi.fn());

    expect(result.tasks).toHaveLength(405);
    expect(result.links).toEqual([...firstLinks, ...secondLinks, ...finalLinks]);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(String(fetchMock.mock.calls[0][0])).toContain("limit=200&offset=0");
    expect(String(fetchMock.mock.calls[1][0])).toContain("limit=200&offset=200");
    expect(String(fetchMock.mock.calls[2][0])).toContain("limit=200&offset=400");
  });
});

describe("parseError", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("turns a FastAPI/Pydantic 422 detail array into a readable message", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          detail: [
            { loc: ["body", "cost_category_id"], msg: "Field required", type: "missing" },
            { loc: ["body", "calendar_id"], msg: "Input should be a valid integer", type: "int_type" },
          ],
        }),
        { status: 422, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      updateResourceRole(1, { name: "Dev" }, { accessToken: "token" }, vi.fn()),
    ).rejects.toMatchObject({
      status: 422,
      message: "cost_category_id: Field required; calendar_id: Input should be a valid integer",
    } as Partial<ApiError>);
  });

  it("still surfaces a plain string detail as-is", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "Role not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      updateResourceRole(1, { name: "Dev" }, { accessToken: "token" }, vi.fn()),
    ).rejects.toMatchObject({ status: 404, message: "Role not found" } as Partial<ApiError>);
  });

  it("turns a PLANNING_REVISION_CONFLICT detail into a readable message", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          detail: {
            code: "PLANNING_REVISION_CONFLICT",
            project_id: 1,
            planning_id: 7,
            expected_revision: 0,
            current_revision: 1,
          },
        }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      movePlanningTasks(
        1,
        7,
        { task_uids: [1], target_parent_uid: null, position: 1, expected_revision: 0 },
        { accessToken: "token" },
        vi.fn(),
      ),
    ).rejects.toMatchObject({
      status: 409,
      message: "Ce planning a été modifié entre-temps : recharge-le avant de réessayer.",
    } as Partial<ApiError>);
  });

  it("turns a GENERIC_ERROR detail into the generic French fallback message", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: { code: "GENERIC_ERROR" } }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      movePlanningTasks(
        1,
        7,
        { task_uids: [1], target_parent_uid: null, position: 1, expected_revision: 0 },
        { accessToken: "token" },
        vi.fn(),
      ),
    ).rejects.toMatchObject({
      status: 500,
      message: "Une erreur est survenue. Réessayez ou contactez le support si le problème persiste.",
    } as Partial<ApiError>);
  });

  it("turns a PLANNING_STRUCTURE_REOPEN_REQUIRES_VALIDATION detail into a readable message", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ detail: { code: "PLANNING_STRUCTURE_REOPEN_REQUIRES_VALIDATION" } }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      movePlanningTasks(
        1,
        7,
        { task_uids: [1], target_parent_uid: null, position: 1, expected_revision: 0 },
        { accessToken: "token" },
        vi.fn(),
      ),
    ).rejects.toMatchObject({
      status: 409,
      message: "Cette structure doit d'abord être validée avant de pouvoir être rouverte.",
    } as Partial<ApiError>);
  });

  it("turns a PLANNING_STRUCTURE_REOPEN_INTEGRITY_CONFLICT detail into a readable message", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ detail: { code: "PLANNING_STRUCTURE_REOPEN_INTEGRITY_CONFLICT" } }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      movePlanningTasks(
        1,
        7,
        { task_uids: [1], target_parent_uid: null, position: 1, expected_revision: 0 },
        { accessToken: "token" },
        vi.fn(),
      ),
    ).rejects.toMatchObject({
      status: 409,
      message: "Cette structure ne peut pas être rouverte : son intégrité a été compromise depuis sa validation.",
    } as Partial<ApiError>);
  });

  it("falls back to the generic French message (never the raw JSON body) for an unrecognized structured code", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: { code: "SOME_FUTURE_CODE" } }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      movePlanningTasks(
        1,
        7,
        { task_uids: [1], target_parent_uid: null, position: 1, expected_revision: 0 },
        { accessToken: "token" },
        vi.fn(),
      ),
    ).rejects.toMatchObject({
      status: 500,
      message: "Une erreur est survenue. Réessayez ou contactez le support si le problème persiste.",
    } as Partial<ApiError>);
  });
});

describe("getPlanningTaskDeleteConflict", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("turns a CASCADE_CONFIRMATION_REQUIRED conflict into a readable message and exposes the descendant uids", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ detail: { code: "CASCADE_CONFIRMATION_REQUIRED", descendant_uids: [2, 3] } }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    let thrown: unknown;
    try {
      await deletePlanningTasks(
        1,
        7,
        { task_uids: [1], confirm_cascade: false, expected_revision: 0 },
        { accessToken: "token" },
        vi.fn(),
      );
    } catch (cause) {
      thrown = cause;
    }

    expect(thrown).toBeInstanceOf(ApiError);
    expect((thrown as ApiError).message).toBe(
      "Cette tâche a des tâches enfants et nécessite une confirmation.",
    );
    expect(getPlanningTaskDeleteConflict(thrown)).toEqual({
      code: "CASCADE_CONFIRMATION_REQUIRED",
      descendantUids: [2, 3],
      taskUids: undefined,
    });
  });

  it("turns a TASK_REFERENCED conflict into a readable message and exposes the referenced task uids", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: { code: "TASK_REFERENCED", task_uids: [4] } }), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    let thrown: unknown;
    try {
      await deletePlanningTasks(
        1,
        7,
        { task_uids: [4], confirm_cascade: true, expected_revision: 0 },
        { accessToken: "token" },
        vi.fn(),
      );
    } catch (cause) {
      thrown = cause;
    }

    expect((thrown as ApiError).message).toBe(
      "Cette tâche est référencée par un devis, une affectation ou une charge.",
    );
    expect(getPlanningTaskDeleteConflict(thrown)).toEqual({
      code: "TASK_REFERENCED",
      descendantUids: undefined,
      taskUids: [4],
    });
  });

  it("returns null for a non-409 error, a 409 without a structured detail, or an unrelated error", () => {
    expect(getPlanningTaskDeleteConflict(new ApiError(404, "Not found"))).toBeNull();
    expect(getPlanningTaskDeleteConflict(new ApiError(409, "Conflict"))).toBeNull();
    expect(getPlanningTaskDeleteConflict(new Error("boom"))).toBeNull();
  });
});

// E6-06/#67: creates a task directly from the Devis screen.
describe("createEstimateTask", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the payload to the estimate's tasks endpoint and returns the created row", async () => {
    const createdRow = {
      id: 1,
      estimate_id: 7,
      task_id: 42,
      parent_task_id: null,
      position: 3,
      task_name: "Terrassement",
      outline_number: "1.3",
      outline_level: 1,
      is_milestone: false,
    };
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () =>
        new Response(JSON.stringify(createdRow), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await createEstimateTask(
      1,
      7,
      { name: "Terrassement", is_milestone: false, target_parent_uid: 5 },
      { accessToken: "token" },
      vi.fn(),
    );

    expect(result).toEqual(createdRow);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/projects/1/estimates/7/tasks");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      name: "Terrassement",
      is_milestone: false,
      target_parent_uid: 5,
    });
  });

  it("turns an ESTIMATE_TASK_CREATE_REQUIRES_PLANNING_DRAFT conflict into a readable message that isEstimateTaskCreateRequiresPlanningDraft recognizes", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: { code: "ESTIMATE_TASK_CREATE_REQUIRES_PLANNING_DRAFT" } }), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    let thrown: unknown;
    try {
      await createEstimateTask(1, 7, { name: "Terrassement", is_milestone: false }, { accessToken: "token" }, vi.fn());
    } catch (cause) {
      thrown = cause;
    }

    expect(thrown).toBeInstanceOf(ApiError);
    expect((thrown as ApiError).message).toBe(
      "Le planning affiché n'est plus un brouillon : rouvre sa structure depuis l'onglet Planning avant d'ajouter une tâche depuis le devis.",
    );
    expect(isEstimateTaskCreateRequiresPlanningDraft(thrown)).toBe(true);
  });

  it("does not flag a generic 409 (e.g. estimate/planning no longer a draft) as the reopen-structure case", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "Estimate is not a draft" }), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    let thrown: unknown;
    try {
      await createEstimateTask(1, 7, { name: "Terrassement", is_milestone: false }, { accessToken: "token" }, vi.fn());
    } catch (cause) {
      thrown = cause;
    }

    expect(isEstimateTaskCreateRequiresPlanningDraft(thrown)).toBe(false);
  });

  it("returns false for a non-409 error, a 409 without a structured detail, or an unrelated error", () => {
    expect(isEstimateTaskCreateRequiresPlanningDraft(new ApiError(404, "Not found"))).toBe(false);
    expect(isEstimateTaskCreateRequiresPlanningDraft(new ApiError(409, "Conflict"))).toBe(false);
    expect(isEstimateTaskCreateRequiresPlanningDraft(new Error("boom"))).toBe(false);
  });
});

// E6-07/#68: applies a chained-milestone template to a cost line.
describe("applyEstimateCostLineMilestoneTemplate", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the payload to the cost line's milestones endpoint and returns the created rows", async () => {
    const createdRows = [
      { id: 1, estimate_id: 7, task_id: 42, task_name: "Commande", is_milestone: true },
      { id: 2, estimate_id: 7, task_id: 43, task_name: "Réception", is_milestone: true },
    ];
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () =>
        new Response(JSON.stringify({ items: createdRows, total: 2, limit: null, offset: 0 }), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await applyEstimateCostLineMilestoneTemplate(
      1,
      7,
      3,
      { template: "fourniture", intermediate_milestones_count: 0, lag_minutes: 0 },
      { accessToken: "token" },
      vi.fn(),
    );

    expect(result).toEqual(createdRows);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/projects/1/estimates/7/cost-lines/3/milestones");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      template: "fourniture",
      intermediate_milestones_count: 0,
      lag_minutes: 0,
    });
  });

  it("turns an ESTIMATE_TASK_CREATE_REQUIRES_PLANNING_DRAFT conflict into a readable message that isEstimateTaskCreateRequiresPlanningDraft recognizes, same code as createEstimateTask", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: { code: "ESTIMATE_TASK_CREATE_REQUIRES_PLANNING_DRAFT" } }), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    let thrown: unknown;
    try {
      await applyEstimateCostLineMilestoneTemplate(
        1,
        7,
        3,
        { template: "sous_traitance", intermediate_milestones_count: 2, lag_minutes: 60 },
        { accessToken: "token" },
        vi.fn(),
      );
    } catch (cause) {
      thrown = cause;
    }

    expect(thrown).toBeInstanceOf(ApiError);
    expect((thrown as ApiError).message).toBe(
      "Le planning affiché n'est plus un brouillon : rouvre sa structure depuis l'onglet Planning avant d'ajouter une tâche depuis le devis.",
    );
    expect(isEstimateTaskCreateRequiresPlanningDraft(thrown)).toBe(true);
  });

  it("surfaces a 400 (e.g. a labor cost line) as a plain ApiError the caller can key its own copy off of", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "Milestone templates are only available for a non-labor cost line" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    let thrown: unknown;
    try {
      await applyEstimateCostLineMilestoneTemplate(
        1,
        7,
        3,
        { template: "fourniture", intermediate_milestones_count: 0, lag_minutes: 0 },
        { accessToken: "token" },
        vi.fn(),
      );
    } catch (cause) {
      thrown = cause;
    }

    expect(thrown).toBeInstanceOf(ApiError);
    expect((thrown as ApiError).status).toBe(400);
  });
});

// E12-06/#278: CRUD for EstimateRoleAssignment ("MO"/labor) rows.
describe("EstimateRoleAssignment CRUD", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists role assignments scoped to the given project/estimate", async () => {
    const items = [{ id: 1, estimate_id: 7, task_id: 42, role_id: 1, role_code: "DEV", role_name: "Développeur", cost_category_id: 1, accounting_code: "6410", quantity: 1, hours: 8, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z" }];
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(
      async () => jsonResponse({ items, total: 1 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await listEstimateRoleAssignments(1, 7, { accessToken: "token" }, vi.fn());

    expect(result).toEqual(items);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/projects/1/estimates/7/role-assignments");
  });

  it("posts a new role assignment to the given estimate's own role-assignments endpoint", async () => {
    const created = { id: 1, estimate_id: 7, task_id: 42, role_id: 3, role_code: "DEV", role_name: "Développeur", cost_category_id: 1, accounting_code: "6410", quantity: 1, hours: 8, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z" };
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () => new Response(JSON.stringify(created), { status: 201, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await createEstimateRoleAssignment(
      1,
      7,
      { task_id: 42, role_id: 3, quantity: 1, hours: 8 },
      { accessToken: "token" },
      vi.fn(),
    );

    expect(result).toEqual(created);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/projects/1/estimates/7/role-assignments");
    expect(String(url)).not.toContain("/projects/1/estimates/8/role-assignments");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ task_id: 42, role_id: 3, quantity: 1, hours: 8 });
  });

  it("patches an existing role assignment by id", async () => {
    const updated = { id: 5, estimate_id: 7, task_id: 42, role_id: 3, role_code: "DEV", role_name: "Développeur", cost_category_id: 1, accounting_code: "6410", quantity: 2, hours: 10, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-02T00:00:00Z" };
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () => jsonResponse(updated),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await updateEstimateRoleAssignment(
      1,
      7,
      5,
      { quantity: 2, hours: 10 },
      { accessToken: "token" },
      vi.fn(),
    );

    expect(result).toEqual(updated);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/projects/1/estimates/7/role-assignments/5");
    expect(init?.method).toBe("PATCH");
  });

  it("deletes a role assignment by id", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () => new Response(null, { status: 204 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await deleteEstimateRoleAssignment(1, 7, 5, { accessToken: "token" }, vi.fn());

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/projects/1/estimates/7/role-assignments/5");
    expect(init?.method).toBe("DELETE");
  });
});

// E6-11/#175: the structured MISSING_RATE_COVERAGE detail on createEstimateRoleAssignment's 400.
describe("getMissingRateCoverage / describeMissingRateCoverage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("extracts the structured detail from a 400 MISSING_RATE_COVERAGE response", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          detail: {
            code: "MISSING_RATE_COVERAGE",
            missing_cost_rates: [{ category_id: 1, category_name: "Ingénierie", accounting_code: "6410", year: 2027 }],
            missing_inflation_years: [2028],
          },
        }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    let thrown: unknown;
    try {
      await createEstimateRoleAssignment(1, 7, { task_id: 42, role_id: 3, quantity: 1, hours: 8 }, { accessToken: "token" }, vi.fn());
    } catch (cause) {
      thrown = cause;
    }

    const detail = getMissingRateCoverage(thrown);
    expect(detail).toEqual({
      code: "MISSING_RATE_COVERAGE",
      missing_cost_rates: [{ category_id: 1, category_name: "Ingénierie", accounting_code: "6410", year: 2027 }],
      missing_inflation_years: [2028],
    });
    expect(describeMissingRateCoverage(detail!)).toContain("6410 Ingénierie (2027)");
    expect(describeMissingRateCoverage(detail!)).toContain("taux d'inflation manquant pour 2028");
  });

  it("returns null for a 400 without a MISSING_RATE_COVERAGE structured detail, or an unrelated error", () => {
    expect(getMissingRateCoverage(new ApiError(400, "Bad request"))).toBeNull();
    expect(getMissingRateCoverage(new ApiError(404, "Not found", { code: "MISSING_RATE_COVERAGE" }))).toBeNull();
    expect(getMissingRateCoverage(new Error("boom"))).toBeNull();
  });

  it("describes a detail missing only cost rates, without mentioning inflation", () => {
    const message = describeMissingRateCoverage({
      code: "MISSING_RATE_COVERAGE",
      missing_cost_rates: [{ category_id: 1, category_name: "Ingénierie", accounting_code: "6410", year: 2027 }],
      missing_inflation_years: [],
    });

    expect(message).toContain("6410 Ingénierie (2027)");
    expect(message).not.toContain("inflation");
  });
});
