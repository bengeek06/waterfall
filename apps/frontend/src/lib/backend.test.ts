import { afterEach, describe, expect, it, vi } from "vitest";

import { getPlanning } from "./backend";

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
