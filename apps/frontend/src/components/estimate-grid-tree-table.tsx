"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PlanningTreeToolbar } from "@/components/planning-tree-toolbar";
import { useEstimateGridDrafts } from "@/hooks/use-estimate-grid-drafts";
import { useEstimateGridSelection } from "@/hooks/use-estimate-grid-selection";
import type {
  CostCategory,
  CostRate,
  EstimateCostLine,
  EstimateRoleAssignment,
  EstimateTaskRow,
  ResourceNode,
  ResourceRole,
  Task,
} from "@/lib/backend";
import { computeIndicativeLaborCost, resolveIndicativeHourlyRate, resolveRoleAssignmentYear } from "@/lib/estimate-role-assignment";
import {
  buildEstimateGridTreeRows,
  computeEstimateGridRowTotals,
  type EstimateGridLaborRow,
  type EstimateGridLineRow,
  type EstimateGridTreeRow,
} from "@/lib/estimate-grid-tree";
import { computeGridIndentCommand, computeGridOutdentCommand, computeGridReorderCommand, type EstimateGridMoveCommand } from "@/lib/estimate-grid-move";

export type EstimateGridTreeTableProps = {
  taskRows: EstimateTaskRow[];
  costLines: EstimateCostLine[];
  roleAssignments: EstimateRoleAssignment[];
  /** Any value identifying the loaded estimate version; changing it resets local expand/selection/draft state. */
  versionKey: number | string | null;
  canEditEstimate: boolean;
  mutationBusy: boolean;
  /** Active-only category referential, feeding the "Type" column's non-MO `<select>` options. */
  costCategories: CostCategory[];
  /** Full (including inactive) category referential, used only to resolve an existing line's
   * category name when it isn't in `costCategories` anymore (a category deactivated after the
   * line was created must still show its real name, not silently fall back to nothing). */
  allCostCategories: CostCategory[];
  resourceNodes: ResourceNode[];
  resourceRoles: ResourceRole[];
  costRates: CostRate[];
  planningTasks: Task[];
  onMove?: (command: EstimateGridMoveCommand) => void;
  onRenameTask?: (taskUid: number, name: string) => Promise<boolean>;
  onUpdateCostLine?: (
    lineId: number,
    payload: { label?: string; quantity?: number; unit_cost?: number; cost_category_id?: number },
  ) => Promise<boolean>;
  onUpdateRoleAssignment?: (id: number, payload: { quantity?: number; hours?: number }) => Promise<boolean>;
  // Bulk cost-code assignment (E6-03) stays scoped to non-labor cost lines only, unchanged from
  // the table this component replaces.
  selectedCostLineIds: Set<number>;
  onSelectedCostLineIdsChange: (next: Set<number>) => void;
  bulkAssignBusy: boolean;
  onOpenMilestoneDialog: (line: EstimateCostLine) => void;
  milestoneTaskIds: Set<number>;
  onRequestDeleteCostLine: (line: EstimateCostLine) => void;
  onRequestDeleteRoleAssignment: (assignment: EstimateRoleAssignment) => void;
  // E12-11/#293: right-click context menu's "Ajouter ressource" action on a labor row -- creates
  // a new, entirely blank EstimateRoleAssignment attached to the same task as `assignment`
  // (never a copy of its own values). Disabled by the grid itself for a root labor row
  // (`assignment.task_id == null`, the E12-07 case) -- see renderContextMenuItems' own comment.
  onAddRoleAssignmentForRow: (assignment: EstimateRoleAssignment) => void;
};

const COLUMN_HEADERS = [
  "Numéro",
  "Libellé",
  "Type",
  "Dpt 1er niveau",
  "Dpt 2eme niveau",
  "Rôle",
  "Qté",
  "Heures",
  "Débours",
  "Taux horaire",
  "PRU",
] as const;

function resolveCategoryName(categoryId: number, allCostCategories: CostCategory[]): string {
  return allCostCategories.find((category) => category.id === categoryId)?.name ?? "-";
}

