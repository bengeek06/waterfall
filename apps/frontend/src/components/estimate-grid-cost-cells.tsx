"use client";

import type { FocusEvent } from "react";

import { TableCell } from "@/components/ui/table";
import { stopRowKeys } from "@/hooks/use-tree-table-selection";
import type { CostCategory, ResourceNode, ResourceRole, RevisionCostNature } from "@/lib/backend";
import {
  costCategoryLabel,
  dept1Options,
  dept2Options,
  derivedCostCategory,
  gridRowLabel,
  isCostRow,
  resolveDeptColumns,
  roleOptions,
  rowCostCategory,
  taskRowTypeLabel,
  type RevisionCostGridRow,
  type RevisionCostRow,
  type RoleCascadeSelection,
} from "@/lib/revision-cost-grid";

// E14-11 (#337), and this file is where #315 is actually answered.
//
// The four cells the "Type" column branches into -- Type, Dpt 1er niveau, Dpt 2eme niveau, Rôle --
// **in the grid**, not in a dialog. E12-10 (#292) specified them as drop-downs here; E12-06 (#278)
// shipped the cascade in "Ajouter une ligne MO" instead, and #315 recorded that the grid itself
// never got it: a line's role could not be changed without deleting and recreating it, and a line
// could not be switched from non-MO to MO at all.
//
// Two rules of the model shape every control below, and neither is negotiable:
//
// * an MO line carries a role and **no** accounting category (INV-19). So choosing a role does not
//   write a category anywhere: the category is derived from the role and shown read-only next to
//   the nature. `check_cost_facet_shape` refuses the write, creation included, so there is no
//   "write it anyway and let the server sort it out" variant of this;
// * flipping the nature swaps the whole attribute set of the line (INV-19 ↔ INV-20). The nature
//   select therefore does not commit on its own: it opens the *other* branch's mandatory field --
//   the cascade for MO, the flat category list for non-MO -- and the switch is asked for only once
//   that field is answered. Anything else would send a half-shaped facet the domain refuses.

const SELECT_CLASS = "h-8 w-full rounded-md border border-input bg-background px-2 text-sm";

export type EstimateGridCostCellsProps = Readonly<{
  row: RevisionCostGridRow;
  /** The whole row list, for "a task with task children is a récapitulatif". */
  rows: readonly RevisionCostGridRow[];
  readOnly: boolean;
  mutationBusy: boolean;
  /** Where this row's three cascade selects currently sit (pending edits included). */
  cascade: RoleCascadeSelection;
  /** The nature the user picked but has not completed yet, or null when none is pending. */
  pendingNature: RevisionCostNature | null;
  resourceNodes: readonly ResourceNode[];
  resourceRoles: readonly ResourceRole[];
  /** Active non-MO categories: the flat list the non-MO branch offers. */
  costCategories: readonly CostCategory[];
  /** Including deactivated ones, so an existing line still shows its real category name. */
  allCostCategories: readonly CostCategory[];
  onNatureChange: (row: RevisionCostGridRow, nature: RevisionCostNature) => void;
  onDept1Change: (row: RevisionCostGridRow, dept1Id: string) => void;
  onDept2Change: (row: RevisionCostGridRow, dept2Id: string) => void;
  /** Focus left one of the cascade's selects; `nextFocus` is what took it, when anything did. */
  onCascadeBlur: (row: RevisionCostGridRow, nextFocus: EventTarget | null) => void;
  onRoleChange: (row: RevisionCostGridRow, roleId: number) => void;
  onCategoryChange: (row: RevisionCostGridRow, categoryId: number) => void;
}>;

/**
 * The category to show next to the nature.
 *
 * While a switch to MO is pending the row still *stores* its old non-MO category, which would read
 * as if the line were already charged to it. The derived category of the role being chosen is the
 * only one worth showing there, and there is none until a role is picked.
 */
function shownCategoryOf(
  row: RevisionCostRow,
  props: EstimateGridCostCellsProps,
  isLabor: boolean,
): CostCategory | null {
  if (!props.pendingNature) {
    return rowCostCategory(row, props.resourceRoles, props.allCostCategories);
  }
  if (!isLabor) {
    return null;
  }
  return derivedCostCategory(Number(props.cascade.roleId) || null, props.resourceRoles, props.allCostCategories);
}

/** A task row has no nature and no resource: its "Type" says what the tree says it is. */
function TaskCells({ row, rows }: Readonly<{ row: RevisionCostGridRow; rows: readonly RevisionCostGridRow[] }>) {
  return (
    <>
      <TableCell role="gridcell">{taskRowTypeLabel(row, rows)}</TableCell>
      <TableCell role="gridcell">-</TableCell>
      <TableCell role="gridcell">-</TableCell>
      <TableCell role="gridcell">-</TableCell>
    </>
  );
}

