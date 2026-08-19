import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OrganizationTree, type OrganizationRow } from "./organization-tree";

const rows: OrganizationRow[] = [{ id: 1, code: "IT", name: "Informatique", parent_id: null, is_active: true, depth: 0, hasChildren: false, created_at: "", updated_at: "" }];

describe("OrganizationTree", () => {
  it("selects and edits a node", () => {
    const onSelect = vi.fn();
    const onStartEdit = vi.fn();

    render(<OrganizationTree rows={rows} selectedNodeId={null} collapsedNodeIds={new Set()} editingNodeId={null} nodeCode="" nodeName="" nodeParentId="" nodeDraft={{ code: "", name: "", parentId: "" }} actionBusy={false} onAdd={vi.fn()} onSelect={onSelect} onToggleCollapsed={vi.fn()} onStartEdit={onStartEdit} onDraftChange={vi.fn()} onSave={vi.fn()} onCancel={vi.fn()} onRemove={vi.fn()} onNodeChange={vi.fn()} />);

    fireEvent.click(screen.getByText("Informatique"));
    fireEvent.click(screen.getByRole("button", { name: "Modifier" }));

    expect(onSelect).toHaveBeenCalledWith(1);
    expect(onStartEdit).toHaveBeenCalledWith(rows[0]);
  });
});