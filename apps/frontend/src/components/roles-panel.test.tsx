import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RolesPanel } from "./roles-panel";

describe("RolesPanel", () => {
  it("only offers categories attached to labor cost types", () => {
    render(<RolesPanel selectedNode={null} selectedRoles={[]} nodes={[]} categories={[{ id: 1, cost_type_id: 10, accounting_code: "MO-DEV", category_code: null, name: "Développement", is_active: true } as never, { id: 2, cost_type_id: 20, accounting_code: "FO-CABLE", category_code: null, name: "Câbles", is_active: true } as never]} costTypes={[{ id: 10, code: "MO", name: "Main d'œuvre", kind: "labor" } as never, { id: 20, code: "FO", name: "Fourniture", kind: "supply" } as never]} roleName="" roleNodeId="" roleCategoryId="" actionBusy={false} categoryNames={new Map()} onSubmit={(event) => event.preventDefault()} onNameChange={() => undefined} onNodeChange={() => undefined} onCategoryChange={() => undefined} />);

    expect(screen.getByRole("option", { name: /MO-DEV/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /FO-CABLE/ })).not.toBeInTheDocument();
  });

  it("disambiguates two roles that share the same name and category within the same node using role id", () => {
    render(
      <RolesPanel
        selectedNode={{ id: 1, code: "IT", name: "Informatique" } as never}
        selectedRoles={[
          { id: 5, name: "Développeur", cost_category_id: 1 } as never,
          { id: 6, name: "Développeur", cost_category_id: 1 } as never,
        ]}
        nodes={[]}
        categories={[]}
        costTypes={[]}
        roleName=""
        roleNodeId=""
        roleCategoryId=""
        actionBusy={false}
        categoryNames={new Map([[1, "MO-DEV"]])}
        onSubmit={(event) => event.preventDefault()}
        onNameChange={() => undefined}
        onNodeChange={() => undefined}
        onCategoryChange={() => undefined}
      />,
    );

    // Both roles share the same name and the same accounting category, so within
    // this single node's list only the trailing "(#<role.id>)" discriminant can
    // tell them apart. If that suffix were dropped, both list items would render
    // identical text ("Développeur" + the "MO-DEV" badge) and would be
    // indistinguishable from one another.
    expect(screen.getByText("Développeur (#5)")).toBeInTheDocument();
    expect(screen.getByText("Développeur (#6)")).toBeInTheDocument();
  });
});