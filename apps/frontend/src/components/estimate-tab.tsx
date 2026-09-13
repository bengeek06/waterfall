"use client";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { EstimateGridTreeTable } from "@/components/estimate-grid-tree-table";
import { PlanningConflictBanner } from "@/components/planning-conflict-banner";
import { PlanningVersionControls } from "@/components/planning-version-controls";
import { isPlanningTreeReadOnly } from "@/components/planning-tree-panel";
import type { CreateTaskCommand } from "@/hooks/use-planning-create-task-dialog";
import type { RevisionLockConflict } from "@/hooks/use-revision-planning";
import type {
  CostCategory,
  CostRate,
  ProjectCostCode,
  ResourceNode,
  ResourceRole,
  Revision,
  RevisionAggregates,
  RevisionCostLineCreateInput,
  RevisionTree,
} from "@/lib/backend";
import type { PlanningMoveMode } from "@/lib/planning-tree";
import { formatEuros, type RevisionCostRow } from "@/lib/revision-cost-grid";

export type EstimateTabProps = Readonly<{
  active: boolean;
  // The revision, read and written through the very same hook instance the Planning tab uses --
  // one tree, one optimistic-lock counter. That is what makes "l'onglet Planning reflète
  // l'opération sans action de synchronisation" true by construction rather than by a refresh.
  revisions: Revision[];
  selectedRevision: Revision | null;
  selectedRevisionId: number | null;
  referenceRevisionId: number | null;
  revisionsBusy: boolean;
  treeBusy: boolean;
  tree: RevisionTree | null;
  mutationBusy: boolean;
  conflict: RevisionLockConflict | null;
  feedback: string | null;
  /** True when the page already shows an error banner, so this tab keeps quiet about it. */
  hasError: boolean;
  isReadOnlyProject: boolean;
  onSelectRevision: (revisionId: number) => void;
  onCreateDraft: () => void;
  onValidateRevision: () => void;
  onReloadConflict: () => void;
  exportBusy: boolean;
  onExport: () => void;
  /** The revision's totals, priced from its cost facets -- null while unread or unavailable. */
  aggregates: RevisionAggregates | null;
  aggregatesBusy: boolean;
  // Referentials, loaded once per project.
  costCategories: CostCategory[];
  allCostCategories: CostCategory[];
  resourceNodes: ResourceNode[];
  resourceRoles: ResourceRole[];
  costRates: CostRate[];
  projectCostCodes: ProjectCostCode[];
  bulkCostCodeId: string;
  onBulkCostCodeIdChange: (value: string) => void;
  bulkAssignBusy: boolean;
  onAssignCostCode: (nodeIds: number[]) => void;
  onMove: (mode: PlanningMoveMode, nodeIds: number[]) => void;
  onUpdatePlanning: (nodeId: number, payload: { name: string }) => Promise<boolean>;
  onUpdateCost: (
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
  onSwitchNature: (
    row: RevisionCostRow,
    payload: Omit<RevisionCostLineCreateInput, "expected_lock_version" | "parent_id" | "position">,
  ) => Promise<boolean>;
  onCreateCostLine: (payload: Omit<RevisionCostLineCreateInput, "expected_lock_version">) => void;
  onCreateTask: (command: CreateTaskCommand) => void;
  onDeleteNodes: (nodeIds: number[]) => void;
}>;

// E14-11 (#337): the Devis tab, rebuilt on the revision.
//
// A "version de devis" is no longer a document of its own: it is a **revision**, the same one the
// Planning tab shows, and it carries both facets. So the version controls, the read-only rule and
// the lock-conflict banner are literally the planning ones (PlanningVersionControls,
// isPlanningTreeReadOnly, PlanningConflictBanner) rather than a second set that would have to be
// kept in step with them.
export function EstimateTab({
  active,
  revisions,
  selectedRevision,
  selectedRevisionId,
  referenceRevisionId,
  revisionsBusy,
  treeBusy,
  tree,
  mutationBusy,
  conflict,
  feedback,
  hasError,
  isReadOnlyProject,
  onSelectRevision,
  onCreateDraft,
  onValidateRevision,
  onReloadConflict,
  exportBusy,
  onExport,
  aggregates,
  aggregatesBusy,
  costCategories,
  allCostCategories,
  resourceNodes,
  resourceRoles,
  costRates,
  projectCostCodes,
  bulkCostCodeId,
  onBulkCostCodeIdChange,
  bulkAssignBusy,
  onAssignCostCode,
  onMove,
  onUpdatePlanning,
  onUpdateCost,
  onSwitchNature,
  onCreateCostLine,
  onCreateTask,
  onDeleteNodes,
}: EstimateTabProps) {
  if (!active) {
    return null;
  }

  const readOnly = isPlanningTreeReadOnly(isReadOnlyProject, conflict !== null, tree);
  const showEmptyState = !revisionsBusy && !treeBusy && !hasError && !revisions.length;
  // Every write handler, withheld in one place instead of nine `readOnly ? undefined :` at the
  // call site. The grid decides what to render from the *absence* of a handler as much as from
  // `readOnly` itself, so a read-only revision offers no command to press and none to reach.
  //
  // Defence in depth, and inert as things stand: the grid's own `readOnly` already hides its
  // toolbar, its context menus and every editable cell, so no test can tell this apart from
  // passing the handlers through. Kept because each layer stands on its own -- and read as
  // *coverage* by nobody.
  const writeHandlers = readOnly
    ? {}
    : {
        onAssignCostCode,
        onMove,
        onUpdatePlanning,
        onUpdateCost,
        onSwitchNature,
        onCreateCostLine,
        onCreateTask,
        onDeleteNodes,
      };

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2>Devis de la révision</h2>
          <p className="text-sm text-muted-foreground">
            {readOnly
              ? "Cette révision n'est plus modifiable : crée un brouillon pour la chiffrer."
              : "Le brouillon affiché est éditable. Le planning et le devis sont le même arbre."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <PlanningVersionControls
            revisions={revisions}
            selectedRevisionId={selectedRevisionId}
            selectedRevision={selectedRevision}
            referenceRevisionId={referenceRevisionId}
            revisionsBusy={revisionsBusy}
            mutationBusy={mutationBusy}
            isReadOnlyProject={isReadOnlyProject}
            hasConflict={conflict !== null}
            onSelectRevision={onSelectRevision}
            onCreateDraft={onCreateDraft}
            onValidate={onValidateRevision}
            // The lotissement is a planning-side screen: offering it from the devis would send the
            // user to another tab to answer a question this one never asked.
            showReopenStructure={false}
            onReopenStructure={() => {}}
          />
          <Button
            type="button"
            variant="outline"
            disabled={exportBusy || selectedRevisionId === null}
            onClick={onExport}
          >
            {exportBusy ? "Export..." : "Exporter le devis"}
          </Button>
        </div>
      </div>

      <PlanningConflictBanner conflict={conflict} onReload={onReloadConflict} />

      {feedback ? (
        <Alert>
          <AlertDescription>{feedback}</AlertDescription>
        </Alert>
      ) : null}

      {revisionsBusy || treeBusy ? (
        <p className="text-sm text-muted-foreground" role="status">
          Chargement de la révision...
        </p>
      ) : null}

      {showEmptyState ? (
        <p className="py-6 text-sm text-muted-foreground">
          Aucune révision à chiffrer. Importe un planning MS Project ou génère le lotissement depuis
          l&apos;onglet Planning.
        </p>
      ) : null}

      {tree ? (
        <>
          <RevisionTotalsPanel aggregates={aggregates} busy={aggregatesBusy} />

          <EstimateGridTreeTable
            nodes={tree.nodes}
            revisionKey={tree.revision_id}
            readOnly={readOnly}
            mutationBusy={mutationBusy}
            costCategories={costCategories}
            allCostCategories={allCostCategories}
            resourceNodes={resourceNodes}
            resourceRoles={resourceRoles}
            costRates={costRates}
            projectCostCodes={projectCostCodes}
            bulkCostCodeId={bulkCostCodeId}
            onBulkCostCodeIdChange={onBulkCostCodeIdChange}
            bulkAssignBusy={bulkAssignBusy}
            {...writeHandlers}
          />
        </>
      ) : null}
    </div>
  );
}

/**
 * The revision's published figures, and the lines no figure could count.
 *
 * The totals are priced from the cost facets themselves, so a **brouillon** has them -- which is
 * the state a devis is consulted in while it is being built. It is also where "une ligne
 * désindentée jusqu'à la racine reste comptabilisée" is actually visible: a project-wide cost
 * bears no task, and is counted all the same.
 */
function RevisionTotalsPanel({
  aggregates,
  busy,
}: Readonly<{ aggregates: RevisionAggregates | null; busy: boolean }>) {
  const unpriceable = aggregates?.unpriceable_facets ?? [];
  return (
    <>
      <div className="flex flex-wrap gap-4">
        <TotalCard label="Total MO" value={aggregates?.total_labor_cost ?? null} busy={busy} />
        <TotalCard label="Total achats" value={aggregates?.total_purchase_cost ?? null} busy={busy} />
        <TotalCard label="Total déboursé sec" value={aggregates?.total_unburdened_cost ?? null} busy={busy} />
      </div>
      {unpriceable.length ? (
        <Alert>
          <AlertTitle>Lignes non valorisables</AlertTitle>
          <AlertDescription>
            <p>
              {unpriceable.length} ligne(s) de chiffrage ne sont comptées dans aucun total, faute de
              dates sur la tâche qui les porte :
            </p>
            <ul className="mt-1 list-disc pl-4">
              {unpriceable.map((facet) => (
                <li key={facet.node_id}>
                  {facet.label}
                  {facet.bearing_task_name ? ` (${facet.bearing_task_name})` : ""}
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}
    </>
  );
}

/**
 * One published figure of the revision, in euros at the cent as the backend rounded it.
 *
 * A total that could not be read is "—" and never 0: a revision with no chiffrage at all really
 * does total zero euros, and the two must not look alike.
 */
function totalCardText(value: string | null, busy: boolean): string {
  if (value === null) {
    return busy ? "..." : "—";
  }
  const amount = Number(value);
  return Number.isFinite(amount) ? formatEuros(amount) : "—";
}

function TotalCard({ label, value, busy }: Readonly<{ label: string; value: string | null; busy: boolean }>) {
  return (
    <div className="grid min-w-37.5 w-fit gap-0.5 rounded-lg border bg-muted/40 px-4 py-3">
      <strong>{totalCardText(value, busy)}</strong>
      <span>{label}</span>
    </div>
  );
}
