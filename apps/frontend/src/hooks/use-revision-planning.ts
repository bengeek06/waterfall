import { useCallback, useEffect, useRef, useState } from "react";
import type { useRouter } from "next/navigation";

import {
  ApiError,
  SessionExpiredError,
  copyRevision,
  createRevisionCostLine,
  createRevisionTask,
  deleteRevisionNodes,
  getRevisionErrorCode,
  getRevisionLockConflict,
  getRevisionNodes,
  listRevisions,
  moveRevisionNodes,
  replaceRevisionPredecessors,
  updateRevisionCostFacet,
  updateRevisionPlanFacet,
  validateRevision,
  type Revision,
  type RevisionCostFacetUpdateInput,
  type RevisionCostLineCreateInput,
  type RevisionCostLoss,
  type RevisionList,
  type RevisionMoveMode,
  type RevisionNode,
  type RevisionPlanFacetUpdateInput,
  type RevisionPredecessorWrite,
  type RevisionTaskCreateInput,
  type RevisionTree,
} from "@/lib/backend";
import { clearSession, type SessionTokens } from "@/lib/session";

type AppRouter = ReturnType<typeof useRouter>;

/** What a stale `expected_lock_version` came back with, kept until the user reloads. */
export type RevisionLockConflict = {
  revisionId: number | null;
  expectedLockVersion: number | null;
  currentLockVersion: number | null;
};

export type UseRevisionPlanningParams = {
  session: SessionTokens | null;
  projectId: number;
  onSessionRefresh: (next: SessionTokens) => void;
  router: AppRouter;
  setError: (message: string | null) => void;
};

/**
 * Picks the revision to show when the screen has no opinion yet: the draft being worked on, then
 * the reference, then the latest by version number.
 *
 * Mirrors the pointer semantics the backend states (`displayed_revision_id` names the draft on
 * screen and goes back to NULL on validation, the reference is what the project is run against),
 * rather than always opening the last row: a project whose latest revision is somebody's abandoned
 * draft should still open on what it is actually run against when nothing is being worked on.
 */
export function pickRevisionToDisplay(
  revisions: readonly Revision[],
  displayedRevisionId: number | null,
  referenceRevisionId: number | null,
): number | null {
  const exists = (id: number | null) =>
    id !== null && revisions.some((revision) => revision.revision_id === id);
  if (exists(displayedRevisionId)) {
    return displayedRevisionId;
  }
  if (exists(referenceRevisionId)) {
    return referenceRevisionId;
  }
  return revisions.at(-1)?.revision_id ?? null;
}

/**
 * Whether a write that just failed leaves the tree on screen -- or the counter it was read with --
 * stale enough that it has to be re-read.
 *
 * Two ways in:
 *
 * * REVISION_IMMUTABLE: the revision was validated under the user, by another tab or by this one
 *   before the list came back. Re-reading is what actually turns the screen read-only, instead of
 *   leaving an editable table over a revision that refuses every write (INV-03);
 * * a composite write (`rereadOnFailure`): a failure half-way through happens *after* a request
 *   has succeeded, so the server's `lock_version` has moved while the local one has not. Without
 *   the re-read the counter is **guaranteed** stale -- every later write 409s -- over a grid that
 *   does not even show what the first half wrote.
 */
function mustRereadAfterFailure(cause: unknown, rereadOnFailure: boolean): boolean {
  return rereadOnFailure || getRevisionErrorCode(cause) === "REVISION_IMMUTABLE";
}

