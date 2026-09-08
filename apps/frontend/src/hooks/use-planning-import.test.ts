import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImportBatchStatus, Planning, PlanningDetail, Project } from "@/lib/backend";
import { SessionExpiredError } from "@/lib/backend";

const mocks = vi.hoisted(() => ({
  getPlanning: vi.fn(),
  getImportBatchStatus: vi.fn(),
}));

vi.mock("@/lib/backend", async () => {
  const actual = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
  return {
    ...actual,
    getPlanning: mocks.getPlanning,
    getImportBatchStatus: mocks.getImportBatchStatus,
  };
});

import {
  applyImportRefreshes,
  applySettledRefresh,
  buildImportFeedbackMessage,
  pickNextPlanningId,
  pollImportBatchStatus,
  refreshPlanningDetailAfterImport,
} from "@/hooks/use-planning-import";

const session = { accessToken: "test-token" };
const onSessionRefresh = vi.fn();

beforeEach(() => {
  mocks.getPlanning.mockReset();
  mocks.getImportBatchStatus.mockReset();
  onSessionRefresh.mockReset();
});

describe("applySettledRefresh", () => {
  it("applies the value and reports no failure when the promise is fulfilled", () => {
    const onSuccess = vi.fn();
    const result = applySettledRefresh(
      { status: "fulfilled", value: 42 } as PromiseSettledResult<number>,
      onSuccess,
      "le projet",
    );

    expect(onSuccess).toHaveBeenCalledWith(42);
    expect(result).toEqual({ sessionExpired: false, failureLabel: null });
  });

  it("reports a session expiry without calling onSuccess when rejected with SessionExpiredError", () => {
    const onSuccess = vi.fn();
    const result = applySettledRefresh(
      { status: "rejected", reason: new SessionExpiredError() } as PromiseSettledResult<number>,
      onSuccess,
      "le projet",
    );

    expect(onSuccess).not.toHaveBeenCalled();
    expect(result).toEqual({ sessionExpired: true, failureLabel: null });
  });

  it("reports the failure label without calling onSuccess when rejected with another error", () => {
    const onSuccess = vi.fn();
    const result = applySettledRefresh(
      { status: "rejected", reason: new Error("boom") } as PromiseSettledResult<number>,
      onSuccess,
      "le projet",
    );

    expect(onSuccess).not.toHaveBeenCalled();
    expect(result).toEqual({ sessionExpired: false, failureLabel: "le projet" });
  });
});

describe("applyImportRefreshes", () => {
  it("applies both values and reports no failures when both refreshes succeed", () => {
    const setProject = vi.fn();
    const setPlannings = vi.fn();
    const project = { id: 1 } as Project;
    const plannings = [{ id: 2 }] as Planning[];

    const result = applyImportRefreshes(
      { status: "fulfilled", value: project },
      { status: "fulfilled", value: plannings },
      setProject,
      setPlannings,
    );

    expect(setProject).toHaveBeenCalledWith(project);
    expect(setPlannings).toHaveBeenCalledWith(plannings);
    expect(result).toEqual({ sessionExpired: false, refreshFailures: [] });
  });

  it("short-circuits with sessionExpired when the project refresh's session expired", () => {
    const setProject = vi.fn();
    const setPlannings = vi.fn();

    const result = applyImportRefreshes(
      { status: "rejected", reason: new SessionExpiredError() },
      { status: "rejected", reason: new Error("boom") },
      setProject,
      setPlannings,
    );

    expect(setProject).not.toHaveBeenCalled();
    expect(setPlannings).not.toHaveBeenCalled();
    expect(result).toEqual({ sessionExpired: true, refreshFailures: [] });
  });

  it("short-circuits with sessionExpired when the plannings refresh's session expired", () => {
    const setProject = vi.fn();
    const setPlannings = vi.fn();
    const project = { id: 1 } as Project;

    const result = applyImportRefreshes(
      { status: "fulfilled", value: project },
      { status: "rejected", reason: new SessionExpiredError() },
      setProject,
      setPlannings,
    );

    expect(setProject).toHaveBeenCalledWith(project);
    expect(setPlannings).not.toHaveBeenCalled();
    expect(result).toEqual({ sessionExpired: true, refreshFailures: [] });
  });

  it("aggregates both failure labels when both refreshes fail with non-session errors", () => {
    const setProject = vi.fn();
    const setPlannings = vi.fn();

    const result = applyImportRefreshes(
      { status: "rejected", reason: new Error("boom") },
      { status: "rejected", reason: new Error("boom") },
      setProject,
      setPlannings,
    );

    expect(result).toEqual({
      sessionExpired: false,
      refreshFailures: ["le projet", "les versions de planning"],
    });
  });
});