// The "Dpt 1er niveau"/"Dpt 2eme niveau" columns are read-only for an already-created labor row
// (a role's `node_id` is immutable, see EstimateRoleAssignmentUpdate's own doc comment) -- unlike
// resolveOrganizationPath's single joined string (used elsewhere for a breadcrumb-style display),
// this grid needs the top two ancestor *names* split across two dedicated columns.
function resolveDeptColumns(nodeId: number | null | undefined, nodes: ResourceNode[]): [string, string] {
  if (nodeId == null) {
    return ["-", "-"];
  }
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const segments: string[] = [];
  const seen = new Set<number>();
  let current = byId.get(nodeId);
  while (current && !seen.has(current.id)) {
    segments.unshift(current.name);
    seen.add(current.id);
    current = current.parent_id != null ? byId.get(current.parent_id) : undefined;
  }
  return [segments[0] ?? "-", segments[1] ?? "-"];
}

function formatLocked(value: number | null | undefined): string {
  return value == null ? "—" : String(value);
}

// E12-10/#292: replaces cost-lines-table.tsx's fixed task-grouping + single-row "Modifier/Sauver"
// edit mode with a real tree table (row_number/uid/parent_uid/position, E12-07..E12-09) where
// every cell commits itself independently on blur/Enter -- see use-estimate-grid-drafts.ts.
// Structurally modeled after PlanningTreeTable (collapse/expand, click-to-select, Indenter/
// Désindenter/Monter/Descendre toolbar): see lib/estimate-grid-move.ts for why this grid's own
// move semantics deliberately differ from planning-tree.ts's in a couple of spots.
export function EstimateGridTreeTable({
  taskRows,
  costLines,
  roleAssignments,
  versionKey,
  canEditEstimate,
  mutationBusy,
  costCategories,
  allCostCategories,
  resourceNodes,
  resourceRoles,
  costRates,
  planningTasks,
  onMove,
  onRenameTask,
  onUpdateCostLine,
  onUpdateRoleAssignment,
  selectedCostLineIds,
  onSelectedCostLineIdsChange,
  bulkAssignBusy,
  onOpenMilestoneDialog,
  milestoneTaskIds,
  onRequestDeleteCostLine,
  onRequestDeleteRoleAssignment,
  onAddRoleAssignmentForRow,
}: EstimateGridTreeTableProps) {
  const [renderedVersionKey, setRenderedVersionKey] = useState(versionKey);

  const rows = buildEstimateGridTreeRows(taskRows, costLines, roleAssignments);
  const totalsByUid = computeEstimateGridRowTotals(rows, costRates, planningTasks);
  const resourceRoleById = new Map(resourceRoles.map((role) => [role.id, role]));

  const selection = useEstimateGridSelection(rows);
  const drafts = useEstimateGridDrafts({ mutationBusy, onRenameTask, onUpdateCostLine, onUpdateRoleAssignment });

  // A different estimate version must never reuse another version's expand/selection/draft state
  // -- same deliberate synchronous render-body reset as PlanningTreeTable's own versionKey guard
  // (must land within the same render as the versionKey prop change, see that component's own
  // doc comment for why this can't be a useEffect).
  if (versionKey !== renderedVersionKey) {
    setRenderedVersionKey(versionKey);
    selection.reset();
    drafts.reset();
  }

  const indentCommand = computeGridIndentCommand(rows, selection.selectedUids);
  const outdentCommand = computeGridOutdentCommand(rows, selection.selectedUids);
  const moveUpCommand = computeGridReorderCommand(rows, selection.selectedUids, "up");
  const moveDownCommand = computeGridReorderCommand(rows, selection.selectedUids, "down");

  function dispatchMove(command: EstimateGridMoveCommand | null) {
    if (command) {
      onMove?.(command);
    }
  }

  function toggleCostLine(lineId: number, checked: boolean) {
    const next = new Set(selectedCostLineIds);
    if (checked) {
      next.add(lineId);
    } else {
      next.delete(lineId);
    }
    onSelectedCostLineIdsChange(next);
  }

  function renderLabelCell(row: EstimateGridTreeRow) {
    // A task row with no `task_uid` (see use-estimate-grid-drafts.ts's own commitLabel doc
    // comment) has no valid target for the rename PATCH at all -- never rendered as editable,
    // rather than letting the user type into a field whose blur-commit silently does nothing.
    const taskRenameLocked = row.kind === "task" && row.taskRow.task_uid == null;
    const editable = row.kind !== "labor" && !taskRenameLocked && canEditEstimate;
    const content = editable ? (
      <Input
        aria-label={`Libellé de ${row.kind === "task" ? row.taskRow.task_name : row.line.label}`}
        value={drafts.draftFor(row).label}
        onChange={(event) => drafts.updateDraftField(row, "label", event.target.value)}
        onBlur={() => void drafts.commitLabel(row)}
        onKeyDown={drafts.onFieldKeyDown}
        disabled={mutationBusy}
      />
    ) : (
      <span title={taskRenameLocked ? "Cette tâche n'a pas d'identifiant projet valide et ne peut pas être renommée depuis le devis." : undefined}>
        {row.kind === "task" ? row.taskRow.task_name : row.kind === "line" ? row.line.label : row.assignment.role_name}
      </span>
    );
    return (
      <div className="flex min-w-0 items-center gap-1" style={{ paddingLeft: `${row.depth * 1.25}rem` }}>
        {row.hasChildren && row.uid != null ? (
          <button
            type="button"
            aria-label={selection.collapsedUids.has(row.uid) ? "Déplier" : "Replier"}
            className="flex size-6 shrink-0 items-center justify-center"
            onClick={(event) => {
              event.stopPropagation();
              selection.toggleCollapsed(row.uid as number);
            }}
          >
            {selection.collapsedUids.has(row.uid) ? <ChevronRight aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
          </button>
        ) : (
          <span className="size-6 shrink-0" />
        )}
        <div className="min-w-0 flex-1">{content}</div>
      </div>
    );
  }

  function renderTypeCell(row: EstimateGridTreeRow) {
    if (row.kind === "task") {
      return "-";
    }
    if (row.kind === "labor") {
      return "MO";
    }
    if (!canEditEstimate || !onUpdateCostLine) {
      return resolveCategoryName(row.line.cost_category_id, allCostCategories);
    }
    const currentInList = costCategories.some((category) => category.id === row.line.cost_category_id);
    return (
      <select
        aria-label={`Type de ${row.line.label}`}
        className="h-8 rounded-md border border-input bg-background px-2 text-sm"
        value={row.line.cost_category_id}
        disabled={mutationBusy}
        onChange={(event) => void onUpdateCostLine(row.line.id, { cost_category_id: Number(event.target.value) })}
      >
        {!currentInList ? (
          <option value={row.line.cost_category_id}>{resolveCategoryName(row.line.cost_category_id, allCostCategories)}</option>
        ) : null}
        {costCategories.map((category) => (
          <option key={category.id} value={category.id}>
            {category.name}
          </option>
        ))}
      </select>
    );
  }

  function renderQuantityCell(row: EstimateGridTreeRow) {
    if (row.kind === "task") {
      return row.hasChildren && row.uid != null ? formatLocked(totalsByUid.get(row.uid)?.quantity) : "-";
    }
    const current = row.kind === "line" ? row.line.quantity : row.assignment.quantity;
    if (!canEditEstimate) {
      return current;
    }
    return (
      <Input
        aria-label={`Qté de ${row.kind === "line" ? row.line.label : row.assignment.role_name}`}
        type="number"
        min="0.01"
        step="0.01"
        value={drafts.draftFor(row).quantity}
        onChange={(event) => drafts.updateDraftField(row, "quantity", event.target.value)}
        onBlur={() => void drafts.commitQuantity(row)}
        onKeyDown={drafts.onFieldKeyDown}
        disabled={mutationBusy}
      />
    );
  }

  function renderHoursCell(row: EstimateGridTreeRow) {
    if (row.kind === "task") {
      return row.hasChildren && row.uid != null ? formatLocked(totalsByUid.get(row.uid)?.hours) : "-";
    }
    if (row.kind === "line") {
      return "-";
    }
    if (!canEditEstimate) {
      return row.assignment.hours;
    }
    return (
      <Input
        aria-label={`Heures de ${row.assignment.role_name}`}
        type="number"
        min="0"
        step="0.01"
        value={drafts.draftFor(row).hours}
        onChange={(event) => drafts.updateDraftField(row, "hours", event.target.value)}
        onBlur={() => void drafts.commitHours(row)}
        onKeyDown={drafts.onFieldKeyDown}
        disabled={mutationBusy}
      />
    );
  }

  function renderDeboursCell(row: EstimateGridTreeRow) {
    if (row.kind === "task") {
      return row.hasChildren && row.uid != null ? formatLocked(totalsByUid.get(row.uid)?.debours) : "-";
    }
    if (row.kind === "labor") {
      return "-";
    }
    if (!canEditEstimate) {
      return row.line.unit_cost;
    }
    return (
      <Input
        aria-label={`Débours de ${row.line.label}`}
        type="number"
        min="0"
        step="0.01"
        value={drafts.draftFor(row).unitCost}
        onChange={(event) => drafts.updateDraftField(row, "unitCost", event.target.value)}
        onBlur={() => void drafts.commitUnitCost(row)}
        onKeyDown={drafts.onFieldKeyDown}
        disabled={mutationBusy}
      />
    );
  }

  function renderHourlyRateCell(row: EstimateGridTreeRow) {
    if (row.kind !== "labor") {
      return "-";
    }
    const year = resolveRoleAssignmentYear(row.assignment.task_id, planningTasks);
    const hourlyRate = resolveIndicativeHourlyRate(row.assignment.cost_category_id, year, costRates);
    return hourlyRate ? hourlyRate.hourly_rate : "—";
  }

  function renderPruCell(row: EstimateGridTreeRow) {
    if (row.kind === "task") {
      return row.hasChildren && row.uid != null ? formatLocked(totalsByUid.get(row.uid)?.pru) : "-";
    }
    if (row.kind === "line") {
      return row.line.purchase_cost;
    }
    const year = resolveRoleAssignmentYear(row.assignment.task_id, planningTasks);
    const hourlyRate = resolveIndicativeHourlyRate(row.assignment.cost_category_id, year, costRates);
    const laborCost = computeIndicativeLaborCost(row.assignment, hourlyRate);
    return laborCost == null ? "—" : laborCost;
  }

  function renderDeptCells(row: EstimateGridTreeRow) {
    if (row.kind !== "labor") {
      return ["-", "-"] as const;
    }
    const role = resourceRoleById.get(row.assignment.role_id);
    return resolveDeptColumns(role?.node_id, resourceNodes);
  }

  function renderRoleCell(row: EstimateGridTreeRow) {
    return row.kind === "labor" ? row.assignment.role_name : "-";
  }

  function renderActionsCell(row: EstimateGridTreeRow) {
    if (row.kind === "task") {
      return null;
    }
    if (row.kind === "line") {
      // E12-11/#293: "Gabarit de jalons" used to be a dedicated button here -- it's now only
      // reachable from this row's right-click context menu (see renderContextMenuItems below),
      // which calls the exact same onOpenMilestoneDialog prop, never a parallel implementation.
      return (
        <Button size="sm" variant="destructive" type="button" disabled={mutationBusy} onClick={() => onRequestDeleteCostLine(row.line)}>
          Supprimer
        </Button>
      );
    }
    return (
      <Button size="sm" variant="destructive" type="button" disabled={mutationBusy} onClick={() => onRequestDeleteRoleAssignment(row.assignment)}>
        Supprimer
      </Button>
    );
  }

  // E12-11/#293: right-click context-menu items for a "line"/"labor" row -- a "task" row never
  // gets a menu at all (see the row-mapping loop below, which only wraps these two kinds in a
  // ContextMenu). "Ajouter ressource" only ever shows on a labor row, "Gabarit de jalons" only
  // ever shows on a non-MO cost-line row -- never both, mirroring the acceptance criteria's own
  // "the menu must not offer the other kind's action" requirement.
  function renderContextMenuItems(row: EstimateGridLineRow | EstimateGridLaborRow) {
    if (row.kind === "line") {
      const attachedToMilestoneTask = row.line.task_id != null && milestoneTaskIds.has(row.line.task_id);
      return (
        <ContextMenuItem
          disabled={mutationBusy || attachedToMilestoneTask}
          title={attachedToMilestoneTask ? "Cette ligne est rattachée à une tâche-jalon, qui ne peut pas recevoir de sous-tâches." : undefined}
          onClick={() => onOpenMilestoneDialog(row.line)}
        >
          Gabarit de jalons
        </ContextMenuItem>
      );
    }
    // A root labor row (no task ancestor, `task_id: null` -- the E12-07 case) can never be
    // duplicated: EstimateRoleAssignmentCreate.task_id is required, so there is no task to attach
    // a new blank row to. Disabled with an explanatory title rather than hidden outright, so the
    // user understands why rather than wondering if the row was skipped by mistake.
    const hasTaskAncestor = row.assignment.task_id != null;
    return (
      <ContextMenuItem
        disabled={mutationBusy || !hasTaskAncestor}
        title={!hasTaskAncestor ? "Cette ligne MO n'est rattachée à aucune tâche : impossible d'y ajouter une ressource." : undefined}
        onClick={() => onAddRoleAssignmentForRow(row.assignment)}
      >
        Ajouter ressource
      </ContextMenuItem>
    );
  }

  const columnCount = COLUMN_HEADERS.length + (canEditEstimate ? 2 : 0);

  return (
    <div>
      <PlanningTreeToolbar
        visible={canEditEstimate}
        showMoveActions={Boolean(onMove)}
        indentDisabled={!indentCommand || mutationBusy}
        outdentDisabled={!outdentCommand || mutationBusy}
        moveUpDisabled={!moveUpCommand || mutationBusy}
        moveDownDisabled={!moveDownCommand || mutationBusy}
        onIndent={() => dispatchMove(indentCommand)}
        onOutdent={() => dispatchMove(outdentCommand)}
        onMoveUp={() => dispatchMove(moveUpCommand)}
        onMoveDown={() => dispatchMove(moveDownCommand)}
        showCreateAction={false}
        createDisabled
        onCreateTask={() => {}}
        showDeleteAction={false}
        deleteDisabled
        onDeleteSelection={() => {}}
      />
      <Table>
        <TableHeader>
          <TableRow>
            {canEditEstimate ? <TableHead /> : null}
            {COLUMN_HEADERS.map((label) => (
              <TableHead key={label}>{label}</TableHead>
            ))}
            {canEditEstimate ? <TableHead>Action</TableHead> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {selection.visibleRows.map((row) => {
            const selected = row.uid != null && selection.selectedUids.has(row.uid);
            const [dept1, dept2] = renderDeptCells(row);
            const key = row.kind === "task" ? `task-${row.taskRow.id}` : row.kind === "line" ? `line-${row.line.id}` : `labor-${row.assignment.id}`;
            const rowElement = (
              <TableRow
                key={key}
                data-state={selected ? "selected" : undefined}
                aria-selected={selected}
                className={row.kind === "task" ? undefined : "cursor-pointer"}
                onClick={(event) => selection.selectRow(row, event)}
              >
                {canEditEstimate ? (
                  <TableCell>
                    {row.kind === "line" ? (
                      <Checkbox
                        aria-label={`Sélectionner ${row.line.label}`}
                        checked={selectedCostLineIds.has(row.line.id)}
                        disabled={bulkAssignBusy}
                        onCheckedChange={(checked) => toggleCostLine(row.line.id, Boolean(checked))}
                      />
                    ) : null}
                  </TableCell>
                ) : null}
                <TableCell>{row.rowNumber ?? "-"}</TableCell>
                <TableCell className="overflow-hidden">{renderLabelCell(row)}</TableCell>
                <TableCell>{renderTypeCell(row)}</TableCell>
                <TableCell>{dept1}</TableCell>
                <TableCell>{dept2}</TableCell>
                <TableCell>{renderRoleCell(row)}</TableCell>
                <TableCell>{renderQuantityCell(row)}</TableCell>
                <TableCell>{renderHoursCell(row)}</TableCell>
                <TableCell>{renderDeboursCell(row)}</TableCell>
                <TableCell>{renderHourlyRateCell(row)}</TableCell>
                <TableCell>{renderPruCell(row)}</TableCell>
                {canEditEstimate ? <TableCell>{renderActionsCell(row)}</TableCell> : null}
              </TableRow>
            );

            // E12-11/#293: right-click context menu -- only ever on a "line"/"labor" row (never
            // a "task" row, see this issue's own spec) and only while the estimate is actually
            // editable (mirrors the Action column itself, also `canEditEstimate`-gated above):
            // there is nothing this menu could ever do on a read-only estimate version.
            if (canEditEstimate && row.kind !== "task") {
              return (
                <ContextMenu key={key}>
                  <ContextMenuTrigger render={rowElement} />
                  <ContextMenuContent>{renderContextMenuItems(row)}</ContextMenuContent>
                </ContextMenu>
              );
            }
            return rowElement;
          })}
          {!selection.visibleRows.length ? (
            <TableRow>
              <TableCell colSpan={columnCount} className="text-muted-foreground">
                Aucune ligne de coût.
              </TableCell>
            </TableRow>
          ) : null}
        </TableBody>
      </Table>
    </div>
  );
}
