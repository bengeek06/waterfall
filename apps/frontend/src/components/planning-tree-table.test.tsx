import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Task } from "@/lib/backend";
import { PlanningTreeTable } from "./planning-tree-table";

function task(overrides: Partial<Task>): Task {
  return {
    id: overrides.uid ?? 1,
    project_id: 1,
    uid: 1,
    id_display: null,
    structure_key: null,
    structure_kind: null,
    parent_uid: null,
    position: 1,
    name: "Tâche",
    outline_number: null,
    outline_level: null,
    start_at: null,
    finish_at: null,
    percent_complete: 0,
    is_summary: false,
    is_milestone: false,
    is_manual: true,
    description: null,
    predecessor_links: [],
    ...overrides,
  };
}

const threeLevelTasks: Task[] = [
  task({ uid: 1, name: "Poste", parent_uid: null, position: 1, is_summary: true }),
  task({ uid: 2, name: "Lot", parent_uid: 1, position: 1, is_summary: true }),
  task({ uid: 3, name: "Livrable", parent_uid: 2, position: 1 }),
];

describe("PlanningTreeTable", () => {
  afterEach(() => cleanup());

  it("renders a three-level planning with indentation", () => {
    render(<PlanningTreeTable tasks={threeLevelTasks} versionKey={1} />);

    expect(screen.getByText("Poste")).toBeInTheDocument();
    expect(screen.getByText("Lot")).toBeInTheDocument();
    expect(screen.getByText("Livrable")).toBeInTheDocument();
  });

  it("shows an empty state when the planning has no task", () => {
    render(<PlanningTreeTable tasks={[]} versionKey={1} />);

    expect(screen.getByText("Le planning ne contient aucune tâche.")).toBeInTheDocument();
  });

  it("collapsing a task hides only its descendants", () => {
    render(<PlanningTreeTable tasks={threeLevelTasks} versionKey={1} />);

    fireEvent.click(screen.getByRole("button", { name: "Replier Poste" }));

    expect(screen.getByText("Poste")).toBeInTheDocument();
    expect(screen.queryByText("Lot")).not.toBeInTheDocument();
    expect(screen.queryByText("Livrable")).not.toBeInTheDocument();
  });

  it("expanding again restores descendants and keeps selection", () => {
    render(<PlanningTreeTable tasks={threeLevelTasks} versionKey={1} />);

    fireEvent.click(screen.getByText("Livrable"));
    expect(screen.getByText("Livrable").closest("tr")).toHaveAttribute("data-state", "selected");

    fireEvent.click(screen.getByRole("button", { name: "Replier Lot" }));
    expect(screen.queryByText("Livrable")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Déplier Lot" }));
    expect(screen.getByText("Livrable")).toBeInTheDocument();
  });

  it("supports mono-selection on click and multi-selection with ctrl+click", () => {
    render(<PlanningTreeTable tasks={threeLevelTasks} versionKey={1} />);

    fireEvent.click(screen.getByText("Poste"));
    expect(screen.getByText("Poste").closest("tr")).toHaveAttribute("data-state", "selected");
    expect(screen.getByText("Lot").closest("tr")).not.toHaveAttribute("data-state", "selected");

    fireEvent.click(screen.getByText("Lot"), { ctrlKey: true });
    expect(screen.getByText("Poste").closest("tr")).toHaveAttribute("data-state", "selected");
    expect(screen.getByText("Lot").closest("tr")).toHaveAttribute("data-state", "selected");

    fireEvent.click(screen.getByText("Livrable"));
    expect(screen.getByText("Poste").closest("tr")).not.toHaveAttribute("data-state", "selected");
    expect(screen.getByText("Livrable").closest("tr")).toHaveAttribute("data-state", "selected");
  });

  it("resets collapse and selection state when the planning version changes", () => {
    const { rerender } = render(<PlanningTreeTable tasks={threeLevelTasks} versionKey={1} />);

    fireEvent.click(screen.getByText("Poste"));
    fireEvent.click(screen.getByRole("button", { name: "Replier Lot" }));
    expect(screen.queryByText("Livrable")).not.toBeInTheDocument();

    rerender(<PlanningTreeTable tasks={threeLevelTasks} versionKey={2} />);

    expect(screen.getByText("Livrable")).toBeInTheDocument();
    expect(screen.getByText("Poste").closest("tr")).not.toHaveAttribute("data-state", "selected");
  });

  it("remains usable with a planning of 1000 tasks", () => {
    const manyTasks: Task[] = Array.from({ length: 1000 }, (_, index) =>
      task({ uid: index + 1, name: `Tâche ${index + 1}`, parent_uid: null, position: index + 1 }),
    );

    render(<PlanningTreeTable tasks={manyTasks} versionKey={1} />);

    expect(screen.getAllByRole("row")).toHaveLength(manyTasks.length + 1);
  });

  it("shows a read-only notice for validated versions or read-only projects", () => {
    render(<PlanningTreeTable tasks={threeLevelTasks} versionKey={1} readOnly />);

    expect(
      screen.getByText("Version validée ou projet en lecture seule : édition désactivée."),
    ).toBeInTheDocument();
  });
});
