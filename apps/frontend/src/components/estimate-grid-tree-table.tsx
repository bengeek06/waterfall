"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { BulkCostCodeAssignmentBar } from "@/components/bulk-cost-code-assignment-bar";
import { EstimateGridCostCells } from "@/components/estimate-grid-cost-cells";
import { PlanningCreateTaskDialog } from "@/components/planning-create-task-dialog";
import { PlanningDeleteDialog } from "@/components/planning-delete-dialog";
import { PlanningTreeToolbar } from "@/components/planning-tree-toolbar";
import { TreeTableColumnResizeHandle } from "@/components/tree-table-column-resize-handle";
import { useEstimateGridDrafts } from "@/hooks/use-estimate-grid-drafts";
import {
  ESTIMATE_COLUMN_LABELS,
  ESTIMATE_COLUMN_ORDER,
  ESTIMATE_MAX_COLUMN_WIDTH,
  ESTIMATE_MIN_COLUMN_WIDTHS,
  useEstimateColumnWidths,
} from "@/hooks/use-estimate-column-widths";
import { usePlanningCreateTaskDialog, type CreateTaskCommand } from "@/hooks/use-planning-create-task-dialog";
import { stopRowKeys, useTreeTableSelection } from "@/hooks/use-tree-table-selection";
import type {
  CostCategory,
  CostRate,
  ProjectCostCode,
  ResourceNode,
  ResourceRole,
  RevisionCostLineCreateInput,
  RevisionCostNature,
  RevisionNode,
} from "@/lib/backend";
import {
  EXPLAINED_MOVE_REFUSALS,
  normalizeSelectionToRoots,
  planningMoveAvailability,
  type PlanningMoveMode,
  type PlanningRow,
} from "@/lib/planning-tree";
import {
  computeRevisionCostGridTotals,
  costNumber,
  EMPTY_ROLE_CASCADE,
  formatEuros,
  gridRowDeleteLabel,
  gridRowLabel,
  isCostRow,
  roleCascadeOf,
  rowAmount,
  rowHourlyRate,
  type RevisionCostGridContext,
  type RevisionCostGridRow,
  type RevisionCostRow,
  type RoleCascadeSelection,
} from "@/lib/revision-cost-grid";
import { buildRevisionTreeRows, revisionNodeRowIdentity, siblingRanks } from "@/lib/revision-tree";

// E14-11 (#337): the devis grid, on the revision model and on the shared editable-tree base.
//
// What this rewrite actually changes, beyond the types:
//
// * **one tree, not two.** Tasks and cost lines were two parallel lists stitched back together by
//   a shared uid space in which a cost node's uid was *negative*; they are now nodes of the same
//   tree, and the grid renders `buildRevisionTreeRows(nodes)` with no kind filter. `row_number`
//   and `level` come off the wire, computed on read, so nothing is renumbered client-side;
// * **tasks are movable from here.** E12 put "réorganiser les tâches depuis le devis" out of
//   scope because the devis had no say over the planning's order. Under one tree, moving a task
//   from the devis *is* moving it in the planning -- the same `POST .../nodes/move` the Planning
//   tab calls, decided by the same `planningMoveAvailability` (reused as is: it was made correct
//   for a filtered tree and an unfiltered one precisely so this grid would not fork it);
// * **the Type column branches** MO/non-MO for real, and the MO branch's Dpt/Rôle cascade lives in
//   the cells (see estimate-grid-cost-cells.tsx) rather than in a dialog. That is #315.
//
// Read-only is decided by the caller and is absolute: on a validated revision every cell is plain
// text, the toolbar is gone and no row carries a context menu at all (INV-03 refuses every write,
// so an action that could only 400 is not offered).

