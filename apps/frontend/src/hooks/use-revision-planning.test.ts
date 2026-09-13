import { describe, expect, it } from "vitest";

import type { Revision, RevisionCostLoss } from "@/lib/backend";
import { describeCostLosses, pickRevisionToDisplay } from "./use-revision-planning";

function revision(revisionId: number, versionNumber: number): Revision {
  return {
    revision_id: revisionId,
    project_id: 1,
    version_number: versionNumber,
    kind: "initial",
    status: "draft",
    lock_version: 0,
    note: null,
    created_at: "2026-09-01T00:00:00Z",
    validated_at: null,
  };
}

const revisions = [revision(7, 1), revision(8, 2), revision(9, 3)];

describe("pickRevisionToDisplay", () => {
  it("opens the draft the project is pointing at", () => {
    expect(pickRevisionToDisplay(revisions, 8, 7)).toBe(8);
  });

  it("falls back to the reference when no draft is being worked on", () => {
    // `displayed_revision_id` goes back to NULL on validation: the project then runs against its
    // reference, and that is what must be on screen -- not whatever draft happens to be latest.
    expect(pickRevisionToDisplay(revisions, null, 7)).toBe(7);
  });

  it("falls back to the latest revision when neither pointer is set", () => {
    expect(pickRevisionToDisplay(revisions, null, null)).toBe(9);
  });

  it("ignores a pointer naming a revision that is not in the list", () => {
    expect(pickRevisionToDisplay(revisions, 42, null)).toBe(9);
  });

  it("answers null for a project with no revision at all", () => {
    expect(pickRevisionToDisplay([], 42, 43)).toBeNull();
  });
});

describe("describeCostLosses", () => {
  it("names every chiffrage a deletion took away, and totals them", () => {
    // A cascade's losses *are* deduplicated (one entry per removed node), unlike the per-item
    // lists of an import diff -- so summing them here is correct.
    const losses: RevisionCostLoss[] = [
      { node_id: 1, work_item_id: 10, label: "Étude", nature: "labor", amount: "1000.00", bearing_task_name: "Lot" },
      { node_id: 2, work_item_id: 20, label: "Serveur", nature: "non_labor", amount: "200.50", bearing_task_name: "Lot" },
    ];

    const message = describeCostLosses(losses);

    expect(message).toContain("2 ligne(s)");
    expect(message).toContain("Étude");
    expect(message).toContain("Serveur");
    expect(message).toMatch(/1\s?200,50/);
  });
});
