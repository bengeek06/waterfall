import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  deletePlanningTasks,
  getCalendars,
  getCostTypes,
  getPlanning,
  getPlanningTaskDeleteConflict,
  getResourceRoles,
  getUsers,
  movePlanningTasks,
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
