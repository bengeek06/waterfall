import type { RevisionNode, RevisionPlanFacet } from "./backend";
import { buildRevisionTreeRows, siblingsByParent, type RevisionTreeRow } from "./revision-tree";

// E14-10 (#336): what is left of this module once the tree itself moved to the revision model.
//
// Two thirds of it are gone rather than rewritten. `buildPlanningTreeRows` disappeared because
// `GET .../revisions/{id}/nodes` already answers an ordered tree with `row_number` and `level`
// (see lib/revision-tree.ts), and the three command builders -- computeIndentCommand,
// computeOutdentCommand, computeReorderCommand -- disappeared because the destination of a move
// is no longer the client's to compute: `POST .../nodes/move` carries the modes `up`, `down`,
// `indent` and `outdent` and works them out itself. That was not a simplification for its own
// sake: the outdent semantics changed with #344 (the displayed row order is preserved and the
// following siblings become the outdented node's children), and a client still building the old
// destination would have silently produced a different tree.
//
// What stays is the one thing the client still has to know: **whether a command can be asked for
// at all**, so a disabled button explains itself instead of leaving the user to discover a 400.

/** A task row: a revision node of kind `task`, whose planning facet is therefore never null. */
export type PlanningRow = RevisionTreeRow & { planning: RevisionPlanFacet };

/** The task rows of a revision, in the depth-first order the server sent them. */
export function buildPlanningRows(nodes: readonly RevisionNode[]): PlanningRow[] {
  return buildRevisionTreeRows(nodes, ["task"]).filter(
    (row): row is PlanningRow => row.planning !== null,
  );
}

/**
 * Mirrors the domain's `selection_roots`: a node whose ancestor is also selected is dropped, since
 * moving the ancestor already carries it along. Order follows the display order.
 *
 * Recomputed here even though the backend normalises the selection itself, because the *enablement*
 * of each command is decided on the roots -- a selection of a parent and its child is a single
 * root, and is perfectly movable.
 *
 * `nodes` is the revision's **complete** node list, for the same reason the sibling model below
 * is: an ancestor chain walked over a kind-filtered set can stop short of a parent that was
 * filtered out, and a node would then be reported as its own root.
 */
export function normalizeSelectionToRoots<TNode extends { node_id: number; parent_id: number | null }>(
  nodes: readonly TNode[],
  selectedNodeIds: ReadonlySet<number>,
): TNode[] {
  const nodesById = new Map(nodes.map((node) => [node.node_id, node]));
  function hasSelectedAncestor(node: TNode): boolean {
    let parentId = node.parent_id;
    while (parentId !== null) {
      if (selectedNodeIds.has(parentId)) {
        return true;
      }
      parentId = nodesById.get(parentId)?.parent_id ?? null;
    }
    return false;
  }
  return nodes.filter((node) => selectedNodeIds.has(node.node_id) && !hasSelectedAncestor(node));
}

/** The four sibling-level commands the move endpoint exposes, as the toolbar offers them. */
export type PlanningMoveMode = "up" | "down" | "indent" | "outdent";

/** Why a command cannot be asked for. */
export type PlanningMoveRefusal =
  | "empty-selection"
  | "mixed-parents"
  | "not-contiguous"
  | "at-first-position"
  | "at-last-position"
  | "already-at-root"
  | "cost-parent"
  | "milestone-parent"
  | "milestone-children";

/**
 * What to say about a refusal, for the refusals worth saying anything about.
 *
 * **A refusal carries a message if and only if it is announced** (`EXPLAINED_MOVE_REFUSALS` is
 * literally this object's key set), so there is no such thing here as copy that no screen can
 * ever display -- which a later reader would take for coverage it is not.
 *
 * The four refusals deliberately absent -- `empty-selection`, `at-first-position`,
 * `at-last-position`, `already-at-root` -- are the ones the table already shows: the user can see
 * that nothing is selected, or that the selected row is the first/last/topmost of its level, and a
 * greyed-out button is then the whole explanation. The five kept are the ones whose cause is
 * *elsewhere*: the two `milestone-*` (INV-27, #343) and `cost-parent` (INV-14) come from a rule
 * about another row -- a flag carried by a sibling, or for `cost-parent` a sibling the planning
 * table does not even render -- and `mixed-parents`/`not-contiguous` grey out all four buttons at
 * once after a Ctrl+click that looks perfectly reasonable on screen.
 */
