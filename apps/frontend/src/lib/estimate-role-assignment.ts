import type { CostRate, EstimateRoleAssignment, Task } from "@/lib/backend";

// Resolves the calendar year used to preview an indicative hourly rate for a labor line
// (E12-06/#278): the attached task's own `start_at` year once the task is dated -- the same
// "dated" test the backend's own MISSING_RATE_COVERAGE check applies (#175, `start_at` set) --
// falling back to the current calendar year for a not-yet-scheduled task. This is purely a
// client-side preview: the backend remains the sole source of truth for the year actually used
// once the estimate is validated, so this function must never be mistaken for a second
// calculation engine (see resolveIndicativeHourlyRate/computeIndicativeLaborCost below, same
// caveat).
export function resolveRoleAssignmentYear(taskId: number, planningTasks: Task[]): number {
  const task = planningTasks.find((candidate) => candidate.id === taskId);
  if (task?.start_at) {
    const parsed = new Date(task.start_at);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.getUTCFullYear();
    }
  }
  return new Date().getFullYear();
}

// Finds the CostRate matching (costCategoryId, year), or null if none is loaded. The caller
// (cost-lines-table.tsx) must show an explicit "—" fallback rather than treating a missing rate
// as a rate of zero -- a real, deliberate zero-euro rate would otherwise be indistinguishable
// from "no rate configured at all".
export function resolveIndicativeHourlyRate(
  costCategoryId: number,
  year: number,
  costRates: CostRate[],
): CostRate | null {
  return costRates.find((rate) => rate.cost_category_id === costCategoryId && rate.year === year) ?? null;
}

// Indicative "MO" column value: quantity x hours x the resolved hourly rate, or null if no rate
// could be resolved (see resolveIndicativeHourlyRate above) -- never silently falls back to 0,
// which would be indistinguishable from a legitimately free assignment.
export function computeIndicativeLaborCost(
  assignment: Pick<EstimateRoleAssignment, "quantity" | "hours">,
  hourlyRate: CostRate | null,
): number | null {
  if (!hourlyRate) {
    return null;
  }
  return assignment.quantity * assignment.hours * hourlyRate.hourly_rate;
}
