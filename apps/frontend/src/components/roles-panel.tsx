"use client";

import type { FormEventHandler } from "react";
import type { CostCategory, CostType, ResourceNode, ResourceRole } from "@/lib/backend";

type RolesPanelProps = {
  selectedNode: ResourceNode | null;
  selectedRoles: ResourceRole[];
  nodes: ResourceNode[];
  categories: CostCategory[];
  costTypes: CostType[];
  roleCode: string;
  roleName: string;
  roleNodeId: string;
  roleCategoryId: string;
  actionBusy: boolean;
  categoryNames: Map<number, string | null>;
  onSubmit: FormEventHandler<HTMLFormElement>;
  onCodeChange: (value: string) => void;
  onNameChange: (value: string) => void;
  onNodeChange: (value: string) => void;
  onCategoryChange: (value: string) => void;
};

export function RolesPanel(props: RolesPanelProps) {
  const laborCategories = props.categories.filter((category) => category.is_active && props.costTypes.some((type) => type.id === category.cost_type_id && type.kind === "labor"));

  return (
    <section className="panel panel-stack">
      <h2>Rôles {props.selectedNode ? `de ${props.selectedNode.name}` : ""}</h2>
      <form onSubmit={props.onSubmit}>
        <div className="field"><label htmlFor="role-code">Code</label><input id="role-code" value={props.roleCode} onChange={(event) => props.onCodeChange(event.target.value)} required /></div>
        <div className="field"><label htmlFor="role-name">Nom</label><input id="role-name" value={props.roleName} onChange={(event) => props.onNameChange(event.target.value)} required /></div>
        <div className="field"><label htmlFor="role-node">Nœud</label><select id="role-node" value={props.roleNodeId} onChange={(event) => props.onNodeChange(event.target.value)} required><option value="">Sélectionner</option>{props.nodes.map((node) => <option key={node.id} value={node.id}>{node.code} - {node.name}</option>)}</select></div>
        <div className="field"><label htmlFor="role-category">Code comptable</label><select id="role-category" value={props.roleCategoryId} onChange={(event) => props.onCategoryChange(event.target.value)} required><option value="">Sélectionner</option>{laborCategories.map((category) => <option key={category.id} value={category.id}>{category.accounting_code} - {category.name}</option>)}</select></div>
        <button className="btn btn-primary" disabled={props.actionBusy} type="submit">Ajouter</button>
      </form>
      <ul className="resource-list">{props.selectedRoles.map((role) => <li key={role.id}><strong>{role.code}</strong> {role.name}<span>{props.categoryNames.get(role.cost_category_id) ?? "?"}</span></li>)}</ul>
    </section>
  );
}
