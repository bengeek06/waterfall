import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  deletePlanningTasks,
  getPlanning,
  getPlanningTaskDeleteConflict,
  movePlanningTasks,
  updateResourceRole,
} from "./backend";

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
