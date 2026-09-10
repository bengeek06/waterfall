"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { EstimateTaskRow, ProjectCostCode, ResourceNode, ResourceRole } from "@/lib/backend";
import { buildOrganizationNodeOptions } from "@/lib/organization-tree";
import { buildAttachableTaskOptions } from "@/lib/estimate-task-options";

export type EstimateRoleAssignmentDialogProps = {
  open: boolean;
  resourceNodes: ResourceNode[];
  nodeId: string;
  onNodeIdChange: (value: string) => void;
  // E12-06/#278: only the roles of the chosen node (and its descendants) -- loaded on demand by
  // the caller (use-estimate-cost-lines.ts's updateRoleAssignmentNodeId) once a node is picked,
  // never the whole referential up front. Empty and disabled until a node is chosen.
  roles: ResourceRole[];
  rolesLoading: boolean;
  roleId: string;
  onRoleIdChange: (value: string) => void;
  // The selected estimate's task rows, filtered down to attachable ones (task_id set) the same
  // way cost-line-form.tsx's own "Tâche" selector is -- see buildAttachableTaskOptions.
  estimateTaskRows: EstimateTaskRow[];
  taskId: string;
  onTaskIdChange: (value: string) => void;
  quantity: string;
  onQuantityChange: (value: string) => void;
  hours: string;
  onHoursChange: (value: string) => void;
  projectCostCodes: ProjectCostCode[];
  costCodeId: string;
  onCostCodeIdChange: (value: string) => void;
  comment: string;
  onCommentChange: (value: string) => void;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: () => void;
};

// E12-06/#278: "Ajouter une ligne MO" dialog, launched from the Devis tab -- creates an
// EstimateRoleAssignment attached to a task of the selected (draft) estimate. Modeled after
// estimate-milestone-template-dialog.tsx for the modal/busy/error pattern. `task_id`/`role_id`
// are only ever set here: EstimateRoleAssignmentUpdate has no field for either (immutable once
// created, see lib/backend.ts's own doc comment) -- editing an existing row happens inline in
// cost-lines-table.tsx instead (quantity/hours only), not by reopening this dialog.
export function EstimateRoleAssignmentDialog({
  open,
  resourceNodes,
  nodeId,
  onNodeIdChange,
  roles,
  rolesLoading,
  roleId,
  onRoleIdChange,
  estimateTaskRows,
  taskId,
  onTaskIdChange,
  quantity,
  onQuantityChange,
  hours,
  onHoursChange,
  projectCostCodes,
  costCodeId,
  onCostCodeIdChange,
  comment,
  onCommentChange,
  busy,
  error,
  onClose,
  onSubmit,
}: EstimateRoleAssignmentDialogProps) {
  const nodeOptions = buildOrganizationNodeOptions(resourceNodes);
  const taskOptions = buildAttachableTaskOptions(estimateTaskRows);

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Ajouter une ligne MO</DialogTitle>
          <DialogDescription>
            Affecte un rôle de la ressource organisationnelle à une tâche du devis courant.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="role-assignment-node" className="text-sm font-medium">
              Nœud organisationnel
            </label>
            <select
              id="role-assignment-node"
              aria-label="Nœud organisationnel"
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
              value={nodeId}
              onChange={(event) => onNodeIdChange(event.target.value)}
            >
              <option value="">Choisir...</option>
              {nodeOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {"  ".repeat(option.depth)}
                  {option.code} - {option.name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="role-assignment-role" className="text-sm font-medium">
              Rôle
            </label>
            <select
              id="role-assignment-role"
              aria-label="Rôle"
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
              value={roleId}
              disabled={!nodeId || rolesLoading}
              onChange={(event) => onRoleIdChange(event.target.value)}
            >
              <option value="">{rolesLoading ? "Chargement..." : "Choisir..."}</option>
              {roles.map((role) => (
                <option key={role.id} value={role.id}>
                  {role.name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="role-assignment-task" className="text-sm font-medium">
              Tâche
            </label>
            <select
              id="role-assignment-task"
              aria-label="Tâche"
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
              value={taskId}
              onChange={(event) => onTaskIdChange(event.target.value)}
            >
              <option value="">Choisir...</option>
              {taskOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="role-assignment-quantity" className="text-sm font-medium">
              Quantité
            </label>
            <Input
              id="role-assignment-quantity"
              aria-label="Quantité"
              type="number"
              min="0.01"
              step="0.01"
              required
              value={quantity}
              onChange={(event) => onQuantityChange(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="role-assignment-hours" className="text-sm font-medium">
              Heures
            </label>
            <Input
              id="role-assignment-hours"
              aria-label="Heures"
              type="number"
              min="0"
              step="0.01"
              value={hours}
              onChange={(event) => onHoursChange(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="role-assignment-cost-code" className="text-sm font-medium">
              Code d&apos;imputation
            </label>
            <select
              id="role-assignment-cost-code"
              aria-label="Code d'imputation"
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
              value={costCodeId}
              onChange={(event) => onCostCodeIdChange(event.target.value)}
            >
              <option value="">Aucun</option>
              {projectCostCodes.map((code) => (
                <option key={code.id} value={code.id}>
                  {code.code} - {code.name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="role-assignment-comment" className="text-sm font-medium">
              Commentaire
            </label>
            <Input
              id="role-assignment-comment"
              aria-label="Commentaire"
              value={comment}
              onChange={(event) => onCommentChange(event.target.value)}
            />
          </div>
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Annuler
          </Button>
          <Button type="button" disabled={busy} onClick={onSubmit}>
            Ajouter
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