describe("refreshPlanningDetailAfterImport", () => {
  it("clears the planning detail and does not call the API when there is no next planning", async () => {
    const setPlanningDetail = vi.fn();
    const refreshFailures: string[] = [];

    const sessionExpired = await refreshPlanningDetailAfterImport(
      1,
      null,
      session,
      onSessionRefresh,
      setPlanningDetail,
      refreshFailures,
    );

    expect(sessionExpired).toBe(false);
    expect(setPlanningDetail).toHaveBeenCalledWith(null);
    expect(mocks.getPlanning).not.toHaveBeenCalled();
    expect(refreshFailures).toEqual([]);
  });

  it("applies the refreshed planning detail on success", async () => {
    const setPlanningDetail = vi.fn();
    const refreshFailures: string[] = [];
    const detail = { id: 2 } as PlanningDetail;
    mocks.getPlanning.mockResolvedValue(detail);

    const sessionExpired = await refreshPlanningDetailAfterImport(
      1,
      2,
      session,
      onSessionRefresh,
      setPlanningDetail,
      refreshFailures,
    );

    expect(sessionExpired).toBe(false);
    expect(mocks.getPlanning).toHaveBeenCalledWith(1, 2, session, onSessionRefresh);
    expect(setPlanningDetail).toHaveBeenCalledWith(detail);
    expect(refreshFailures).toEqual([]);
  });

  it("signals a session expiry without pushing a failure label", async () => {
    const setPlanningDetail = vi.fn();
    const refreshFailures: string[] = [];
    mocks.getPlanning.mockRejectedValue(new SessionExpiredError());

    const sessionExpired = await refreshPlanningDetailAfterImport(
      1,
      2,
      session,
      onSessionRefresh,
      setPlanningDetail,
      refreshFailures,
    );

    expect(sessionExpired).toBe(true);
    expect(setPlanningDetail).not.toHaveBeenCalled();
    expect(refreshFailures).toEqual([]);
  });

  it("pushes a failure label and does not signal a session expiry for other errors", async () => {
    const setPlanningDetail = vi.fn();
    const refreshFailures: string[] = [];
    mocks.getPlanning.mockRejectedValue(new Error("boom"));

    const sessionExpired = await refreshPlanningDetailAfterImport(
      1,
      2,
      session,
      onSessionRefresh,
      setPlanningDetail,
      refreshFailures,
    );

    expect(sessionExpired).toBe(false);
    expect(setPlanningDetail).not.toHaveBeenCalled();
    expect(refreshFailures).toEqual(["le détail du planning"]);
  });
});

describe("pickNextPlanningId", () => {
  it("prefers the project's displayed planning when set", () => {
    const project = { displayed_planning_id: 5 } as Project;
    const plannings = [{ id: 9 }] as Planning[];

    expect(pickNextPlanningId(project, plannings)).toBe(5);
  });

  it("falls back to the most recent planning when there is no displayed planning", () => {
    const project = { displayed_planning_id: null } as unknown as Project;
    const plannings = [{ id: 9 }, { id: 11 }] as Planning[];

    expect(pickNextPlanningId(project, plannings)).toBe(11);
  });

  it("returns null when there is no project and no planning", () => {
    expect(pickNextPlanningId(null, [])).toBeNull();
  });
});

describe("buildImportFeedbackMessage", () => {
  it("returns the happy-path message when there are no failures", () => {
    expect(buildImportFeedbackMessage([])).toBe("Import réussi. Le planning affiché a été actualisé.");
  });

  it("returns a combined message listing every failure when there are some", () => {
    expect(buildImportFeedbackMessage(["le projet", "les versions de planning"])).toBe(
      "Import réussi, mais le projet et les versions de planning n'ont pas pu être actualisés. Recharge la page pour voir l'état à jour.",
    );
  });
});

describe("pollImportBatchStatus", () => {
  it("returns immediately once the batch status is success", async () => {
    mocks.getImportBatchStatus.mockResolvedValue({ status: "success" } as ImportBatchStatus);

    const status = await pollImportBatchStatus(42, session, onSessionRefresh);

    expect(status.status).toBe("success");
    expect(mocks.getImportBatchStatus).toHaveBeenCalledTimes(1);
    expect(mocks.getImportBatchStatus).toHaveBeenCalledWith(42, session, onSessionRefresh);
  });

  it("throws the batch's error message once the batch status is failed", async () => {
    mocks.getImportBatchStatus.mockResolvedValue({
      status: "failed",
      errorMessage: "Fichier corrompu.",
    } as ImportBatchStatus);

    await expect(pollImportBatchStatus(42, session, onSessionRefresh)).rejects.toThrow("Fichier corrompu.");
  });

  it("throws a default message when the batch failed without an error message", async () => {
    mocks.getImportBatchStatus.mockResolvedValue({ status: "failed" } as ImportBatchStatus);

    await expect(pollImportBatchStatus(42, session, onSessionRefresh)).rejects.toThrow("Import en échec.");
  });
});