export type EstimateGridTreeTableProps = Readonly<{
  /** Every node of the revision, depth-first, as the tree read answered them. */
  nodes: readonly RevisionNode[];
  /** Identity of the displayed revision; changing it resets expand/selection/draft state. */
  revisionKey: number | null;
  readOnly: boolean;
  mutationBusy: boolean;
  /** Active non-MO categories: the flat list the non-MO branch of the Type column offers. */
  costCategories: readonly CostCategory[];
  /** Including deactivated ones, so an existing line still shows its real category name. */
  allCostCategories: readonly CostCategory[];
  resourceNodes: readonly ResourceNode[];
  resourceRoles: readonly ResourceRole[];
  costRates: readonly CostRate[];
  onMove?: (mode: PlanningMoveMode, nodeIds: number[]) => void;
  onUpdatePlanning?: (nodeId: number, payload: { name: string }) => Promise<boolean>;
  onUpdateCost?: (
    nodeId: number,
    payload: {
      label?: string;
      quantity?: number;
      hours?: number;
      unit_cost?: number;
      role_id?: number;
      cost_type_id?: number;
      cost_category_id?: number;
    },
  ) => Promise<boolean>;
  /** Replaces a cost line by the same line in the other nature -- see switchCostLineNature. */
  onSwitchNature?: (
    row: RevisionCostRow,
    payload: Omit<RevisionCostLineCreateInput, "expected_lock_version" | "parent_id" | "position">,
  ) => Promise<boolean>;
  onCreateCostLine?: (payload: Omit<RevisionCostLineCreateInput, "expected_lock_version">) => void;
  onCreateTask?: (command: CreateTaskCommand) => void;
  onDeleteNodes?: (nodeIds: number[]) => void;
  // Bulk cost-code assignment (E6-03/#64), rendered here rather than above the grid: it acts on
  // the grid's own selection, which lives in the shared selection hook. Lifting that selection out
  // would mean a child writing its parent's state during render -- the very thing React refuses.
  projectCostCodes: readonly ProjectCostCode[];
  bulkCostCodeId: string;
  onBulkCostCodeIdChange: (value: string) => void;
  bulkAssignBusy: boolean;
  /** Assigns the currently chosen cost code to the selected **cost** nodes. */
  onAssignCostCode?: (nodeIds: number[]) => void;
}>;

/** Only meaningful when exactly one row is selected -- see PlanningTreeTable's own helper. */
function singleSelectedTaskRow(
  selectedIds: ReadonlySet<number>,
  rows: readonly RevisionCostGridRow[],
): PlanningRow | null {
  if (selectedIds.size !== 1) {
    return null;
  }
  const row = rows.find((candidate) => candidate.node_id === [...selectedIds][0]);
  // A cost row is deliberately not offered as a creation target: "comme enfant de" a cost line
  // would be a task under a cost node, which INV-14 refuses, and "après" it is already covered by
  // the default. The dialog then offers the root, which is always legal.
  if (!row || row.kind !== "task" || row.planning === null) {
    return null;
  }
  return { ...row, planning: row.planning };
}

/** A value the grid cannot compute (no rate configured, no value at all). */
const UNKNOWN = "—";

/** Why "Ajouter une ligne de coût" is greyed out when the referential holds no non-MO category. */
const NO_COST_CATEGORY_REFUSAL =
  "Aucune catégorie de coût non-MO n'est configurée : impossible de créer une ligne.";

const NO_COST_CATEGORY_REFUSAL_ID = "create-cost-line-refusal";

/**
 * "Ajouter une ligne de coût", and the reason it is greyed out when there is one.
 *
 * The motif is **visible text**, not just a `title`: a disabled button takes no focus, so a
 * tooltip on it is reachable by mouse hover alone -- keyboard and screen-reader users would meet a
 * command that never explains itself. And this refusal is permanent rather than transitory: it
 * lasts until someone configures a non-MO category in the referential, so there is nothing to wait
 * for. Same objection that turned the milestone template's `title` (#387) and the Type select's
 * into shown copy; the `title` stays as a hover convenience, it is simply no longer the only
 * carrier.
 */
function AddCostLineButton({
  mutationBusy,
  costCategories,
  onAdd,
}: Readonly<{ mutationBusy: boolean; costCategories: readonly CostCategory[]; onAdd: () => void }>) {
  const refusal = costCategories.length ? undefined : NO_COST_CATEGORY_REFUSAL;
  return (
    <span className="flex flex-col gap-1">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={mutationBusy || refusal !== undefined}
        title={refusal}
        aria-describedby={refusal ? NO_COST_CATEGORY_REFUSAL_ID : undefined}
        onClick={onAdd}
      >
        Ajouter une ligne de coût
      </Button>
      {refusal ? (
        <span id={NO_COST_CATEGORY_REFUSAL_ID} className="text-xs text-muted-foreground">
          {refusal}
        </span>
      ) : null}
    </span>
  );
}

