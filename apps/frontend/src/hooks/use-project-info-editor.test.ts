import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "@/lib/backend";
import { ApiError } from "@/lib/backend";

const mocks = vi.hoisted(() => ({
  updateProject: vi.fn(),
  clearSession: vi.fn(),
}));

vi.mock("@/lib/backend", async () => {
  const actual = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
  return { ...actual, updateProject: mocks.updateProject };
});

vi.mock("@/lib/session", () => ({
  clearSession: mocks.clearSession,
}));

import { useProjectInfoEditor } from "@/hooks/use-project-info-editor";

const session = { accessToken: "test-token" };
const project = { id: 1, name: "Projet A", short_description: null } as Project;

function setup() {
  const router = { push: vi.fn() };
  const setProject = vi.fn();
  const setError = vi.fn();
  const { result } = renderHook(() =>
    useProjectInfoEditor({
      session,
      project,
      projectId: 1,
      onSessionRefresh: vi.fn(),
      router: router as never,
      setProject,
      setError,
    }),
  );
  return { result, router, setProject, setError };
}

describe("useProjectInfoEditor saveProjectInfo", () => {
  beforeEach(() => {
    mocks.updateProject.mockReset();
    mocks.clearSession.mockReset();
  });

  // Regression test for #216: a refresh can succeed yet the retried request still
  // come back 401 (account disabled/deleted between the two calls, server-side
  // race) -- authFetch then rejects with a plain ApiError, not a
  // SessionExpiredError. saveProjectInfo must still detect that as a session
  // expiry (clearSession + redirect), not surface it as a generic error.
  it("clears the session and redirects to login on a post-refresh 401 ApiError, instead of showing a generic error", async () => {
    mocks.updateProject.mockRejectedValue(new ApiError(401, "Unauthorized"));
    const { result, router, setError } = setup();

    act(() => {
      result.current.startEditProjectInfo();
    });
    act(() => {
      result.current.updateProjectInfoName("Nouveau nom");
    });
    await act(async () => {
      await result.current.saveProjectInfo();
    });

    expect(mocks.clearSession).toHaveBeenCalled();
    expect(router.push).toHaveBeenCalledWith("/login");
    expect(setError).not.toHaveBeenCalledWith("Impossible de modifier le projet.");
  });
});