function ReadOnlyCostCells({
  row,
  props,
  isLabor,
}: Readonly<{ row: RevisionCostRow; props: EstimateGridCostCellsProps; isLabor: boolean }>) {
  const role = props.resourceRoles.find((candidate) => candidate.id === row.cost.role_id);
  const [dept1, dept2] = isLabor ? resolveDeptColumns(role?.node_id, props.resourceNodes) : (["-", "-"] as const);
  return (
    <>
      <TableCell role="gridcell">
        <span>{isLabor ? "MO" : "non-MO"}</span>
        <span className="block text-xs text-muted-foreground">
          {costCategoryLabel(shownCategoryOf(row, props, isLabor))}
        </span>
      </TableCell>
      <TableCell role="gridcell">{dept1}</TableCell>
      <TableCell role="gridcell">{dept2}</TableCell>
      <TableCell role="gridcell">{isLabor ? (role?.name ?? "-") : "-"}</TableCell>
    </>
  );
}

/** The flat non-MO category list: the other branch of the Type column. */
function CategorySelect({
  row,
  props,
}: Readonly<{ row: RevisionCostRow; props: EstimateGridCostCellsProps }>) {
  const { costCategories, allCostCategories, pendingNature, mutationBusy, onCategoryChange } = props;
  // An existing line's category can have been deactivated since: it is offered as its own extra
  // option so the select shows the truth instead of silently snapping to another category.
  const currentCategoryMissing =
    !pendingNature &&
    row.cost.cost_category_id != null &&
    !costCategories.some((category) => category.id === row.cost.cost_category_id);
  return (
    <select
      aria-label={`Catégorie de ${gridRowLabel(row)}`}
      className={SELECT_CLASS}
      value={pendingNature ? "" : (row.cost.cost_category_id ?? "")}
      disabled={mutationBusy}
      {...stopRowKeys}
      onChange={(event) => onCategoryChange(row, Number(event.target.value))}
    >
      <option value="">Sélectionner une catégorie</option>
      {currentCategoryMissing ? (
        <option value={row.cost.cost_category_id as number}>
          {costCategoryLabel(rowCostCategory(row, props.resourceRoles, allCostCategories))}
        </option>
      ) : null}
      {costCategories.map((category) => (
        <option key={category.id} value={category.id}>
          {costCategoryLabel(category)}
        </option>
      ))}
    </select>
  );
}

function TypeCell({
  row,
  props,
  isLabor,
}: Readonly<{ row: RevisionCostRow; props: EstimateGridCostCellsProps; isLabor: boolean }>) {
  const { pendingNature, mutationBusy, onNatureChange } = props;
  const label = gridRowLabel(row);
  // A change of nature *replaces* the line, and a delete cascades over the subtree (INV-02), so a
  // line carrying sub-lines cannot be switched. That rule is known here, on `row.hasChildren`,
  // before any request -- so the command is withheld and says why, the way Désindenter does at the
  // root and Indenter does under a jalon. Left enabled, it would take the user through the whole
  // department/role cascade before refusing at the fourth interaction, and the row would stay
  // stuck showing three selects that can never lead anywhere.
  //
  // The motif is **visible text**, not just the `title`: a disabled `<select>` takes no focus, so a
  // tooltip on it is reachable by mouse hover alone -- keyboard and screen-reader users would meet
  // a control that refuses to open and never says why. Same objection that got the milestone
  // template's `title` (#387) turned into shown copy. The `title` stays as a hover convenience, it
  // is simply no longer the only carrier.
  const childrenRefusal = row.hasChildren
    ? "Cette ligne porte des sous-lignes : changer sa nature la remplacerait et supprimerait son sous-arbre."
    : undefined;
  return (
    <TableCell role="gridcell">
      <div className="flex flex-col gap-1">
        <select
          aria-label={`Type de ${label}`}
          className={SELECT_CLASS}
          value={isLabor ? "labor" : "non_labor"}
          disabled={mutationBusy || row.hasChildren}
          title={childrenRefusal}
          aria-describedby={childrenRefusal ? `nature-refusal-${row.node_id}` : undefined}
          {...stopRowKeys}
          onChange={(event) => onNatureChange(row, event.target.value as RevisionCostNature)}
        >
          <option value="labor">MO</option>
          <option value="non_labor">non-MO</option>
        </select>
        {childrenRefusal ? (
          <span id={`nature-refusal-${row.node_id}`} className="text-xs text-muted-foreground">
            {childrenRefusal}
          </span>
        ) : null}
        {isLabor ? (
          // Read-only, and that is the whole point of the amendment to #315: the category of an MO
          // line is the category of its role, derived here and stored nowhere.
          <span className="text-xs text-muted-foreground">
            Catégorie : {costCategoryLabel(shownCategoryOf(row, props, isLabor))}
          </span>
        ) : (
          <CategorySelect row={row} props={props} />
        )}
        {pendingNature ? (
          <span role="status" className="text-xs text-muted-foreground">
            {isLabor
              ? "Choisis un rôle pour basculer cette ligne en MO."
              : "Choisis une catégorie pour basculer cette ligne en non-MO."}
          </span>
        ) : null}
      </div>
    </TableCell>
  );
}

