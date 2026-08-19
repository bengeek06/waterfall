import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RolesPanel } from "./roles-panel";

describe("RolesPanel", () => {
  it("only offers categories attached to labor cost types", () => {
    render(<RolesPanel selectedNode={null} selectedRoles={[]} nodes={[]} categories={[{ id: 1, cost_type_id: 10, accounting_code: "MO-DEV", category_code: null, name: "Développement", is_active: true } as never, { id: 2, cost_type_id: 20, accounting_code: "FO-CABLE", category_code: null, name: "Câbles", is_active: true } as never]} costTypes={[{ id: 10, code: "MO", name: "Main d'œuvre", kind: "labor" } as never, { id: 20, code: "FO", name: "Fourniture", kind: "supply" } as never]} roleCode="" roleName="" roleNodeId="" roleCategoryId="" actionBusy={false} categoryNames={new Map()} onSubmit={(event) => event.preventDefault()} onCodeChange={() => undefined} onNameChange={() => undefined} onNodeChange={() => undefined} onCategoryChange={() => undefined} />);

    expect(screen.getByRole("option", { name: /MO-DEV/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /FO-CABLE/ })).not.toBeInTheDocument();
  });
});