/**
 * The attributes a change of nature carries over, because they belong to the **line** and not to
 * its nature.
 *
 * `RevisionCostLineCreate` accepts `cost_code_id`, `comment`, `description` and `planned_date` on
 * either nature (they are not part of the INV-19 ↔ INV-20 split), so a replacement payload that
 * left them out would silently destroy them: a user who assigned "C1" from the bulk bar, then
 * realised the line was MO and flipped its Type, would find the cost code gone with nothing said.
 * Worse for `planned_date` and `comment`, which this screen has no editor for at all -- the loss
 * would be irreversible through the interface. #386 relocates them into one.
 *
 * `supply_status` is deliberately **not** carried: INV-19 forbids it on a labour facet, so it
 * cannot travel into the MO branch -- and in the other direction the source *is* a labour facet,
 * which never carries one to begin with.
 */
function carriedOverAttributes(row: RevisionCostRow) {
  return {
    cost_code_id: row.cost.cost_code_id,
    comment: row.cost.comment,
    description: row.description,
    planned_date: row.cost.planned_date,
  };
}

function formatNumber(value: number): string {
  return value.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
}

export function EstimateGridTreeTable({
  nodes,
  revisionKey,
  readOnly,
  mutationBusy,
  costCategories,
  allCostCategories,
  resourceNodes,
  resourceRoles,
  costRates,
  onMove,
  onUpdatePlanning,
  onUpdateCost,
  onSwitchNature,
  onCreateCostLine,
  onCreateTask,
  onDeleteNodes,
  projectCostCodes,
  bulkCostCodeId,
  onBulkCostCodeIdChange,
  bulkAssignBusy,
  onAssignCostCode,
}: EstimateGridTreeTableProps) {
  const [renderedRevisionKey, setRenderedRevisionKey] = useState(revisionKey);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  // The one row whose Dpt/Rôle cascade -- or whose pending change of nature -- is being edited.
  // One at a time, deliberately: a nature switch is only asked for once the *other* branch's
  // mandatory field is answered, and carrying several half-answered branches at once would let a
  // user lose one by starting another.
  const [cascadeEdit, setCascadeEdit] = useState<
    (RoleCascadeSelection & { nodeId: number; pendingNature: RevisionCostNature | null }) | null
  >(null);

  // No kind filter, deliberately: the devis grid renders tasks *and* cost lines, which is the
  // whole point of there being one tree.
  const rows = useMemo(() => buildRevisionTreeRows(nodes), [nodes]);
  const nodesById = useMemo(() => new Map(nodes.map((node) => [node.node_id, node])), [nodes]);
  const gridContext: RevisionCostGridContext = useMemo(
    () => ({ nodesById, resourceRoles, costCategories: allCostCategories, costRates }),
    [nodesById, resourceRoles, allCostCategories, costRates],
  );
  const totalsByNodeId = useMemo(
    () => computeRevisionCostGridTotals(rows, gridContext),
    [rows, gridContext],
  );
  // aria-posinset/aria-setsize, over the **rendered** rows and only those: mixing the stored
  // `position` with a count taken from another set is how "3 sur 2" gets announced (#380).
  const rankByNodeId = useMemo(() => siblingRanks(rows), [rows]);

  const columnWidths = useEstimateColumnWidths();
  const totalColumnWidth = useMemo(
    () => ESTIMATE_COLUMN_ORDER.reduce((total, key) => total + columnWidths.widths[key], 0),
    [columnWidths.widths],
  );

  const selection = useTreeTableSelection(rows, revisionNodeRowIdentity);
  const drafts = useEstimateGridDrafts({ mutationBusy, onUpdatePlanning, onUpdateCost });
  const createTaskDialog = usePlanningCreateTaskDialog({
    onCreateTask,
    singleSelectedRow: singleSelectedTaskRow(selection.selectedUids, rows),
  });

  // A different revision must never reuse another revision's expand/selection/draft state. Same
  // deliberate synchronous render-body reset as PlanningTreeTable's -- see that component for why
  // this cannot be a useEffect.
  if (revisionKey !== renderedRevisionKey) {
    setRenderedRevisionKey(revisionKey);
    selection.reset();
    drafts.reset();
    createTaskDialog.reset();
    setCascadeEdit(null);
    setDeleteDialogOpen(false);
  }

  // Decided on the **complete** node list, tasks and cost lines alike, because that is the set the
  // backend ranks a node in (`children_of()`, INV-05). See planningMoveAvailability's contract.
  const moveAvailability = {
    indent: planningMoveAvailability(nodes, selection.selectedUids, "indent"),
    outdent: planningMoveAvailability(nodes, selection.selectedUids, "outdent"),
    up: planningMoveAvailability(nodes, selection.selectedUids, "up"),
    down: planningMoveAvailability(nodes, selection.selectedUids, "down"),
  };
  const moveNotice =
    [moveAvailability.indent, moveAvailability.outdent].find(
      (availability) => availability.refusal !== null && EXPLAINED_MOVE_REFUSALS.has(availability.refusal),
    )?.reason ?? null;

  const selectedRootIds = normalizeSelectionToRoots(nodes, selection.selectedUids).map((node) => node.node_id);
  const selectedLabels = rows
    .filter((row) => selection.selectedUids.has(row.node_id))
    .map(gridRowDeleteLabel);
  // A cost code is a cost-facet attribute: assigning one to a task node would be a write on a
  // facet it does not carry, so the bulk bar only ever counts and targets cost rows.
  const selectedCostNodeIds = rows
    .filter((row) => selection.selectedUids.has(row.node_id) && isCostRow(row))
    .map((row) => row.node_id);

  function dispatchMove(mode: PlanningMoveMode) {
    if (planningMoveAvailability(nodes, selection.selectedUids, mode).enabled) {
      onMove?.(mode, [...selection.selectedUids]);
    }
  }

  function confirmDelete() {
    onDeleteNodes?.(selectedRootIds);
    setDeleteDialogOpen(false);
    selection.clearSelection();
  }

  function cascadeFor(row: RevisionCostGridRow): RoleCascadeSelection {
    if (cascadeEdit?.nodeId === row.node_id) {
      return { dept1Id: cascadeEdit.dept1Id, dept2Id: cascadeEdit.dept2Id, roleId: cascadeEdit.roleId };
    }
    if (isCostRow(row) && row.cost.nature === "labor") {
      return roleCascadeOf(row.cost.role_id, resourceRoles, resourceNodes);
    }
    return EMPTY_ROLE_CASCADE;
  }

  function onNatureChange(row: RevisionCostGridRow, nature: RevisionCostNature) {
    if (!isCostRow(row)) {
      return;
    }
    if (nature === row.cost.nature) {
      // Back to what the line already is: the pending branch is abandoned and the row goes back to
      // showing its stored department, role and category. Nothing was written, so nothing to undo.
      setCascadeEdit(null);
      return;
    }
    setCascadeEdit({ nodeId: row.node_id, pendingNature: nature, ...EMPTY_ROLE_CASCADE });
  }

  function onDept1Change(row: RevisionCostGridRow, dept1Id: string) {
    setCascadeEdit((current) => ({
      nodeId: row.node_id,
      pendingNature: current?.nodeId === row.node_id ? current.pendingNature : null,
      dept1Id,
      // A narrower Dpt 1er niveau invalidates both levels below it: keeping the old ones would
      // leave a role that does not belong to the department now displayed.
      dept2Id: "",
      roleId: "",
    }));
  }

  function onDept2Change(row: RevisionCostGridRow, dept2Id: string) {
    setCascadeEdit((current) => ({
      nodeId: row.node_id,
      pendingNature: current?.nodeId === row.node_id ? current.pendingNature : null,
      dept1Id: current?.nodeId === row.node_id ? current.dept1Id : cascadeFor(row).dept1Id,
      dept2Id,
      roleId: "",
    }));
  }

  /**
   * Abandons a cascade the user opened and then left without choosing a role.
   *
   * Without this, a row could show "Sélectionner" in its Rôle cell while its Taux horaire and PRU
   * cells go on pricing the role it still *stores* -- `onDept1Change`/`onDept2Change` blank the
   * pending `roleId`, the computed cells read `row.cost.role_id`, and the two halves of the row
   * then contradict each other until the revision is changed.
   *
   * Abandoning on blur rather than keeping the stored role on screen, deliberately: while the
   * cascade is open the empty Rôle select is *correct* -- the stored role is not among the options
   * of the department being picked, and re-displaying it there would name a role that does not
   * belong to the department shown next to it. What is wrong is the state outliving the edit, so
   * it is the state that goes. The row then returns to its stored department, role and price, all
   * three at once, exactly as picking the original nature again abandons a pending switch.
   *
   * A pending change of nature is **not** abandoned here: nothing is stored for it to fall back
   * to, and the row is telling the user in as many words what remains to be chosen.
   */
  function onCascadeBlur(row: RevisionCostGridRow, nextFocus: EventTarget | null) {
    // Moving from one select of the cascade to the next is not leaving it.
    if (nextFocus instanceof HTMLElement && nextFocus.dataset.cascadeRow === String(row.node_id)) {
      return;
    }
    setCascadeEdit((current) =>
      current?.nodeId === row.node_id && current.pendingNature === null && !current.roleId
        ? null
        : current,
    );
  }

  async function onRoleChange(row: RevisionCostGridRow, roleId: number) {
    if (!isCostRow(row) || !roleId) {
      return;
    }
    setCascadeEdit((current) =>
      current?.nodeId === row.node_id ? { ...current, roleId: String(roleId) } : current,
    );
    const pendingNature = cascadeEdit?.nodeId === row.node_id ? cascadeEdit.pendingNature : null;
    const done =
      pendingNature === "labor"
        ? await onSwitchNature?.(row, {
            nature: "labor",
            label: row.cost.label,
            quantity: costNumber(row.cost.quantity),
            role_id: roleId,
            // INV-19 wants hours *present*, not non-zero: a line that has just changed nature has
            // no hours of its own yet, and 0 is the honest starting point the user then fills in.
            hours: 0,
            ...carriedOverAttributes(row),
          })
        : // An MO line that stays MO: only its role changes, which is the edit #315 recorded as
          // impossible ("il faut la supprimer et la recréer").
          await onUpdateCost?.(row.node_id, { role_id: roleId });
    if (done) {
      // Bounded to this row rather than clearing whatever cascade is open. In practice the two
      // are the same thing -- `mutationBusy` disables every select while the write is in flight,
      // so no other row's cascade can have been opened meanwhile -- but that is a guarantee held
      // by another component, and one line here is cheaper than depending on it from a distance.
      setCascadeEdit((current) => (current?.nodeId === row.node_id ? null : current));
    }
  }

  async function onCategoryChange(row: RevisionCostGridRow, categoryId: number) {
    if (!isCostRow(row) || !categoryId) {
      return;
    }
    const category = allCostCategories.find((candidate) => candidate.id === categoryId);
    if (!category) {
      return;
    }
    const pendingNature = cascadeEdit?.nodeId === row.node_id ? cascadeEdit.pendingNature : null;
    const done =
      pendingNature === "non_labor"
        ? await onSwitchNature?.(row, {
            nature: "non_labor",
            label: row.cost.label,
            quantity: costNumber(row.cost.quantity),
            cost_type_id: category.cost_type_id,
            cost_category_id: category.id,
            // INV-20 wants a débours present; 0 is the starting point, edited inline right after.
            unit_cost: 0,
            ...carriedOverAttributes(row),
          })
        : // `cost_type_id` travels with the category, always: the two are one choice, and leaving
          // the old type behind would describe the line as a type its category does not belong to.
          await onUpdateCost?.(row.node_id, {
            cost_category_id: category.id,
            cost_type_id: category.cost_type_id,
          });
    if (done) {
      // Same row-bounded reset as onRoleChange's -- see the note there.
      setCascadeEdit((current) => (current?.nodeId === row.node_id ? null : current));
    }
  }

  function addCostLine() {
    const category = costCategories[0];
    if (!category || !onCreateCostLine) {
      return;
    }
    const target = rows.find((row) => selection.selectedUids.has(row.node_id)) ?? null;
    onCreateCostLine({
      nature: "non_labor",
      label: "Nouvelle ligne",
      quantity: 1,
      cost_type_id: category.cost_type_id,
      cost_category_id: category.id,
      unit_cost: 0,
      // Under the selected task, or at the root when a cost line (or nothing) is selected: a cost
      // line under a cost line is legal but is rarely what a user asking for "une ligne" wants,
      // and the root is always legal (INV-01) and one outdent away from anywhere.
      parent_id: target && target.kind === "task" ? target.node_id : null,
    });
  }

  function duplicateResource(row: RevisionCostRow) {
    if (!onCreateCostLine || row.cost.role_id == null) {
      return;
    }
    // "Duplication vierge d'une ressource MO" (E12-11/#293): the same role on the same bearing
    // task, with blank amounts -- never a copy of this line's own quantity and hours.
    onCreateCostLine({
      nature: "labor",
      label: row.cost.label,
      quantity: 1,
      role_id: row.cost.role_id,
      hours: 0,
      parent_id: row.parent_id,
    });
  }

  function renderLabelCell(row: RevisionCostGridRow) {
    const collapsed = selection.collapsedUids.has(row.node_id);
    const label = gridRowLabel(row);
    return (
      <div
        className="flex min-w-0 items-center gap-1"
        // `level` is 1-based (roots at 1) and deliberately uncapped: a real import nests deeper
        // than a handful of levels and the indentation must keep saying so.
        style={{ paddingLeft: `${(row.level - 1) * 1.25}rem` }}
      >
        {row.hasChildren ? (
          <button
            type="button"
            aria-label={`${collapsed ? "Déplier" : "Replier"} ${label}`}
            className="flex size-6 shrink-0 items-center justify-center rounded-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            {...stopRowKeys}
            onClick={(event) => {
              event.stopPropagation();
              selection.toggleCollapsed(row.node_id);
            }}
          >
            {collapsed ? <ChevronRight aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
          </button>
        ) : (
          <span className="size-6 shrink-0" />
        )}
        {readOnly ? (
          <span className="min-w-0 truncate">{label}</span>
        ) : (
          <Input
            aria-label={`Libellé de ${label}`}
            className="min-w-0"
            value={drafts.draftFor(row).label}
            disabled={mutationBusy}
            onChange={(event) => drafts.updateDraftField(row, "label", event.target.value)}
            onBlur={() => void drafts.commitLabel(row)}
            onKeyDown={drafts.onFieldKeyDown}
          />
        )}
      </div>
    );
  }

  /** A numeric cell: the subtotal of a récapitulatif row, an editable field, or a plain value. */
  function renderNumberCell(
    row: RevisionCostGridRow,
    field: "quantity" | "hours" | "unitCost",
    options: { editable: boolean; value: string; ariaLabel: string; min: string; commit: () => void },
  ) {
    if (!isCostRow(row)) {
      const totals = totalsByNodeId.get(row.node_id);
      if (!row.hasChildren || !totals) {
        return "-";
      }
      return formatNumber(
        field === "quantity" ? totals.quantity : field === "hours" ? totals.hours : totals.debours,
      );
    }
    if (!options.editable) {
      return "-";
    }
    if (readOnly) {
      // From the **stored** facet, never from `options.value`: that one is the row's uncommitted
      // draft, and `readOnly` can turn on without the revision changing -- a lock conflict posts
      // the banner, which makes the whole table read-only on the very same revision. Rendering the
      // draft there would show a "999" the user never saved, as plain text indistinguishable from
      // a persisted value (and "NaN" for a half-typed one). The Libellé cell already reads the
      // stored label through `gridRowLabel`; this is the same rule, applied to the numbers.
      const stored =
        field === "quantity" ? row.cost.quantity : field === "hours" ? row.cost.hours : row.cost.unit_cost;
      return stored === null || stored === "" ? UNKNOWN : formatNumber(costNumber(stored));
    }
    return (
      <Input
        aria-label={options.ariaLabel}
        type="number"
        min={options.min}
        step="0.01"
        value={options.value}
        disabled={mutationBusy}
        onChange={(event) => drafts.updateDraftField(row, field, event.target.value)}
        onBlur={options.commit}
        onKeyDown={drafts.onFieldKeyDown}
      />
    );
  }

  function renderHourlyRateCell(row: RevisionCostGridRow) {
    if (!isCostRow(row) || row.cost.nature !== "labor") {
      return "-";
    }
    const rate = rowHourlyRate(row, gridContext);
    return rate === null ? UNKNOWN : formatEuros(rate);
  }

  function renderPruCell(row: RevisionCostGridRow) {
    if (!isCostRow(row)) {
      const totals = totalsByNodeId.get(row.node_id);
      return row.hasChildren && totals ? formatEuros(totals.pru) : "-";
    }
    const amount = rowAmount(row, gridContext);
    return amount === null ? UNKNOWN : formatEuros(amount);
  }

  function renderContextMenuItems(row: RevisionCostRow) {
    if (row.cost.nature === "labor") {
      return (
        <ContextMenuItem disabled={mutationBusy || row.cost.role_id == null} onClick={() => duplicateResource(row)}>
          Ajouter une ressource
        </ContextMenuItem>
      );
    }
    return (
      <ContextMenuItem disabled>
        {/*
          E12-11/#293's second menu action. It is kept visible and explains itself rather than
          disappearing silently: the template is a planning-side generator that only exists on the
          pre-revision socle (`POST .../estimates/{id}/cost-lines/{lineId}/milestones`), and there
          is no revision endpoint for it yet -- tracked as **#387** rather than reimplemented here,
          a second formulation of a generation rule being exactly what this EPIC removes.

          The reason is part of the entry's own text, not a `title`: a disabled menu item cannot
          be focused, so it is never reached by keyboard and a tooltip that only opens on hover
          says nothing to anyone who does not use a mouse.
        */}
        <span className="flex flex-col">
          <span>Gabarit de jalons</span>
          <span className="text-xs text-muted-foreground">
            Pas encore disponible sur le modèle de révision.
          </span>
        </span>
      </ContextMenuItem>
    );
  }

  return (
    <div>
      <PlanningTreeToolbar
        visible={!readOnly}
        showMoveActions={Boolean(onMove)}
        indentDisabled={!moveAvailability.indent.enabled || mutationBusy}
        outdentDisabled={!moveAvailability.outdent.enabled || mutationBusy}
        moveUpDisabled={!moveAvailability.up.enabled || mutationBusy}
        moveDownDisabled={!moveAvailability.down.enabled || mutationBusy}
        onIndent={() => dispatchMove("indent")}
        onOutdent={() => dispatchMove("outdent")}
        onMoveUp={() => dispatchMove("up")}
        onMoveDown={() => dispatchMove("down")}
        notice={moveNotice}
        showCreateAction={Boolean(onCreateTask)}
        createDisabled={mutationBusy}
        onCreateTask={createTaskDialog.openCreateTaskDialog}
        showDeleteAction={Boolean(onDeleteNodes)}
        deleteDisabled={selection.selectedUids.size === 0 || mutationBusy}
        onDeleteSelection={() => setDeleteDialogOpen(true)}
      >
        {onCreateCostLine ? (
          <AddCostLineButton mutationBusy={mutationBusy} costCategories={costCategories} onAdd={addCostLine} />
        ) : null}
      </PlanningTreeToolbar>

      {!readOnly && onAssignCostCode ? (
        <BulkCostCodeAssignmentBar
          selectedCount={selectedCostNodeIds.length}
          projectCostCodes={[...projectCostCodes]}
          bulkCostCodeId={bulkCostCodeId}
          onBulkCostCodeIdChange={onBulkCostCodeIdChange}
          bulkAssignBusy={bulkAssignBusy}
          mutationBusy={mutationBusy}
          onAssign={() => onAssignCostCode(selectedCostNodeIds)}
        />
      ) : null}

      {rows.length ? (
        <Table
          // #380, devis half: the grid folds, unfolds, selects and takes focus -- it is a treegrid
          // and now says so. Without these roles a screen-reader user hears a plain table and is
          // told neither a row's level nor whether it can be unfolded.
          role="treegrid"
          aria-label="Devis de la révision"
          aria-multiselectable="true"
          className="table-fixed w-auto"
          style={{ width: totalColumnWidth }}
        >
          <colgroup>
            {ESTIMATE_COLUMN_ORDER.map((key) => (
              <col key={key} style={{ width: `${columnWidths.widths[key]}px` }} />
            ))}
          </colgroup>
          <TableHeader>
            <TableRow>
              {ESTIMATE_COLUMN_ORDER.map((key) => (
                <TableHead key={key} className="relative overflow-hidden">
                  {ESTIMATE_COLUMN_LABELS[key]}
                  <TreeTableColumnResizeHandle
                    column={key}
                    label={ESTIMATE_COLUMN_LABELS[key]}
                    width={columnWidths.widths[key]}
                    min={ESTIMATE_MIN_COLUMN_WIDTHS[key]}
                    max={ESTIMATE_MAX_COLUMN_WIDTH}
                    onResizeStart={columnWidths.startResize}
                    onResizeBy={columnWidths.resizeBy}
                  />
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {selection.visibleRows.map((row) => {
              const collapsed = selection.collapsedUids.has(row.node_id);
              const selected = selection.selectedUids.has(row.node_id);
              const draft = drafts.draftFor(row);
              const cost = isCostRow(row) ? row.cost : null;
              const rowElement = (
                <TableRow
                  key={row.node_id}
                  ref={(element) => selection.registerRow(row, element)}
                  role="row"
                  data-state={selected ? "selected" : undefined}
                  aria-selected={selected}
                  aria-level={row.level}
                  aria-posinset={rankByNodeId.get(row.node_id)?.position ?? 1}
                  aria-setsize={rankByNodeId.get(row.node_id)?.total ?? 1}
                  aria-expanded={row.hasChildren ? !collapsed : undefined}
                  tabIndex={selection.focusableUid === row.node_id ? 0 : -1}
                  // An `outline`, not the design system's `ring-3`: a box-shadow on a
                  // `display: table-row` is unreliable across browsers, where an outline is drawn
                  // around the whole row (#380).
                  className="cursor-pointer outline-none focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
                  onClick={(event) => selection.selectRow(row, event)}
                  onFocus={() => selection.setFocusedUid(row.node_id)}
                  onKeyDown={(event) => selection.onRowKeyDown(event, row)}
                >
                  <TableCell role="gridcell">{row.row_number}</TableCell>
                  <TableCell role="gridcell" className="overflow-hidden">
                    {renderLabelCell(row)}
                  </TableCell>
                  <EstimateGridCostCells
                    row={row}
                    rows={rows}
                    readOnly={readOnly}
                    mutationBusy={mutationBusy}
                    cascade={cascadeFor(row)}
                    pendingNature={cascadeEdit?.nodeId === row.node_id ? cascadeEdit.pendingNature : null}
                    resourceNodes={resourceNodes}
                    resourceRoles={resourceRoles}
                    costCategories={costCategories}
                    allCostCategories={allCostCategories}
                    onNatureChange={onNatureChange}
                    onDept1Change={onDept1Change}
                    onDept2Change={onDept2Change}
                    onCascadeBlur={onCascadeBlur}
                    onRoleChange={(target, roleId) => void onRoleChange(target, roleId)}
                    onCategoryChange={(target, categoryId) => void onCategoryChange(target, categoryId)}
                  />
                  <TableCell role="gridcell">
                    {renderNumberCell(row, "quantity", {
                      editable: cost !== null,
                      value: draft.quantity,
                      ariaLabel: `Qté de ${gridRowLabel(row)}`,
                      min: "0.01",
                      commit: () => void drafts.commitQuantity(row),
                    })}
                  </TableCell>
                  <TableCell role="gridcell">
                    {renderNumberCell(row, "hours", {
                      editable: cost?.nature === "labor",
                      value: draft.hours,
                      ariaLabel: `Heures de ${gridRowLabel(row)}`,
                      min: "0",
                      commit: () => void drafts.commitHours(row),
                    })}
                  </TableCell>
                  <TableCell role="gridcell">
                    {renderNumberCell(row, "unitCost", {
                      editable: cost !== null && cost.nature !== "labor",
                      value: draft.unitCost,
                      ariaLabel: `Débours de ${gridRowLabel(row)}`,
                      min: "0",
                      commit: () => void drafts.commitUnitCost(row),
                    })}
                  </TableCell>
                  <TableCell role="gridcell">{renderHourlyRateCell(row)}</TableCell>
                  <TableCell role="gridcell">{renderPruCell(row)}</TableCell>
                </TableRow>
              );

              // A context menu only where it has an action to offer: on a cost row, and only while
              // the revision is editable. On a validated one nothing here could do anything but
              // 400, so the menu is not attached at all.
              if (!readOnly && isCostRow(row)) {
                return (
                  <ContextMenu key={row.node_id}>
                    <ContextMenuTrigger render={rowElement} />
                    <ContextMenuContent>{renderContextMenuItems(row)}</ContextMenuContent>
                  </ContextMenu>
                );
              }
              return rowElement;
            })}
          </TableBody>
        </Table>
      ) : (
        <p className="py-6 text-sm text-muted-foreground">Cette révision ne contient aucune ligne.</p>
      )}

      <PlanningCreateTaskDialog
        open={createTaskDialog.createDialogOpen}
        name={createTaskDialog.createTaskName}
        isMilestone={createTaskDialog.createTaskIsMilestone}
        positionMode={createTaskDialog.createPositionMode}
        error={createTaskDialog.createTaskError}
        singleSelectedRow={singleSelectedTaskRow(selection.selectedUids, rows)}
        mutationBusy={mutationBusy}
        onNameChange={createTaskDialog.setCreateTaskName}
        onMilestoneChange={createTaskDialog.setCreateTaskIsMilestone}
        onPositionModeChange={createTaskDialog.setCreatePositionMode}
        onClose={createTaskDialog.closeCreateTaskDialog}
        onSubmit={createTaskDialog.submitCreateTask}
      />
      <PlanningDeleteDialog
        open={deleteDialogOpen}
        rowLabels={selectedLabels}
        busy={mutationBusy}
        onCancel={() => setDeleteDialogOpen(false)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
