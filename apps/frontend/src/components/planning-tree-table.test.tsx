import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
    render(<PlanningTreeTable tasks={threeLevelTasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    expect(screen.queryByLabelText("Début de Poste")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Mode de Poste")).not.toBeInTheDocument();
  });

  it("does not offer schedule edition when read-only", () => {
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
    render(
      <PlanningTreeTable tasks={threeLevelTasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} readOnly />,
    );

    expect(screen.queryByLabelText("Début de Livrable")).not.toBeInTheDocument();
  });

  it("only exposes the start date for a manual milestone, deriving finish_at and duration", () => {
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
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

  it("disables the start date editor for an automatic milestone with a predecessor link", () => {
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
    const tasks: Task[] = [
      task({
        uid: 1,
        name: "Prédécesseur",
        parent_uid: null,
        position: 1,
        start_at: "2026-01-05T09:00:00Z",
        finish_at: "2026-01-05T17:00:00Z",
        duration_minutes: 480,
      }),
      task({
        uid: 2,
        name: "Jalon auto",
        parent_uid: null,
        position: 2,
        is_milestone: true,
        is_manual: false,
        start_at: "2026-01-06T09:00:00Z",
        finish_at: "2026-01-06T09:00:00Z",
        duration_minutes: 0,
        predecessor_links: [{ predecessor_uid: 1, link_type: 1, lag_tenth_minute: 0 }],
      }),
    ];
    render(<PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    // The server always lets a predecessor's contributed constraint win over payload.start_at
    // once one exists (_apply_automatic_milestone_schedule); editing here would be a no-op
    // guaranteed to be silently reverted, so the field is disabled with an explanatory label.
    const startInput = screen.getByLabelText("Début de Jalon auto (Date déterminée par les prédécesseurs)");
    expect(startInput).toBeDisabled();
    expect(startInput).toHaveAttribute("title", "Date déterminée par les prédécesseurs");
  });

  it("rejects an emptied start date edit on a milestone instead of sending a no-op request", () => {
    // Neither _apply_manual_milestone_schedule nor _apply_automatic_milestone_schedule can
    // distinguish an omitted start_at from an explicitly cleared one: both fall back to the
    // already-stored value, so a cleared field would 200 without changing anything. The client
    // must not fire that request.
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
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

    const startInput = screen.getByLabelText("Début de Jalon");
    fireEvent.change(startInput, { target: { value: "" } });
    fireEvent.blur(startInput);

    expect(onScheduleUpdate).not.toHaveBeenCalled();
  });

  it("keeps the start date editor enabled for an automatic milestone with no predecessor link", () => {
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
    const tasks: Task[] = [
      task({
        uid: 1,
        name: "Jalon auto",
        parent_uid: null,
        position: 1,
        is_milestone: true,
        is_manual: false,
        start_at: "2026-01-06T09:00:00Z",
        finish_at: "2026-01-06T09:00:00Z",
        duration_minutes: 0,
        predecessor_links: [],
      }),
    ];
    render(<PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    const startInput = screen.getByLabelText("Début de Jalon auto");
    expect(startInput).not.toBeDisabled();
  });

  it("commits a manual task's start/finish/duration edit on blur", () => {
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
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
    // jsdom's own datetime-local value sanitization always truncates to minute precision
    // regardless of `step`, so a seconds-carrying value can't be simulated through this input's
    // change event here; the seconds round-trip itself is covered separately below (see "preserves
    // a manual task's non-zero seconds when only the duration field is edited"), which never goes
    // through this DOM sanitization path. A missing seconds group defaults to :00 (see
    // DATETIME_INPUT_PATTERN).
    fireEvent.change(startInput, { target: { value: "2026-01-06T09:00" } });
    fireEvent.blur(startInput);

    expect(onScheduleUpdate).toHaveBeenCalledTimes(1);
    const [taskUid, payload] = onScheduleUpdate.mock.calls[0];
    expect(taskUid).toBe(1);
    expect(payload.is_manual).toBe(true);
    expect(payload.duration_minutes).toBe(480);
    // The datetime-local field's components are UTC (see toDateTimeInputValue/fromDateTimeInputValue
    // in planning-tree-table.tsx), so "2026-01-06T09:00" must round-trip to exactly this UTC
    // instant regardless of the host's local timezone -- not whatever `new Date("2026-01-06T09:00")`
    // (local-time interpretation) would produce.
    expect(payload.start_at).toBe("2026-01-06T09:00:00.000Z");
  });

  it("does not shift naive-UTC backend datetimes when the browser runs in a non-UTC timezone", () => {
    // The backend returns naive-UTC datetimes with no offset (e.g. "2026-01-09T08:00:00").
    // `new Date(...)` on such a string is interpreted as *local* time by JS, which silently
    // shifted every displayed/round-tripped value by the browser's UTC offset before this fix.
    // Force a non-UTC timezone here so this regression is actually exercised (this test would
    // have failed against the pre-fix implementation in any timezone other than UTC, including
    // this one).
    const originalTz = process.env.TZ;
    process.env.TZ = "America/New_York"; // UTC-5 (winter, no DST ambiguity for this fixed date)
    try {
      const onScheduleUpdate = vi.fn().mockResolvedValue(true);
      const tasks: Task[] = [
        task({
          uid: 1,
          name: "Tâche manuelle",
          parent_uid: null,
          position: 1,
          is_manual: true,
          start_at: "2026-01-09T08:00:00",
          finish_at: "2026-01-09T08:00:00",
          duration_minutes: 480,
        }),
      ];
      render(<PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

      const startInput = screen.getByLabelText<HTMLInputElement>("Début de Tâche manuelle");
      // toDateTimeInputValue must display the value's UTC components (08:00), not the
      // timezone-shifted local ones (which would be 03:00 in America/New_York). jsdom's own
      // datetime-local value sanitization always truncates to minute precision regardless of
      // `step`, so `.value` here reads "08:00" even though toDateTimeInputValue itself produced
      // "08:00:00" (real browsers with `step="1"` preserve the seconds subfield instead).
      expect(startInput.value).toBe("2026-01-09T08:00");

      // Editing the minutes only (leaving the UTC-displayed date/hour untouched) and committing
      // must produce exactly that UTC instant back through fromDateTimeInputValue, with no
      // timezone-induced drift -- this is the round-trip that corrupted data pre-fix.
      fireEvent.change(startInput, { target: { value: "2026-01-09T08:05" } });
      fireEvent.blur(startInput);

      expect(onScheduleUpdate).toHaveBeenCalledTimes(1);
      expect(onScheduleUpdate.mock.calls[0][1].start_at).toBe("2026-01-09T08:05:00.000Z");
    } finally {
      // `process.env.TZ = undefined` would coerce to the literal string "undefined" instead of
      // clearing the variable, leaking a bogus timezone into subsequent tests in this worker.
      if (originalTz === undefined) {
        delete process.env.TZ;
      } else {
        process.env.TZ = originalTz;
      }
    }
  });

  it("commits an Enter keypress in a schedule field immediately and blurs the input", () => {
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
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

  it("preserves a manual task's non-zero seconds when only the duration field is edited", () => {
    // commitScheduleEdit always resends start_at/finish_at/duration_minutes together for a manual
    // task, even when the user only touched the duration field. lag_tenth_minute-derived dates can
    // carry a non-zero, non-minute-aligned seconds component (a multiple of 6s), so
    // toDateTimeInputValue/fromDateTimeInputValue must round-trip seconds losslessly, or an
    // untouched start_at/finish_at would be silently truncated to :00 on every commit.
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
    const tasks: Task[] = [
      task({
        uid: 1,
        name: "Tâche manuelle",
        parent_uid: null,
        position: 1,
        is_manual: true,
        start_at: "2026-01-09T10:00:30",
        finish_at: "2026-01-09T11:00:30",
        duration_minutes: 60,
      }),
    ];
    render(<PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    const durationInput = screen.getByLabelText("Durée de Tâche manuelle");
    fireEvent.change(durationInput, { target: { value: "90" } });
    fireEvent.blur(durationInput);

    expect(onScheduleUpdate).toHaveBeenCalledTimes(1);
    const [taskUid, payload] = onScheduleUpdate.mock.calls[0];
    expect(taskUid).toBe(1);
    expect(payload.duration_minutes).toBe(90);
    expect(payload.start_at).toBe("2026-01-09T10:00:30.000Z");
    expect(payload.finish_at).toBe("2026-01-09T11:00:30.000Z");
  });

  it("keeps the schedule draft in place when the update fails, instead of reverting to the stale value", async () => {
    // If onScheduleUpdate's request fails (network error, server validation, conflict...) the
    // draft must survive: clearing it regardless of outcome would make scheduleDraftFor(row) fall
    // back to defaultScheduleDraft (the never-updated `row` prop), silently discarding whatever the
    // user typed with no way to recover it.
    const onScheduleUpdate = vi.fn().mockResolvedValue(false);
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

    const durationInput = screen.getByLabelText<HTMLInputElement>("Durée de Tâche manuelle");
    fireEvent.change(durationInput, { target: { value: "600" } });
    fireEvent.blur(durationInput);

    expect(onScheduleUpdate).toHaveBeenCalledTimes(1);
    // Give the rejected/false-resolving update a chance to settle, then confirm the field still
    // shows the user's typed value rather than having bounced back to the original 480.
    await waitFor(() => expect(durationInput.value).toBe("600"));
  });

  it("only allows duration edition for an automatic non-milestone task", () => {
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
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

  it("rejects a 0 or empty duration edit on an automatic non-milestone task instead of sending a doomed request", () => {
    // _apply_automatic_schedule rejects a null/0/negative duration_minutes with a 400 server-side;
    // the client must not fire that request.
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
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

    const durationInput = screen.getByLabelText("Durée de Tâche auto");
    expect(durationInput).toHaveAttribute("min", "1");

    fireEvent.change(durationInput, { target: { value: "0" } });
    fireEvent.blur(durationInput);
    expect(onScheduleUpdate).not.toHaveBeenCalled();

    fireEvent.change(durationInput, { target: { value: "" } });
    fireEvent.blur(durationInput);
    expect(onScheduleUpdate).not.toHaveBeenCalled();
  });

  it("does not commit a schedule edit on blur when nothing was typed", () => {
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
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
    fireEvent.focus(startInput);
    fireEvent.blur(startInput);

    expect(onScheduleUpdate).not.toHaveBeenCalled();
  });

  it("does not commit a schedule edit while a mutation is busy", () => {
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
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
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
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
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
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
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
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

  it("does not let an arrow key on the mode selector bubble up to the row's navigation", () => {
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
    const siblings: Task[] = [
      task({ uid: 1, name: "Premier", parent_uid: null, position: 1, is_manual: false }),
      task({ uid: 2, name: "Second", parent_uid: null, position: 2, is_manual: false }),
    ];
    render(<PlanningTreeTable tasks={siblings} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    const trigger = screen.getByLabelText("Mode de Premier");
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });

    // If the keydown had bubbled to the row, the row navigation handler would have moved focus
    // to the sibling row (see the useEffect that re-focuses the row matching focusedUid).
    expect(document.activeElement).toBe(trigger);
  });

  it("disables the automatic option for a non-milestone task with no duration set", async () => {
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
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

  it("disables the automatic option for a non-milestone task with a zero duration", async () => {
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
    const tasks: Task[] = [
      task({
        uid: 1,
        name: "Tâche durée nulle",
        parent_uid: null,
        position: 1,
        is_manual: true,
        start_at: "2026-01-05T09:00:00Z",
        finish_at: null,
        duration_minutes: 0,
      }),
    ];
    render(<PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    fireEvent.click(screen.getByLabelText("Mode de Tâche durée nulle"));

    expect(await screen.findByRole("option", { name: "Automatique" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("disables the automatic option for a non-milestone task with no start_at and no predecessors", async () => {
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
    const tasks: Task[] = [
      task({
        uid: 1,
        name: "Tâche sans ancre",
        parent_uid: null,
        position: 1,
        is_manual: true,
        start_at: null,
        finish_at: null,
        duration_minutes: 480,
        predecessor_links: [],
      }),
    ];
    render(<PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    fireEvent.click(screen.getByLabelText("Mode de Tâche sans ancre"));

    expect(await screen.findByRole("option", { name: "Automatique" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("disables the automatic option for a milestone with no start_at and no predecessors", async () => {
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
    const tasks: Task[] = [
      task({
        uid: 1,
        name: "Jalon sans ancre",
        parent_uid: null,
        position: 1,
        is_milestone: true,
        is_manual: true,
        start_at: null,
        finish_at: null,
        duration_minutes: 0,
        predecessor_links: [],
      }),
    ];
    render(<PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    fireEvent.click(screen.getByLabelText("Mode de Jalon sans ancre"));

    expect(await screen.findByRole("option", { name: "Automatique" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("keeps the automatic option enabled when a task has no start_at but has a predecessor link", async () => {
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
    const tasks: Task[] = [
      task({
        uid: 1,
        name: "Tâche avec prédécesseur",
        parent_uid: null,
        position: 1,
        is_manual: true,
        start_at: null,
        finish_at: null,
        duration_minutes: 480,
        predecessor_links: [{ predecessor_uid: 2, link_type: 1, lag_tenth_minute: 0 }],
      }),
    ];
    render(<PlanningTreeTable tasks={tasks} versionKey={1} onScheduleUpdate={onScheduleUpdate} />);

    fireEvent.click(screen.getByLabelText("Mode de Tâche avec prédécesseur"));

    expect(await screen.findByRole("option", { name: "Automatique" })).not.toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });
});
