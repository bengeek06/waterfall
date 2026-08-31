"use client";

import type { FormEventHandler } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { CostCategory, CostType, ResourceNode, ResourceRole } from "@/lib/backend";

type RolesPanelProps = {
  selectedNode: ResourceNode | null;
  selectedRoles: ResourceRole[];
  nodes: ResourceNode[];
  categories: CostCategory[];
  costTypes: CostType[];
  roleName: string;
  roleNodeId: string;
  roleCategoryId: string;
  actionBusy: boolean;
  categoryNames: Map<number, string | null>;
  onSubmit: FormEventHandler<HTMLFormElement>;
  onNameChange: (value: string) => void;
  onNodeChange: (value: string) => void;
  onCategoryChange: (value: string) => void;
};

export function RolesPanel(props: RolesPanelProps) {
  const laborCategories = props.categories.filter((category) => category.is_active && props.costTypes.some((type) => type.id === category.cost_type_id && type.kind === "labor"));

  return (
    <Card className="mt-4">
      <CardHeader><CardTitle>Rôles {props.selectedNode ? `de ${props.selectedNode.name}` : ""}</CardTitle></CardHeader>
      <CardContent className="grid gap-6">
        <form onSubmit={props.onSubmit} className="grid gap-4 sm:grid-cols-2">
          <div className="grid gap-2"><Label htmlFor="role-name">Nom</Label><Input id="role-name" value={props.roleName} onChange={(event) => props.onNameChange(event.target.value)} required /></div>
          <div className="grid gap-2"><Label htmlFor="role-node">Nœud</Label><select id="role-node" className="h-8 rounded-md border border-input bg-background px-2 text-sm" value={props.roleNodeId} onChange={(event) => props.onNodeChange(event.target.value)} required><option value="">Sélectionner</option>{props.nodes.map((node) => <option key={node.id} value={node.id}>{node.code} - {node.name}</option>)}</select></div>
          <div className="grid gap-2"><Label htmlFor="role-category">Code comptable</Label><select id="role-category" className="h-8 rounded-md border border-input bg-background px-2 text-sm" value={props.roleCategoryId} onChange={(event) => props.onCategoryChange(event.target.value)} required><option value="">Sélectionner</option>{laborCategories.map((category) => <option key={category.id} value={category.id}>{category.accounting_code} - {category.name}</option>)}</select></div>
          <Button className="sm:col-span-2 sm:w-fit" disabled={props.actionBusy} type="submit">Ajouter</Button>
        </form>
        {props.selectedRoles.length ? <ul className="grid divide-y rounded-md border">{props.selectedRoles.map((role) => <li key={role.id} className="flex flex-wrap items-center gap-2 px-3 py-2"><span>{role.name} (#{role.id})</span><Badge variant="outline">{props.categoryNames.get(role.cost_category_id) ?? "?"}</Badge></li>)}</ul> : null}
      </CardContent>
    </Card>
  );
}