const REFUSAL_MESSAGES: Partial<Record<PlanningMoveRefusal, string>> = {
  "mixed-parents": "Les lignes sélectionnées n'ont pas le même parent : déplace-les un niveau à la fois.",
  "not-contiguous": "La sélection doit former un bloc de lignes voisines.",
  "cost-parent":
    "La ligne précédente est une ligne de chiffrage : un chiffrage ne porte aucune tâche.",
  "milestone-parent": "La ligne précédente est un jalon : un jalon ne porte aucune ligne enfant.",
  "milestone-children":
    "Ce jalon est suivi d'autres lignes de son niveau : les désindenter lui rattacherait ces lignes, or un jalon ne porte aucune ligne enfant.",
};

export type PlanningMoveAvailability = {
  enabled: boolean;
  refusal: PlanningMoveRefusal | null;
  /** Ready-to-display French sentence, or null when the command is available. */
  reason: string | null;
};

const AVAILABLE: PlanningMoveAvailability = { enabled: true, refusal: null, reason: null };

function refuse(refusal: PlanningMoveRefusal): PlanningMoveAvailability {
  return { enabled: false, refusal, reason: REFUSAL_MESSAGES[refusal] ?? null };
}

/** The contiguous sibling block a command applies to, once the selection has been normalised. */
type SelectionBlock = {
  /** The **complete** sibling set, tasks and cost nodes alike -- see `selectionBlock` below. */
  siblings: readonly RevisionNode[];
  parentId: number | null;
  firstIndex: number;
  lastIndex: number;
  /** Whether the block carries at least one task, which is what makes a cost parent illegal. */
  carriesTask: boolean;
};

/**
 * The block the selection designates, or the refusal that makes every sibling-level command
 * impossible. Shared by the four modes, because the domain applies these three guards
 * (`selection_roots`, `_common_parent`, `_contiguous_indexes`) to all of them alike.
 */
function selectionBlock(
  nodes: readonly RevisionNode[],
  selectedNodeIds: ReadonlySet<number>,
): { block: SelectionBlock } | { refusal: PlanningMoveRefusal } {
  const roots = normalizeSelectionToRoots(nodes, selectedNodeIds);
  if (!roots.length) {
    return { refusal: "empty-selection" };
  }
  const parentId = roots[0].parent_id;
  if (roots.some((root) => root.parent_id !== parentId)) {
    return { refusal: "mixed-parents" };
  }
  const siblings = siblingsByParent(nodes).get(parentId) ?? [];
  const rootIds = new Set(roots.map((root) => root.node_id));
  const indexes = siblings
    .map((sibling, index) => (rootIds.has(sibling.node_id) ? index : -1))
    .filter((index) => index >= 0);
  if (!indexes.length) {
    return { refusal: "empty-selection" };
  }
  const firstIndex = Math.min(...indexes);
  const lastIndex = Math.max(...indexes);
  if (lastIndex - firstIndex + 1 !== indexes.length) {
    return { refusal: "not-contiguous" };
  }
  const carriesTask = roots.some((root) => root.kind === "task");
  return { block: { siblings, parentId, firstIndex, lastIndex, carriesTask } };
}

function indentAvailability(block: SelectionBlock): PlanningMoveAvailability {
  if (block.firstIndex === 0) {
    return refuse("at-first-position");
  }
  const newParent = block.siblings[block.firstIndex - 1];
  // INV-14: a cost node holds no task. Worth its own refusal rather than being folded into the
  // jalon one, because the planning table does not render the offending sibling at all -- the
  // row above the selection *on screen* is a task, and the user has no way to guess otherwise.
  if (newParent.kind === "cost" && block.carriesTask) {
    return refuse("cost-parent");
  }
  // The preceding sibling becomes the new parent, and a jalon is a dated point, not a container.
  return newParent.planning?.is_milestone ? refuse("milestone-parent") : AVAILABLE;
}

