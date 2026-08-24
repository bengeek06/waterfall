import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CostCategoriesTable } from "./cost-categories-table";

describe("CostCategoriesTable", () => {
  it("renders active cost types and existing category actions", () => {
    render(
      <CostCategoriesTable
        items={[{ id: 1, cost_type_id: 1, accounting_code: "601", category_code: "MAT", name: "Matériel", is_active: true } as never]}
        types={[{ id: 1, code: "SUP", name: "Fourniture", kind: "supply", is_active: true } as never]}
        typeId=""
        accountingCode=""
        categoryCode=""
        name=""
        draft={{ code: "", name: "", accountingCode: "" }}
        editingId={null}
        busy={false}
        onSubmit={(event) => event.preventDefault()}
        onTypeChange={vi.fn()}
        onAccountingCodeChange={vi.fn()}
        onCategoryCodeChange={vi.fn()}
        onNameChange={vi.fn()}
        onStartEdit={vi.fn()}
        onDraftChange={vi.fn()}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByRole("option", { name: "SUP - Fourniture" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Modifier" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Désactiver" })).toBeInTheDocument();
  });
});
