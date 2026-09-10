import { describe, expect, it, vi, afterEach } from "vitest";

import {
  computeIndicativeLaborCost,
  resolveIndicativeHourlyRate,
  resolveRoleAssignmentYear,
} from "@/lib/estimate-role-assignment";
import type { CostRate, EstimateRoleAssignment, Task } from "@/lib/backend";

function makeTask(overrides: Partial<Task> = {}): Task {
  return { id: 1, project_id: 1, uid: 1, row_number: 1, name: "Tâche", is_summary: false, is_milestone: false, ...overrides } as Task;
}

function makeRate(overrides: Partial<CostRate> = {}): CostRate {
  return { id: 1, cost_category_id: 1, year: 2026, hourly_rate: 50, currency_code: "EUR", ...overrides } as CostRate;
}

describe("resolveRoleAssignmentYear", () => {
  it("uses the attached task's start_at year when the task is dated", () => {
    const tasks = [makeTask({ id: 42, start_at: "2027-03-15T00:00:00Z" })];

    expect(resolveRoleAssignmentYear(42, tasks)).toBe(2027);
  });

  it("falls back to the current calendar year when the task has no start_at", () => {
    const tasks = [makeTask({ id: 42, start_at: null })];

    expect(resolveRoleAssignmentYear(42, tasks)).toBe(new Date().getFullYear());
  });

  it("falls back to the current calendar year when the task can't be found", () => {
    expect(resolveRoleAssignmentYear(999, [])).toBe(new Date().getFullYear());
  });

  it("falls back to the current calendar year for a root labor line (task_id: null)", () => {
    expect(resolveRoleAssignmentYear(null, [])).toBe(new Date().getFullYear());
  });
});

describe("resolveIndicativeHourlyRate", () => {
  afterEach(() => vi.useRealTimers());

  it("finds the rate matching both cost_category_id and year", () => {
    const rates = [makeRate({ cost_category_id: 1, year: 2026, hourly_rate: 42 }), makeRate({ cost_category_id: 2, year: 2026, hourly_rate: 99 })];

    expect(resolveIndicativeHourlyRate(1, 2026, rates)).toEqual(rates[0]);
  });

  it("returns null when no rate matches", () => {
    const rates = [makeRate({ cost_category_id: 1, year: 2025 })];

    expect(resolveIndicativeHourlyRate(1, 2026, rates)).toBeNull();
  });
});

describe("computeIndicativeLaborCost", () => {
  it("computes quantity x hours x hourly_rate", () => {
    const assignment = { quantity: 2, hours: 10 } as EstimateRoleAssignment;
    const rate = makeRate({ hourly_rate: 50 });

    expect(computeIndicativeLaborCost(assignment, rate)).toBe(1000);
  });

  it("returns null (not 0) when no rate could be resolved", () => {
    const assignment = { quantity: 2, hours: 10 } as EstimateRoleAssignment;

    expect(computeIndicativeLaborCost(assignment, null)).toBeNull();
  });
});
