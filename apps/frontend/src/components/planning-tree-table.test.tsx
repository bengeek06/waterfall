import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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

  it("shows the read-only notice alongside the empty state", () => {
    render(<PlanningTreeTable tasks={[]} versionKey={1} readOnly />);

    expect(screen.getByText("Le planning ne contient aucune tâche.")).toBeInTheDocument();
    expect(
      screen.getByText("Version validée ou projet en lecture seule : édition désactivée."),
    ).toBeInTheDocument();
  });

  it("orders siblings with no position after positioned ones instead of treating null as 0", () => {
    const tasks: Task[] = [
      task({ uid: 1, name: "Sans position", parent_uid: null, position: undefined }),
      task({ uid: 2, name: "Position 1", parent_uid: null, position: 1 }),
    ];

    render(<PlanningTreeTable tasks={tasks} versionKey={1} />);

    const names = screen.getAllByRole("row").slice(1).map((row) => row.textContent ?? "");
    expect(names[0]).toContain("Position 1");
    expect(names[1]).toContain("Sans position");
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

  it("does not render the actions toolbar when read-only or without onMove", () => {
    const { rerender } = render(<PlanningTreeTable tasks={threeLevelTasks} versionKey={1} />);
    expect(screen.queryByRole("button", { name: "Indenter" })).not.toBeInTheDocument();

    rerender(<PlanningTreeTable tasks={threeLevelTasks} versionKey={1} readOnly onMove={() => {}} />);
    expect(screen.queryByRole("button", { name: "Indenter" })).not.toBeInTheDocument();
  });

  it("disables Indenter when the selected task has no previous sibling", () => {
    const onMove = vi.fn();
    render(<PlanningTreeTable tasks={threeLevelTasks} versionKey={1} onMove={onMove} />);

    fireEvent.click(screen.getByText("Livrable"));
    fireEvent.click(screen.getByRole("button", { name: "Indenter" }));

    expect(onMove).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Indenter" })).toBeDisabled();
  });

  it("disables buttons while a mutation is busy even when a command would otherwise be valid", () => {
    const onMove = vi.fn();
    const siblings: Task[] = [
      task({ uid: 1, name: "Premier", parent_uid: null, position: 1 }),
      task({ uid: 2, name: "Second", parent_uid: null, position: 2 }),
    ];
    render(<PlanningTreeTable tasks={siblings} versionKey={1} onMove={onMove} mutationBusy />);

    fireEvent.click(screen.getByText("Second"));

    expect(screen.getByRole("button", { name: "Monter" })).toBeDisabled();
  });

  it("enables Monter and calls onMove with the computed command", () => {
    const onMove = vi.fn();
    const siblings: Task[] = [
      task({ uid: 1, name: "Premier", parent_uid: null, position: 1 }),
      task({ uid: 2, name: "Second", parent_uid: null, position: 2 }),
    ];
    render(<PlanningTreeTable tasks={siblings} versionKey={1} onMove={onMove} />);

    fireEvent.click(screen.getByText("Second"));
    fireEvent.click(screen.getByRole("button", { name: "Monter" }));

    expect(onMove).toHaveBeenCalledWith({ task_uids: [2], target_parent_uid: null, position: 1 });
  });

  it("does not offer schedule edition for a summary task even when editable", () => {
    const onScheduleUpdate = vi.fn();
    render(<PlanningTreeTable tasks={threeLevelTasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    expect(screen.queryByLabelText("Début de Poste")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Mode de Poste")).not.toBeInTheDocument();
  });

  it("does not offer schedule edition when read-only", () => {
    const onScheduleUpdate = vi.fn();
    render(
      <PlanningTreeTable tasks={threeLevelTasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} readOnly />,
    );

    expect(screen.queryByLabelText("Début de Livrable")).not.toBeInTheDocument();
  });

  it("only exposes the start date for a manual milestone, deriving finish_at and duration", () => {
    const onScheduleUpdate = vi.fn();
    const tasks: Task[] = [
      task({
        uid: 1,
        name: "Jalon",
        parent_uid: null,
        position: 1,
        is_milestone: true,
        is_manual: true,
        start_at: "2026-01-05T09:00:00Z",
        finish_at: "2026-01-05T09:00:00Z",
        duration_minutes: 0,
      }),
    ];
    render(<PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    expect(screen.getByLabelText("Début de Jalon")).toBeInTheDocument();
    expect(screen.queryByLabelText("Fin de Jalon")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Durée de Jalon")).not.toBeInTheDocument();
  });

  it("commits a manual task's start/finish/duration edit on blur", () => {
    const onScheduleUpdate = vi.fn();
    const tasks: Task[] = [
      task({
        uid: 1,
        name: "Tâche manuelle",
        parent_uid: null,
        position: 1,
        is_manual: true,
        start_at: "2026-01-05T09:00:00Z",
        finish_at: "2026-01-06T17:00:00Z",
        duration_minutes: 480,
      }),
    ];
    render(<PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    const startInput = screen.getByLabelText("Début de Tâche manuelle");
    fireEvent.change(startInput, { target: { value: "2026-01-06T09:00" } });
    fireEvent.blur(startInput);

    expect(onScheduleUpdate).toHaveBeenCalledTimes(1);
    const [taskUid, payload] = onScheduleUpdate.mock.calls[0];
    expect(taskUid).toBe(1);
    expect(payload.is_manual).toBe(true);
    expect(payload.duration_minutes).toBe(480);
    expect(new Date(payload.start_at).toISOString()).toBe(new Date("2026-01-06T09:00").toISOString());
  });

  it("commits an Enter keypress in a schedule field immediately and blurs the input", () => {
    const onScheduleUpdate = vi.fn();
    const tasks: Task[] = [
      task({
        uid: 1,
        name: "Tâche manuelle",
        parent_uid: null,
        position: 1,
        is_manual: true,
        start_at: "2026-01-05T09:00:00Z",
        finish_at: "2026-01-06T17:00:00Z",
        duration_minutes: 480,
      }),
    ];
    render(<PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    const durationInput = screen.getByLabelText("Durée de Tâche manuelle");
    durationInput.focus();
    fireEvent.change(durationInput, { target: { value: "600" } });
    fireEvent.keyDown(durationInput, { key: "Enter" });

    expect(onScheduleUpdate).toHaveBeenCalledTimes(1);
    expect(onScheduleUpdate.mock.calls[0][1].duration_minutes).toBe(600);
  });

  it("only allows duration edition for an automatic non-milestone task", () => {
    const onScheduleUpdate = vi.fn();
    const tasks: Task[] = [
      task({
        uid: 1,
        name: "Tâche auto",
        parent_uid: null,
        position: 1,
        is_manual: false,
        start_at: "2026-01-05T09:00:00Z",
        finish_at: "2026-01-06T17:00:00Z",
        duration_minutes: 480,
      }),
    ];
    render(<PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    expect(screen.queryByLabelText("Début de Tâche auto")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Fin de Tâche auto")).not.toBeInTheDocument();

    const durationInput = screen.getByLabelText("Durée de Tâche auto");
    fireEvent.change(durationInput, { target: { value: "120" } });
    fireEvent.blur(durationInput);

    expect(onScheduleUpdate).toHaveBeenCalledWith(1, { is_manual: false, duration_minutes: 120 });
  });

  it("does not commit a schedule edit while a mutation is busy", () => {
    const onScheduleUpdate = vi.fn();
    const tasks: Task[] = [
      task({
        uid: 1,
        name: "Tâche manuelle",
        parent_uid: null,
        position: 1,
        is_manual: true,
        start_at: "2026-01-05T09:00:00Z",
        finish_at: "2026-01-06T17:00:00Z",
        duration_minutes: 480,
      }),
    ];
    render(
      <PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} mutationBusy />,
    );

    expect(screen.getByLabelText("Début de Tâche manuelle")).toBeDisabled();
  });

  it("switches a task to manual mode and sends its current schedule as the payload", async () => {
    const onScheduleUpdate = vi.fn();
    const tasks: Task[] = [
      task({
        uid: 1,
        name: "Tâche auto",
        parent_uid: null,
        position: 1,
        is_manual: false,
        start_at: "2026-01-05T09:00:00Z",
        finish_at: "2026-01-06T17:00:00Z",
        duration_minutes: 480,
      }),
    ];
    render(<PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    fireEvent.click(screen.getByLabelText("Mode de Tâche auto"));
    const manualOption = await screen.findByRole("option", { name: "Manuel" });
    fireEvent.pointerDown(manualOption);
    fireEvent.click(manualOption);

    expect(onScheduleUpdate).toHaveBeenCalledWith(1, {
      is_manual: true,
      start_at: "2026-01-05T09:00:00Z",
      finish_at: "2026-01-06T17:00:00Z",
      duration_minutes: 480,
    });
  });

  it("switches a manual non-milestone task with a duration to automatic mode", async () => {
    const onScheduleUpdate = vi.fn();
    const tasks: Task[] = [
      task({
        uid: 1,
        name: "Tâche manuelle",
        parent_uid: null,
        position: 1,
        is_manual: true,
        start_at: "2026-01-05T09:00:00Z",
        finish_at: "2026-01-06T17:00:00Z",
        duration_minutes: 480,
      }),
    ];
    render(<PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    fireEvent.click(screen.getByLabelText("Mode de Tâche manuelle"));
    const automaticOption = await screen.findByRole("option", { name: "Automatique" });
    fireEvent.pointerDown(automaticOption);
    fireEvent.click(automaticOption);

    expect(onScheduleUpdate).toHaveBeenCalledWith(1, {
      is_manual: false,
      start_at: "2026-01-05T09:00:00Z",
      finish_at: "2026-01-06T17:00:00Z",
      duration_minutes: 480,
    });
  });

  it("switches a milestone's mode without sending finish_at or duration_minutes", async () => {
    const onScheduleUpdate = vi.fn();
    const tasks: Task[] = [
      task({
        uid: 1,
        name: "Jalon",
        parent_uid: null,
        position: 1,
        is_milestone: true,
        is_manual: true,
        start_at: "2026-01-05T09:00:00Z",
        finish_at: "2026-01-05T09:00:00Z",
        duration_minutes: 0,
      }),
    ];
    render(<PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    fireEvent.click(screen.getByLabelText("Mode de Jalon"));
    const automaticOption = await screen.findByRole("option", { name: "Automatique" });
    fireEvent.pointerDown(automaticOption);
    fireEvent.click(automaticOption);

    expect(onScheduleUpdate).toHaveBeenCalledWith(1, {
      is_manual: false,
      start_at: "2026-01-05T09:00:00Z",
    });
  });

  it("disables the automatic option for a non-milestone task with no duration set", async () => {
    const onScheduleUpdate = vi.fn();
    const tasks: Task[] = [
      task({
        uid: 1,
        name: "Tâche sans durée",
        parent_uid: null,
        position: 1,
        is_manual: true,
        start_at: "2026-01-05T09:00:00Z",
        finish_at: null,
        duration_minutes: null,
      }),
    ];
    render(<PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    fireEvent.click(screen.getByLabelText("Mode de Tâche sans durée"));

    expect(await screen.findByRole("option", { name: "Automatique" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });
});
