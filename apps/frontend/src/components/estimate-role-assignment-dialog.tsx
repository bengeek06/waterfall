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
import { buildAttachableTaskOptions } from "@/lib/estimate-task-options";

export type EstimateRoleAssignmentDialogProps = {
  open: boolean;
  resourceNodes: ResourceNode[];
  // E12-10/#292: two-level department cascade (replaces the single "Nœud organisationnel"
  // selector) -- "Dpt 1er niveau" only ever lists root nodes (`parent_id === null`), "Dpt 2eme
  // niveau" only that root's own direct children (empty when it has none). The role list below is
  // fetched against whichever of the two is the effective/deepest one chosen so far -- see
  // use-estimate-cost-lines.ts's updateRoleAssignmentDept1Id/updateRoleAssignmentDept2Id.
  dept1Id: string;
  onDept1IdChange: (value: string) => void;
  dept2Id: string;
  onDept2IdChange: (value: string) => void;
  // E12-06/#278: only the roles of the chosen department (and its descendants) -- loaded on
  // demand by the caller once a department is picked, never the whole referential up front.
  // Empty and disabled until a department is chosen.
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
  dept1Id,
  onDept1IdChange,
  dept2Id,
  onDept2IdChange,
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
  const taskOptions = buildAttachableTaskOptions(estimateTaskRows);
  const dept1Options = resourceNodes.filter((node) => node.parent_id == null);
  const dept2Options = resourceNodes.filter((node) => dept1Id !== "" && String(node.parent_id) === dept1Id);

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
            <label htmlFor="role-assignment-dept1" className="text-sm font-medium">
              Dpt 1er niveau
            </label>
            <select
              id="role-assignment-dept1"
              aria-label="Dpt 1er niveau"
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
              value={dept1Id}
              onChange={(event) => onDept1IdChange(event.target.value)}
            >
              <option value="">Choisir...</option>
              {dept1Options.map((node) => (
                <option key={node.id} value={node.id}>
                  {node.code} - {node.name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="role-assignment-dept2" className="text-sm font-medium">
              Dpt 2eme niveau
            </label>
            <select
              id="role-assignment-dept2"
              aria-label="Dpt 2eme niveau"
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
              value={dept2Id}
              disabled={!dept1Id || dept2Options.length === 0}
              onChange={(event) => onDept2IdChange(event.target.value)}
            >
              <option value="">Choisir...</option>
              {dept2Options.map((node) => (
                <option key={node.id} value={node.id}>
                  {node.code} - {node.name}
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
              disabled={!dept1Id || rolesLoading}
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
