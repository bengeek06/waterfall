import { describe, expect, it } from "vitest";

import { buildPlanningStructurePayload, type PlanningStructureDraftRow } from "./planning-structure";

describe("buildPlanningStructurePayload", () => {
  it("groups multiple lots under the same post", () => {
    const rows: PlanningStructureDraftRow[] = [
      {
        postKey: "design",
        postName: "Design",
        lotKey: "specification",
        lotName: "Specification",
        deliverables: "Requirements, Architecture",
      },
      {
        postKey: "design",
        postName: "Design",
        lotKey: "validation",
        lotName: "Validation",
        deliverables: "Review",
      },
    ];

    expect(buildPlanningStructurePayload(rows)).toEqual({
      posts: [
        {
          key: "design",
          name: "Design",
          lots: [
            {
              key: "specification",
              name: "Specification",
              deliverables: [
                { key: "deliverable-1", name: "Requirements" },
                { key: "deliverable-2", name: "Architecture" },
              ],
            },
            {
              key: "validation",
              name: "Validation",
              deliverables: [{ key: "deliverable-1", name: "Review" }],
            },
          ],
        },
      ],
    });
  });

  it("removes blank and duplicate deliverables", () => {
    const payload = buildPlanningStructurePayload([
      {
        postKey: "post",
        postName: "Post",
        lotKey: "lot",
        lotName: "Lot",
        deliverables: "One, , One, Two",
      },
    ]);

    expect(payload.posts[0].lots[0].deliverables).toEqual([
      { key: "deliverable-1", name: "One" },
      { key: "deliverable-2", name: "Two" },
    ]);
  });
});