function outdentAvailability(block: SelectionBlock): PlanningMoveAvailability {
  if (block.parentId === null) {
    return refuse("already-at-root");
  }
  // Règle 5 (#344): an outdent preserves the displayed row order, so the siblings that followed
  // the block keep their rank by hanging under its **last** node. When that node is a jalon and
  // something follows it, the command would make a jalon a parent, which INV-27 refuses -- so the
  // jalon is simply not outdentable there, and the user is told why rather than shown a 400.
  //
  // "Something follows it" is counted over the complete sibling set: a cost line following a
  // jalon is a child-to-be just like a task, and it is INV-27's business all the same.
  const lastOutdented = block.siblings[block.lastIndex];
  const following = block.siblings.slice(block.lastIndex + 1);
  // INV-14, symmetrically to `indentAvailability` above: the same relocation hands the following
  // siblings to `last_outdented`, so a *cost* node there with a task behind it is refused by
  // `_validate_move_target` exactly as an indent under a cost node is. Unreachable from the
  // planning table (only tasks are selectable there, so the last outdented node is always a
  // task); reachable from the devis grid (#337), which selects cost rows and shares this guard.
  //
  // The message names the indent case ("la ligne précédente"), which is the only one a browser
  // can reach today; #337 will want its own wording for this one.
  if (lastOutdented.kind === "cost" && following.some((sibling) => sibling.kind === "task")) {
    return refuse("cost-parent");
  }
  return lastOutdented.planning?.is_milestone && following.length > 0
    ? refuse("milestone-children")
    : AVAILABLE;
}

/**
 * The refusals a screen must *say out loud* instead of merely greying a button out: exactly those
 * `REFUSAL_MESSAGES` has a sentence for, and derived from it so the two can never drift apart.
 *
 * See that object for which refusals are in, which are out, and why.
 */
export const EXPLAINED_MOVE_REFUSALS: ReadonlySet<PlanningMoveRefusal> = new Set(
  Object.keys(REFUSAL_MESSAGES) as PlanningMoveRefusal[],
);

/**
 * Whether `mode` can be asked for on the current selection, and why not when it cannot.
 *
 * A transcription of the guards the domain applies (`_common_parent`, `_contiguous_indexes`,
 * `indent_nodes`, `outdent_nodes`, `_validate_move_target`, `_reject_milestone_parent`): it
 * decides *whether* a command is legal, never *where* it lands, which stays server-side. The
 * backend remains the authority -- a refusal missing here costs a 400 the user could have been
 * spared, never a write the domain would not have accepted.
 *
 * ## Contract: `nodes` is the revision's **complete** node list
 *
 * Not the rows a table renders. Every sibling-level guard of the domain runs on `children_of()`,
 * which orders tasks **and** cost nodes together, and INV-05 numbers `position` 1..n over that
 * same set. A task may carry sub-tasks and cost lines at once, so a kind-filtered list produces
 * a different rank for the same node -- and then the toolbar enables an indent the backend
 * answers with a 400, or disables a "Descendre" the backend would have accepted.
 *
 * This is stated as a contract rather than left implicit because both tables of the revision
 * model call it: the planning table renders `task` rows only and passes `tree.nodes` here, while
 * the devis grid (#337) renders the whole tree and passes the very same array to both. The
 * function never looks at what is rendered, so neither caller has to fork it.
 */
export function planningMoveAvailability(
  nodes: readonly RevisionNode[],
  selectedNodeIds: ReadonlySet<number>,
  mode: PlanningMoveMode,
): PlanningMoveAvailability {
  const outcome = selectionBlock(nodes, selectedNodeIds);
  if ("refusal" in outcome) {
    return refuse(outcome.refusal);
  }
  const block = outcome.block;
  switch (mode) {
    case "up":
      return block.firstIndex === 0 ? refuse("at-first-position") : AVAILABLE;
    case "down":
      return block.lastIndex === block.siblings.length - 1 ? refuse("at-last-position") : AVAILABLE;
    case "indent":
      return indentAvailability(block);
    case "outdent":
      return outdentAvailability(block);
    default: {
      // `mode` is `never` here, deliberately: `RevisionMoveMode` already carries a `to_parent`
      // the toolbar does not offer yet, and a mode added to `PlanningMoveMode` without its own
      // guard must break the build rather than inherit the outdent one silently. If one ever
      // reaches this at runtime it is refused, never enabled by default.
      const unhandled: never = mode;
      return refuse(unhandled);
    }
  }
}
