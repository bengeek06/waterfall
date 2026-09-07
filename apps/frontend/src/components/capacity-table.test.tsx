import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CapacityTable, type CapacityTableProps } from "./capacity-table";

const nodeCodeById = new Map([[1, "IT"]]);

function renderTable(overrides: Partial<CapacityTableProps> = {}) {
  const props: CapacityTableProps = {
    items: [{ id: 1, name: "Développeur", node_id: 1 } as never],
    pagination: { total: 1, limit: 20, offset: 0 },
    onPaginationChange: vi.fn(),
    sort: null,
    onSortChange: vi.fn(),
    search: "",
    onSearchChange: vi.fn(),
    isLoading: false,
    drafts: {},
    savedByRoleId: new Map(),
    actionBusy: false,
    nodeCodeById,
    onDraftChange: vi.fn(),
    onSave: vi.fn(),
    ...overrides,
  };
  return render(<CapacityTable {...props} />);
}

describe("CapacityTable", () => {
  afterEach(() => cleanup());

  it("updates a role draft and exposes its save action", () => {
    const onDraftChange = vi.fn();
    const onSave = vi.fn();
    renderTable({
      drafts: { 1: { personCount: "2.00", availableHours: "3200.00" } },
      onDraftChange,
      onSave,
    });

    fireEvent.change(screen.getByDisplayValue("2.00"), { target: { value: "3.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(onDraftChange).toHaveBeenCalledWith(1, { personCount: "3.00", availableHours: "3200.00" });
    expect(onSave).toHaveBeenCalledWith(1);
  });

  it("defaults a role without an existing capacity draft to 0.00/0.00, still editable and creatable inline", () => {
    renderTable({ drafts: {} });

    expect(screen.getByLabelText("Nombre de personnes pour Développeur — IT (#1)")).toHaveValue(0);
    expect(screen.getByLabelText("Heures disponibles pour Développeur — IT (#1)")).toHaveValue(0);
    expect(screen.getByRole("button", { name: "Enregistrer" })).toBeInTheDocument();
  });

  it("disambiguates two roles that share the same name but belong to different nodes", () => {
    const twoNodeCodeById = new Map([
      [1, "IT"],
      [2, "DTSI"],
    ]);
    renderTable({
      items: [
        { id: 1, name: "Développeur", node_id: 1 } as never,
        { id: 2, name: "Développeur", node_id: 2 } as never,
      ],
      nodeCodeById: twoNodeCodeById,
    });

    expect(screen.getByText("Développeur — IT (#1)")).toBeInTheDocument();
    expect(screen.getByText("Développeur — DTSI (#2)")).toBeInTheDocument();
  });

  it("disambiguates two roles that share the same name within the same node using role id", () => {
    renderTable({
      items: [
        { id: 5, name: "Développeur", node_id: 1 } as never,
        { id: 6, name: "Développeur", node_id: 1 } as never,
      ],
    });

    // Same name AND same node code ("IT") — only "(#<role.id>)" can tell them apart.
    // Without that suffix both cells would render identical text "Développeur — IT".
    expect(screen.getByText("Développeur — IT (#5)")).toBeInTheDocument();
    expect(screen.getByText("Développeur — IT (#6)")).toBeInTheDocument();
  });

  it("calls onSortChange with the server column name when the role header is clicked", () => {
    const onSortChange = vi.fn();
    renderTable({ onSortChange });
    fireEvent.click(screen.getByRole("button", { name: "Rôle" }));
    expect(onSortChange).toHaveBeenCalledExactlyOnceWith("name");
  });

  it("searches through the shared DataTable search input", () => {
    const onSearchChange = vi.fn();
    renderTable({ onSearchChange, search: "dev" });
    expect(screen.getByLabelText("Rechercher un rôle")).toHaveValue("dev");
  });

  it("paginates through the shared DataTable controls", () => {
    const onPaginationChange = vi.fn();
    renderTable({
      pagination: { total: 40, limit: 20, offset: 0 },
      onPaginationChange,
    });
    fireEvent.click(screen.getByRole("button", { name: "Suivant" }));
    expect(onPaginationChange).toHaveBeenCalledWith({ offset: 20, limit: 20 });
  });

  it("shows the loading skeleton while a page is being fetched", () => {
    renderTable({ isLoading: true });
    expect(screen.getByRole("status", { name: "Chargement des données" })).toBeInTheDocument();
  });

  it("keeps focus on a capacity input across keystrokes, even though every keystroke round-trips through the parent's drafts prop", () => {
    // Regression test for a real bug: TanStack Table's `flexRender` passes each
    // cell renderer to React as a component *type*. Rebuilding `columns` inline
    // on every render (as this component used to) gives every cell a new
    // function identity whenever `drafts` changes -- which happens on every
    // keystroke, since the parent stores drafts in its own state and passes
    // them back down. React then treats each cell as a *different* component
    // and unmounts/remounts the DOM node, dropping focus after every single
    // character. A component wrapping `CapacityTable` in real `useState` (not
    // a static props object, unlike the other tests in this file) is required
    // to reproduce this: it's specifically the round-trip through a re-render
    // with new `drafts` that triggers the remount.
    function Wrapper() {
      const [drafts, setDrafts] = useState<CapacityTableProps["drafts"]>({});
      return (
        <CapacityTable
          items={[{ id: 1, name: "Développeur", node_id: 1 } as never]}
          pagination={{ total: 1, limit: 20, offset: 0 }}
          onPaginationChange={vi.fn()}
          sort={null}
          onSortChange={vi.fn()}
          search=""
          onSearchChange={vi.fn()}
          isLoading={false}
          drafts={drafts}
          savedByRoleId={new Map()}
          actionBusy={false}
          nodeCodeById={nodeCodeById}
          onDraftChange={(id, draft) => setDrafts((previous) => ({ ...previous, [id]: draft }))}
          onSave={vi.fn()}
        />
      );
    }

    render(<Wrapper />);
    const input = screen.getByLabelText("Nombre de personnes pour Développeur — IT (#1)") as HTMLInputElement;
    input.focus();

    fireEvent.change(input, { target: { value: "3" } });
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("3");

    fireEvent.change(input, { target: { value: "35" } });
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("35");
  });

  it("reflects a renamed node's code in the role label without losing an in-progress edit's value", () => {
    // Regression test for a real bug: `labelFor` was only captured into the
    // memoized `columns` cell closures when `columns` was rebuilt, which used
    // to only happen once (the dependency array was `[]`) -- never on a
    // `nodeCodeById`-only change. Renaming a node's code on the "Nœud" tab
    // would otherwise leave this table showing the role's *old* node code
    // indefinitely.
    //
    // `columns` is still memoized: it only rebuilds on a `nodeCodeById`
    // change (rare, cross-tab), never on a `drafts` change (per-keystroke),
    // so this doesn't reintroduce the focus-loss-per-keystroke bug the
    // memoization exists to prevent (see the still-passing "keeps focus on a
    // capacity input across keystrokes" test above, unaffected by this
    // change). A `nodeCodeById` change does rebuild every column's cell
    // closure -- including the capacity inputs, not just the label -- since
    // `flexRender` treats each cell's function reference as its own React
    // component type, so `CapacityFieldInput` does remount here (mirrors the
    // same accepted trade-off in `role-calendars-table.tsx`'s equivalent
    // rename test, which likewise doesn't assert DOM focus continuity across
    // a rename). What must not regress is the *value*: it's re-seeded from
    // `props.drafts`, which the keystroke already reported upward, so no
    // unsaved edit is silently lost.
    function Wrapper() {
      const [codeById, setCodeById] = useState(new Map([[1, "IT"]]));
      const [drafts, setDrafts] = useState<CapacityTableProps["drafts"]>({});
      return (
        <>
          <button type="button" onClick={() => setCodeById(new Map([[1, "ITSM"]]))}>
            Rename node
          </button>
          <CapacityTable
            items={[{ id: 1, name: "Développeur", node_id: 1 } as never]}
            pagination={{ total: 1, limit: 20, offset: 0 }}
            onPaginationChange={vi.fn()}
            sort={null}
            onSortChange={vi.fn()}
            search=""
            onSearchChange={vi.fn()}
            isLoading={false}
            drafts={drafts}
            savedByRoleId={new Map()}
            actionBusy={false}
            nodeCodeById={codeById}
            onDraftChange={(id, draft) => setDrafts((previous) => ({ ...previous, [id]: draft }))}
            onSave={vi.fn()}
          />
        </>
      );
    }

    render(<Wrapper />);
    expect(screen.getByText("Développeur — IT (#1)")).toBeInTheDocument();
    const input = screen.getByLabelText("Nombre de personnes pour Développeur — IT (#1)") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "3" } });

    fireEvent.click(screen.getByRole("button", { name: "Rename node" }));

    expect(screen.getByText("Développeur — ITSM (#1)")).toBeInTheDocument();
    expect(screen.queryByText("Développeur — IT (#1)")).not.toBeInTheDocument();
    const renamedInput = screen.getByLabelText("Nombre de personnes pour Développeur — ITSM (#1)") as HTMLInputElement;
    expect(renamedInput.value).toBe("3");
  });

  it("freezes pagination, sorting and search while a visible role's draft differs from its saved capacity", () => {
    renderTable({
      drafts: { 1: { personCount: "3.00", availableHours: "3200.00" } },
      savedByRoleId: new Map([[1, { personCount: "2.00", availableHours: "3200.00" }]]),
      pagination: { total: 40, limit: 20, offset: 0 },
    });

    expect(
      screen.getByText("Enregistrez la saisie en cours, ou remettez sa valeur d'origine, avant de changer de page ou de filtrer."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Rechercher un rôle")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Rôle" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Suivant" })).toBeDisabled();
  });

  it("does not freeze navigation when a role's draft matches its saved capacity, even if formatted differently", () => {
    // "2" (freshly typed) vs "2.00" (the saved/API-formatted value) must compare
    // equal numerically -- a naive strict string comparison would wrongly report
    // this role as having an unsaved draft.
    renderTable({
      drafts: { 1: { personCount: "2", availableHours: "3200.00" } },
      savedByRoleId: new Map([[1, { personCount: "2.00", availableHours: "3200.00" }]]),
      pagination: { total: 40, limit: 20, offset: 0 },
    });

    expect(screen.getByLabelText("Rechercher un rôle")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Suivant" })).toBeEnabled();
  });

  it("lifts the freeze once the edited role is no longer visible on the current page", () => {
    // The role with the unsaved draft (#1) has been paginated/searched away from
    // -- `items` no longer contains it. Its draft is untouched in `drafts` (no
    // data is lost, see the comment on `hasUnsavedDraft`), but since it's not
    // *visible* anymore, navigation is no longer blocked.
    renderTable({
      items: [{ id: 2, name: "Autre rôle", node_id: 1 } as never],
      drafts: { 1: { personCount: "3.00", availableHours: "3200.00" } },
      savedByRoleId: new Map([[1, { personCount: "2.00", availableHours: "3200.00" }]]),
      pagination: { total: 40, limit: 20, offset: 0 },
    });

    expect(
      screen.queryByText("Enregistrez la saisie en cours, ou remettez sa valeur d'origine, avant de changer de page ou de filtrer."),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Rechercher un rôle")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Suivant" })).toBeEnabled();
  });

  it("lifts the freeze once a role without any prior saved capacity is saved and its draft matches the new zero-value default", () => {
    // A role with no `RoleCapacity` yet (absent from `savedByRoleId`) falls back
    // to `defaultDraft` ("0.00"/"0.00") on both sides of the comparison -- typing
    // back to that same default value must not read as "still unsaved".
    renderTable({
      drafts: { 1: { personCount: "0.00", availableHours: "0.00" } },
      savedByRoleId: new Map(),
      pagination: { total: 40, limit: 20, offset: 0 },
    });

    expect(screen.getByRole("button", { name: "Suivant" })).toBeEnabled();
  });

  it("keeps the freeze active while a field is cleared for retyping, even against the common 0.00/0.00 saved default", () => {
    // Regression test for a real bug: `Number("")` is `0`, not `NaN`. For a role
    // whose saved capacity is the common "0.00"/"0.00" default (never had a
    // capacity saved yet), a naive numeric comparison would read a blank field
    // (mid-edit, e.g. select-all then retype) as "0 === 0", i.e. matching the
    // saved value, and prematurely lift the freeze while the user is still
    // typing.
    renderTable({
      drafts: { 1: { personCount: "", availableHours: "0.00" } },
      savedByRoleId: new Map(),
      pagination: { total: 40, limit: 20, offset: 0 },
    });

    expect(screen.getByRole("button", { name: "Suivant" })).toBeDisabled();
  });
});
