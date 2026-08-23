import { describe, expect, it } from "vitest";

import {
  buildPlanningStructurePayload,
  getPlanningStructureDraftRows,
  structureToDraftRows,
  type PlanningStructureDraftRow,
} from "./planning-structure";

describe("buildPlanningStructurePayload", () => {
  it("groups multiple lots under the same post", () => {
    const rows: PlanningStructureDraftRow[] = [
      {
        rowId: "row-1",
        postKey: "design",
        postName: "Design",
        lotKey: "specification",
        lotName: "Specification",
        deliverables: "Requirements, Architecture",
      },
      {
        rowId: "row-2",
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
        rowId: "row-3",
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

  it("builds editable rows from a selected planning when no draft payload exists", () => {
    const detail = {
      tasks: [
        { uid: 1, structure_kind: "poste", structure_key: "design", name: "Design" },
        { uid: 2, structure_kind: "lot", structure_key: "design/spec", name: "Specification" },
        { uid: 3, structure_kind: "livrable", structure_key: "design/spec/requirements", name: "Requirements" },
      ],
    } as never;

    expect(getPlanningStructureDraftRows(detail)).toEqual([
      {
        rowId: "design/spec/requirements",
        postKey: "design",
        postName: "Design",
        lotKey: "spec",
        lotName: "Specification",
        deliverables: "Requirements",
        deliverableKeys: { Requirements: "requirements" },
      },
    ]);
  });

  it("preserves existing deliverable keys across a rows -> payload -> rows round-trip", () => {
    const structure = {
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
                { key: "custom-arch", name: "Architecture" },
              ],
            },
          ],
        },
      ],
    };

    const rows = structureToDraftRows(structure);
    const payload = buildPlanningStructurePayload(rows);

    // Keys are reused verbatim, no deliverable-N reassignment.
    expect(payload.posts[0].lots[0].deliverables).toEqual([
      { key: "deliverable-1", name: "Requirements" },
      { key: "custom-arch", name: "Architecture" },
    ]);
    // Round-trip back to rows is stable.
    expect(structureToDraftRows(payload)).toEqual(rows);
  });

  it("only assigns new keys above existing ones for genuinely new deliverables", () => {
    const rows: PlanningStructureDraftRow[] = [
      {
        rowId: "row-1",
        postKey: "design",
        postName: "Design",
        lotKey: "spec",
        lotName: "Specification",
        deliverables: "Requirements, Architecture, Newcomer",
        deliverableKeys: { Requirements: "deliverable-1", Architecture: "deliverable-2" },
      },
    ];

    expect(buildPlanningStructurePayload(rows).posts[0].lots[0].deliverables).toEqual([
      { key: "deliverable-1", name: "Requirements" },
      { key: "deliverable-2", name: "Architecture" },
      { key: "deliverable-3", name: "Newcomer" },
    ]);
  });
});