/** Dpt 1er niveau -> Dpt 2eme niveau -> Rôle, the MO branch, inline in the grid's own cells. */
function CascadeCells({
  row,
  props,
}: Readonly<{ row: RevisionCostRow; props: EstimateGridCostCellsProps }>) {
  const {
    cascade,
    mutationBusy,
    resourceNodes,
    resourceRoles,
    onDept1Change,
    onDept2Change,
    onRoleChange,
    onCascadeBlur,
  } = props;
  const label = gridRowLabel(row);
  // Tags the three selects as belonging to one and the same cascade, so a blur that merely moves
  // from one of them to the next is told apart from one that leaves the cascade altogether. They
  // sit in three separate <TableCell>s -- a table row admits no wrapper around them -- so the
  // grouping has to travel on the controls themselves.
  const cascadeGroup = {
    "data-cascade-row": row.node_id,
    onBlur: (event: FocusEvent<HTMLSelectElement>) => onCascadeBlur(row, event.relatedTarget),
  };
  return (
    <>
      <TableCell role="gridcell">
        <select
          aria-label={`Dpt 1er niveau de ${label}`}
          className={SELECT_CLASS}
          value={cascade.dept1Id}
          disabled={mutationBusy}
          {...stopRowKeys}
          {...cascadeGroup}
          onChange={(event) => onDept1Change(row, event.target.value)}
        >
          <option value="">Sélectionner</option>
          {dept1Options(resourceNodes).map((node) => (
            <option key={node.id} value={node.id}>
              {node.name}
            </option>
          ))}
        </select>
      </TableCell>
      <TableCell role="gridcell">
        <select
          aria-label={`Dpt 2eme niveau de ${label}`}
          className={SELECT_CLASS}
          value={cascade.dept2Id}
          // Nothing to choose from until a Dpt 1er niveau is: the restriction to its direct
          // children *is* the cascade (#292's own acceptance criterion).
          disabled={mutationBusy || !cascade.dept1Id}
          {...stopRowKeys}
          {...cascadeGroup}
          onChange={(event) => onDept2Change(row, event.target.value)}
        >
          <option value="">Sélectionner</option>
          {dept2Options(resourceNodes, cascade.dept1Id).map((node) => (
            <option key={node.id} value={node.id}>
              {node.name}
            </option>
          ))}
        </select>
      </TableCell>
      <TableCell role="gridcell">
        <select
          aria-label={`Rôle de ${label}`}
          className={SELECT_CLASS}
          value={cascade.roleId}
          disabled={mutationBusy || !cascade.dept2Id}
          {...stopRowKeys}
          {...cascadeGroup}
          onChange={(event) => onRoleChange(row, Number(event.target.value))}
        >
          <option value="">Sélectionner</option>
          {roleOptions(resourceRoles, cascade.dept2Id).map((role) => (
            <option key={role.id} value={role.id}>
              {role.name}
            </option>
          ))}
        </select>
      </TableCell>
    </>
  );
}

/** The three "-" a non-MO line shows where the MO branch shows its department and role. */
function EmptyCascadeCells() {
  return (
    <>
      <TableCell role="gridcell">-</TableCell>
      <TableCell role="gridcell">-</TableCell>
      <TableCell role="gridcell">-</TableCell>
    </>
  );
}

export function EstimateGridCostCells(props: EstimateGridCostCellsProps) {
  const { row, rows, readOnly, pendingNature } = props;
  if (!isCostRow(row)) {
    return <TaskCells row={row} rows={rows} />;
  }
  const isLabor = (pendingNature ?? row.cost.nature) === "labor";
  if (readOnly) {
    return <ReadOnlyCostCells row={row} props={props} isLabor={isLabor} />;
  }
  return (
    <>
      <TypeCell row={row} props={props} isLabor={isLabor} />
      {isLabor ? <CascadeCells row={row} props={props} /> : <EmptyCascadeCells />}
    </>
  );
}