// E14-10 (#336): every read and every write a screen makes against a revision, in one place --
// the container the page hands to the Planning tab and, since E14-11 (#337), to the Devis tab.
//
// One hook instance for both, deliberately: a revision is one tree, two facets and **one**
// optimistic-lock counter. Giving each tab its own hook would give each its own copy of that
// counter, and the tab that did not write last would send a stale one on its next edit.
//
// Two things shape it, and both come straight from the contract:
//
// * a write answers its new `lock_version` and nothing else, so each one is followed by a re-read
//   of the tree. Patching local state instead would be wrong rather than merely slower:
//   `row_number`, `level` and a cost facet's bearing task are computed on read, so a move changes
//   rows the response never names -- which is exactly what "moving a task moves its cost lines"
//   means here;
// * a stale counter comes back as a 409 REVISION_LOCK_CONFLICT carrying the stored value. It is
//   surfaced as a banner and never auto-retried: the tree the user acted on is not the one the
//   server holds, and replaying the command against a tree they have not seen is how a silent
//   wrong move happens.
export function useRevisionPlanning({
  session,
  projectId,
  onSessionRefresh,
  router,
  setError,
}: UseRevisionPlanningParams) {
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [referenceRevisionId, setReferenceRevisionId] = useState<number | null>(null);
  const [selectedRevisionId, setSelectedRevisionId] = useState<number | null>(null);
  const [tree, setTree] = useState<RevisionTree | null>(null);
  // Starts true whenever a session is already in hand: the list-loading effect below fires on the
  // very first commit, so the first render is not "no revision" but "not asked yet" -- and the
  // screen must not draw an empty state from it (see PlanningTreePanel.showEmptyState).
  //
  // Intentionally not guarded by the test suite: the frame this fixes is the one React paints
  // *before* running the effect, and under jsdom + Testing Library no assertion can observe it --
  // `findBy*` awaits, and by the time it resolves the effect has long since called
  // `setRevisionsBusy(true)`. A test would have to reach into the render internals to fail, and
  // would then assert the implementation rather than the behaviour. It is a browser-only frame.
  const [revisionsBusy, setRevisionsBusy] = useState(session !== null);
  const [treeBusy, setTreeBusy] = useState(false);
  const [mutationBusy, setMutationBusy] = useState(false);
  const [conflict, setConflict] = useState<RevisionLockConflict | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  // A network/unclassified failure (not a session expiry, not a lock conflict) keeps the
  // just-attempted write retryable instead of silently dropping it -- the affordance E4-01
  // introduced, carried over to the revision model.
  const [retryableAction, setRetryableAction] = useState<{
    /** The revision the write was aimed at: replaying it on screen B would write into A. */
    revisionId: number;
    message: string;
    retry: () => void;
  } | null>(null);
  // Guards every awaited result against a selection that moved on meanwhile: without it a slow
  // read of revision A can land after the user switched to B and repaint A's tree under B's header.
  const selectedRevisionIdRef = useRef<number | null>(null);

  const onExpiredSession = useCallback(() => {
    clearSession();
    router.push("/login");
  }, [router]);

  const isSessionExpiry = (cause: unknown) =>
    cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401);

  const reportFailure = useCallback(
    (cause: unknown, fallback: string) => {
      if (isSessionExpiry(cause)) {
        onExpiredSession();
        return;
      }
      const lockConflict = getRevisionLockConflict(cause);
      if (lockConflict) {
        setConflict(lockConflict);
        return;
      }
      setError(cause instanceof ApiError ? cause.message : fallback);
    },
    [onExpiredSession, setError],
  );

  /**
   * Reports a failure that belongs to `revisionId`, and drops it when the screen has moved on.
   *
   * A response can land long after the user switched revisions. Everything `reportFailure` posts
   * -- the lock-conflict banner, which also turns the table read-only, and the error message --
   * names a tree that is no longer displayed, so it is silenced rather than shown against the
   * wrong revision.
   *
   * The session expiry is deliberately **outside** that guard: it is not a statement about a
   * revision at all, and an expired session must log the user out whatever is on screen.
   */
  const reportFailureFor = useCallback(
    (revisionId: number | null, cause: unknown, fallback: string) => {
      if (isSessionExpiry(cause)) {
        onExpiredSession();
        return;
      }
      if (selectedRevisionIdRef.current !== revisionId) {
        return;
      }
      reportFailure(cause, fallback);
    },
    [onExpiredSession, reportFailure],
  );

  const selectRevision = useCallback(
    (revisionId: number | null) => {
      selectedRevisionIdRef.current = revisionId;
      setSelectedRevisionId(revisionId);
      setConflict(null);
      setFeedback(null);
      // An error and a pending retry both describe a write against the revision that *was* on
      // screen. Carried over, the error accuses the newly displayed revision of a failure it had
      // nothing to do with, and the retry would re-send the write to the revision it was built
      // for -- succeeding invisibly, since the re-read that follows is dropped as stale.
      setRetryableAction(null);
      setError(null);
    },
    [setError],
  );

  /**
   * Re-reads the list of revisions, and moves the selection only when it has to (the selected
   * revision disappeared, or nothing was selected yet). `preferredRevisionId` is how a caller that
   * just created one -- a copy, an import -- names the one to land on.
   */
  const refreshRevisions = useCallback(
    async (tokens: SessionTokens, preferredRevisionId?: number | null) => {
      setRevisionsBusy(true);
      try {
        const list = await listRevisions(projectId, tokens, onSessionRefresh);
        setRevisions(list.items);
        setReferenceRevisionId(list.reference_revision_id);
        const current = selectedRevisionIdRef.current;
        const stillThere = list.items.some((revision) => revision.revision_id === current);
        const next =
          preferredRevisionId ??
          (stillThere
            ? current
            : pickRevisionToDisplay(list.items, list.displayed_revision_id, list.reference_revision_id));
        if (next !== current) {
          selectRevision(next);
        }
        return list;
      } finally {
        setRevisionsBusy(false);
      }
    },
    [onSessionRefresh, projectId, selectRevision],
  );

  const readTree = useCallback(
    async (tokens: SessionTokens, revisionId: number) => {
      const loaded = await getRevisionNodes(projectId, revisionId, tokens, onSessionRefresh);
      if (selectedRevisionIdRef.current === revisionId) {
        setTree(loaded);
      }
      return loaded;
    },
    [onSessionRefresh, projectId],
  );

  // The initial list, and every reload of it the page asks for.
  useEffect(() => {
    if (!session) {
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        await refreshRevisions(session);
      } catch (cause) {
        if (cancelled) {
          return;
        }
        reportFailure(cause, "Impossible de charger les révisions du projet.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session, refreshRevisions, reportFailure]);

  // The selected revision's tree.
  useEffect(() => {
    let cancelled = false;
    // Every write below is inside the async body rather than in the effect body itself: clearing
    // the previous tree *is* a state update driven by an external read, and React's
    // set-state-in-effect rule (rightly) refuses the synchronous form.
    void (async () => {
      if (!session || selectedRevisionId === null) {
        setTree(null);
        setTreeBusy(false);
        return;
      }
      // Cleared before the read, so no frame ever shows the previous revision's rows under the
      // newly selected one's header.
      setTree(null);
      setTreeBusy(true);
      try {
        await readTree(session, selectedRevisionId);
      } catch (cause) {
        if (cancelled) {
          return;
        }
        reportFailure(cause, "Impossible de charger la révision.");
      } finally {
        if (!cancelled) {
          setTreeBusy(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session, selectedRevisionId, readTree, reportFailure]);

  /**
   * Runs one write against the selected revision, then re-reads the tree it wrote into.
   *
   * Returns false on any refusal, having already reported it -- callers use that to keep an
   * inline draft visible rather than replacing what the user typed with a stale value.
   */
  async function runWrite<T>(
    write: (tokens: SessionTokens, revisionId: number, lockVersion: number) => Promise<T>,
    fallbackMessage: string,
    // E14-11 (#337): the two knobs a **composite** write needs, and a single request never does.
    //
    // `retryable: false` withholds the retry affordance: switching a cost line's nature creates
    // the replacement *then* deletes the original, so a failure can leave the first half applied
    // -- and replaying the pair from its original `expected_lock_version` would either 409 or
    // create a second replacement. Better no button than one that makes things worse.
    //
    // `rereadOnFailure: true` re-reads the tree even though the write failed. A mid-sequence
    // failure happens *after* a request has succeeded, so the server's `lock_version` has moved
    // while `tree.lock_version` has not: without the re-read the local counter is **guaranteed**
    // stale and every subsequent write 409s, over a grid that does not even show what the first
    // half wrote. The message that names the half-applied state ("supprime la ligne en double")
    // is only true once the duplicate is on screen.
    {
      retryable = true,
      rereadOnFailure = false,
    }: { retryable?: boolean; rereadOnFailure?: boolean } = {},
  ): Promise<T | null> {
    if (!session || !tree || selectedRevisionId === null || mutationBusy) {
      return null;
    }
    const revisionId = selectedRevisionId;
    setMutationBusy(true);
    setError(null);
    setFeedback(null);
    setRetryableAction(null);
    try {
      const result = await write(session, revisionId, tree.lock_version);
      await readTree(session, revisionId);
      return result;
    } catch (cause) {
      reportFailureFor(revisionId, cause, fallbackMessage);
      if (selectedRevisionIdRef.current !== revisionId) {
        // The user moved to another revision while this write was in flight. The success branch
        // above is already guarded (readTree drops a stale tree); everything the failure branch
        // would do -- a conflict banner, an error, a retry affordance -- belongs to a revision
        // that is no longer on screen, so none of it is posted.
        return null;
      }
      if (mustRereadAfterFailure(cause, rereadOnFailure)) {
        // Failure of the re-read itself is swallowed on purpose: the write's own failure is the
        // one the user must read, and stacking a second message over it says nothing more.
        await readTree(session, revisionId).catch(() => undefined);
      }
      // A refusal the server decided (a 4xx carrying a code) is not worth replaying as-is; an
      // unclassified failure -- a dropped connection, a 5xx -- is exactly what a retry is for.
      if (retryable && (!(cause instanceof ApiError) || cause.status >= 500)) {
        setRetryableAction({
          revisionId,
          message: cause instanceof ApiError ? cause.message : fallbackMessage,
          retry: () => void runWrite(write, fallbackMessage),
        });
      }
      return null;
    } finally {
      setMutationBusy(false);
    }
  }

  async function moveNodes(mode: RevisionMoveMode, nodeIds: number[]) {
    if (!nodeIds.length) {
      return;
    }
    await runWrite(
      (tokens, revisionId, lockVersion) =>
        moveRevisionNodes(
          projectId,
          revisionId,
          { expected_lock_version: lockVersion, node_ids: nodeIds, mode },
          tokens,
          onSessionRefresh,
        ),
      "Impossible de déplacer la sélection.",
    );
  }

  async function createTask(payload: Omit<RevisionTaskCreateInput, "expected_lock_version">) {
    await runWrite(
      (tokens, revisionId, lockVersion) =>
        createRevisionTask(
          projectId,
          revisionId,
          { ...payload, expected_lock_version: lockVersion },
          tokens,
          onSessionRefresh,
        ),
      "Impossible de créer la tâche.",
    );
  }

  /**
   * Deletes a selection, its subtree and both facets of every removed node (INV-02), and names
   * the chiffrage the deletion took away rather than letting it disappear silently (Rule 3).
   */
  async function deleteNodes(nodeIds: number[]): Promise<RevisionCostLoss[] | null> {
    const result = await runWrite(
      (tokens, revisionId, lockVersion) =>
        deleteRevisionNodes(
          projectId,
          revisionId,
          { expected_lock_version: lockVersion, node_ids: nodeIds },
          tokens,
          onSessionRefresh,
        ),
      "Impossible de supprimer la sélection.",
    );
    if (!result) {
      return null;
    }
    if (result.cost_losses.length) {
      setFeedback(describeCostLosses(result.cost_losses));
    }
    return result.cost_losses;
  }

  async function updatePlanning(
    nodeId: number,
    payload: Omit<RevisionPlanFacetUpdateInput, "expected_lock_version">,
  ): Promise<boolean> {
    const result = await runWrite(
      (tokens, revisionId, lockVersion) =>
        updateRevisionPlanFacet(
          projectId,
          revisionId,
          nodeId,
          { ...payload, expected_lock_version: lockVersion },
          tokens,
          onSessionRefresh,
        ),
      "Impossible de mettre à jour la planification.",
    );
    return result !== null;
  }

  // --------------------------------------------------------------------------------------------
  // E14-11 (#337): the cost facet's own writes, on the very same tree and the very same counter.
  //
  // They live here rather than in a second hook precisely because there is one tree: a devis write
  // and a planning write share `tree.lock_version`, and two hooks each holding their own copy of it
  // would hand the second screen a counter the first one has already advanced -- a 409 on every
  // other edit, for no reason the user could ever act on.
  // --------------------------------------------------------------------------------------------

  /** Adds a cost line to the revision. `parent_id` absent = at the root, bearing no task. */
  async function createCostLine(
    payload: Omit<RevisionCostLineCreateInput, "expected_lock_version">,
  ): Promise<boolean> {
    const result = await runWrite(
      (tokens, revisionId, lockVersion) =>
        createRevisionCostLine(
          projectId,
          revisionId,
          { ...payload, expected_lock_version: lockVersion },
          tokens,
          onSessionRefresh,
        ),
      "Impossible de créer la ligne de chiffrage.",
    );
    return result !== null;
  }

  /** Partial edit of one node's cost facet; false on any refusal, already reported. */
  async function updateCost(
    nodeId: number,
    payload: Omit<RevisionCostFacetUpdateInput, "expected_lock_version">,
  ): Promise<boolean> {
    const result = await runWrite(
      (tokens, revisionId, lockVersion) =>
        updateRevisionCostFacet(
          projectId,
          revisionId,
          nodeId,
          { ...payload, expected_lock_version: lockVersion },
          tokens,
          onSessionRefresh,
        ),
      "Impossible de mettre à jour la ligne de chiffrage.",
    );
    return result !== null;
  }

  /**
   * Turns an MO line into a non-MO one, or the other way round, by **replacing** it.
   *
   * There is no `nature` to PATCH, and that absence is a contract rather than an oversight: the
   * two natures have disjoint attribute sets (INV-19 ↔ INV-20), so flipping one would have to
   * clear `role_id`/`hours` and fill `cost_type_id`/`cost_category_id`/`unit_cost` (or the
   * reverse) in the same write -- which is another line. So this creates the replacement at the
   * former line's own parent and rank, then deletes the original, both under the same lock.
   *
   * Two consequences the caller has to live with, and which are surfaced rather than hidden:
   *
   * * the node identity changes. A cost node carries no predecessors (INV-17) and the grid holds
   *   nothing else keyed by node id, so nothing else has to follow -- but a node **carrying
   *   children** is refused here rather than silently taking its subtree with it into the
   *   delete's INV-02 cascade;
   * * if the delete half fails, the replacement is already there. That is reported as such, with
   *   what to do about it, instead of a generic failure that leaves two identical lines on screen
   *   with no explanation.
   */
  async function switchCostLineNature(
    node: RevisionNode,
    payload: Omit<RevisionCostLineCreateInput, "expected_lock_version" | "parent_id" | "position">,
  ): Promise<boolean> {
    if (tree?.nodes.some((candidate) => candidate.parent_id === node.node_id)) {
      setError(
        "Cette ligne porte des sous-lignes : changer sa nature la remplace, ce qui supprimerait son sous-arbre. Déplace ou supprime ses sous-lignes d'abord.",
      );
      return false;
    }
    const result = await runWrite(
      async (tokens, revisionId, lockVersion) => {
        const created = await createRevisionCostLine(
          projectId,
          revisionId,
          {
            ...payload,
            // Same parent and same rank: created *at* the original's position, which pushes the
            // original one rank down, and the delete that follows closes the gap back up (INV-05
            // renumbers the siblings). The row therefore stays where the user left it.
            parent_id: node.parent_id,
            position: node.position,
            expected_lock_version: lockVersion,
          },
          tokens,
          onSessionRefresh,
        );
        try {
          return await deleteRevisionNodes(
            projectId,
            revisionId,
            { expected_lock_version: created.lock_version, node_ids: [node.node_id] },
            tokens,
            onSessionRefresh,
          );
        } catch (cause) {
          if (cause instanceof SessionExpiredError) {
            throw cause;
          }
          throw new ApiError(
            cause instanceof ApiError ? cause.status : 500,
            "La ligne a bien été recréée dans l'autre nature, mais l'ancienne n'a pas pu être supprimée : recharge la révision et supprime la ligne en double.",
            // The structured `detail` travels with it, and that is not decoration: dropping it
            // turns a 409 REVISION_LOCK_CONFLICT into an unclassified failure, `getRevisionLockConflict`
            // stops recognising it, and the "Recharger la révision" banner -- the only way out of
            // a desynchronised grid -- never appears.
            cause instanceof ApiError ? cause.detail : undefined,
          );
        }
      },
      "Impossible de changer la nature de la ligne.",
      { retryable: false, rereadOnFailure: true },
    );
    return result !== null;
  }

  /**
   * Assigns one cost code to a selection of cost nodes, in a single locked sequence.
   *
   * The counter is threaded from one request to the next rather than re-read from `tree`: React
   * state does not update between two awaits, so a loop of independent `updateCost` calls would
   * send the same stale `expected_lock_version` every time and 409 from the second line on.
   */
  async function assignCostCode(nodeIds: readonly number[], costCodeId: number | null): Promise<boolean> {
    if (!nodeIds.length) {
      return false;
    }
    const result = await runWrite(
      async (tokens, revisionId, lockVersion) => {
        let currentLockVersion = lockVersion;
        for (const nodeId of nodeIds) {
          const written = await updateRevisionCostFacet(
            projectId,
            revisionId,
            nodeId,
            { expected_lock_version: currentLockVersion, cost_code_id: costCodeId },
            tokens,
            onSessionRefresh,
          );
          currentLockVersion = written.lock_version;
        }
        return currentLockVersion;
      },
      "Impossible d'affecter le code d'imputation à la sélection.",
      // Same reason as switchCostLineNature, on both counts: a failure half-way through has
      // already written the lines before it, so replaying the whole sequence from the original
      // counter would 409 -- and the counter the tree still holds is the one the first line of
      // the sequence already spent, so the tree is re-read before the next write can use it.
      { retryable: false, rereadOnFailure: true },
    );
    return result !== null;
  }

  /** Rejects on failure, so the links dialog can keep itself open and show the message inline. */
  async function replacePredecessors(nodeId: number, predecessors: RevisionPredecessorWrite[]) {
    const result = await runWrite(
      (tokens, revisionId, lockVersion) =>
        replaceRevisionPredecessors(
          projectId,
          revisionId,
          nodeId,
          { expected_lock_version: lockVersion, predecessors },
          tokens,
          onSessionRefresh,
        ),
      "Impossible de mettre à jour les prédécesseurs.",
    );
    if (result === null) {
      throw new Error("La mise à jour des prédécesseurs a échoué.");
    }
  }

  /**
   * Opens a draft reproducing the selected revision and switches to it, leaving the source exactly
   * as it was -- which is what makes this the way to modify a validated revision (INV-03, INV-07).
   */
  async function createDraftFromSelected() {
    if (!session || !tree || selectedRevisionId === null || mutationBusy) {
      return;
    }
    const revisionId = selectedRevisionId;
    setMutationBusy(true);
    setError(null);
    setFeedback(null);
    try {
      const created = await copyRevision(
        projectId,
        revisionId,
        { expected_lock_version: tree.lock_version },
        session,
        onSessionRefresh,
      );
      await refreshRevisions(session, created.revision_id);
      setFeedback(`Brouillon V${created.version_number} créé : la révision d'origine n'a pas changé.`);
    } catch (cause) {
      reportFailureFor(revisionId, cause, "Impossible de créer un brouillon de révision.");
    } finally {
      setMutationBusy(false);
    }
  }

  async function validateSelected() {
    if (!session || !tree || selectedRevisionId === null || mutationBusy) {
      return;
    }
    const revisionId = selectedRevisionId;
    setMutationBusy(true);
    setError(null);
    setFeedback(null);
    try {
      const validated = await validateRevision(
        projectId,
        revisionId,
        { expected_lock_version: tree.lock_version },
        session,
        onSessionRefresh,
      );
      await refreshRevisions(session, revisionId);
      await readTree(session, revisionId);
      setFeedback(
        `Révision V${validated.version_number} validée : elle est désormais en lecture seule (${validated.frozen_line_count} ligne(s) figée(s)).`,
      );
    } catch (cause) {
      reportFailureFor(revisionId, cause, "Impossible de valider la révision.");
    } finally {
      setMutationBusy(false);
    }
  }

  /**
   * Re-reads the list and the tree: what the conflict banner's "Recharger" button does, and what
   * an import calls once it knows which revision it wrote into.
   *
   * Answers the freshly-read list, so a caller can resolve something about the target revision --
   * its version number, say -- without waiting for this hook's own state to have re-rendered.
   */
  async function reload(preferredRevisionId?: number | null): Promise<RevisionList | null> {
    if (!session) {
      return null;
    }
    // Resolved *before* the awaits, so a failure is attributed to the revision this reload aimed
    // at rather than to whichever one happens to be displayed when it comes back.
    const revisionId = preferredRevisionId ?? selectedRevisionIdRef.current ?? null;
    setConflict(null);
    setTreeBusy(true);
    try {
      const list = await refreshRevisions(session, preferredRevisionId);
      // The list may have moved the selection meanwhile: `refreshRevisions` re-selects when the
      // revision that was displayed is gone from the list (deleted, superseded by an import).
      // Re-reading the one this reload aimed at would then be a guaranteed 404 -- a dead request
      // plus a server-side error log -- whose failure `reportFailureFor` drops as stale anyway.
      // The tree the user will actually see is already being read by the selection effect.
      if (revisionId !== null && selectedRevisionIdRef.current === revisionId) {
        await readTree(session, revisionId);
      }
      return list;
    } catch (cause) {
      reportFailureFor(revisionId, cause, "Impossible de recharger la révision.");
      return null;
    } finally {
      setTreeBusy(false);
    }
  }

  const selectedRevision =
    revisions.find((revision) => revision.revision_id === selectedRevisionId) ?? null;

  return {
    revisions,
    selectedRevision,
    selectedRevisionId,
    referenceRevisionId,
    tree,
    revisionsBusy,
    treeBusy,
    mutationBusy,
    conflict,
    feedback,
    retryableAction,
    selectRevision,
    reload,
    moveNodes,
    createTask,
    deleteNodes,
    updatePlanning,
    createCostLine,
    updateCost,
    switchCostLineNature,
    assignCostCode,
    replacePredecessors,
    createDraftFromSelected,
    validateSelected,
  };
}

/**
 * Names what a deletion took away, in the order the backend reported it.
 *
 * Rule 3 again, on the deletion side this time: the amounts are per cost facet and are summed
 * here because these *are* deduplicated -- a node appears once in a cascade's `cost_losses`,
 * unlike an import diff's per-item lists (see planning-import-panel.tsx).
 */
export function describeCostLosses(losses: readonly RevisionCostLoss[]): string {
  // A malformed amount is skipped rather than poisoning the whole sum: `Number("")` and
  // `Number("n/a")` are NaN, and one of them turns the entire total into "NaN €" -- the very
  // silence Rule 3 exists to prevent. Same guard as planning-import-panel.tsx's totalCostLoss.
  const total = losses.reduce((sum, loss) => {
    const amount = Number(loss.amount);
    return Number.isFinite(amount) ? sum + amount : sum;
  }, 0);
  const names = losses.map((loss) => loss.label).join(", ");
  return `Suppression effectuée. ${losses.length} ligne(s) de chiffrage ont été supprimées avec elle (${total.toLocaleString("fr-FR", { style: "currency", currency: "EUR" })}) : ${names}.`;
}
