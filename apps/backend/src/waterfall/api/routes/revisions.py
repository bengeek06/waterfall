"""Both facets of a revision, over HTTP (E14-05 #331, then E14-07 #333).

Replaces the eight endpoints that read and edited a planning through
`wf_planning_task_snapshot` -- the move/create/delete/schedule/links/restore
family of ``plannings.py``, ``GET /planning-tree`` and ``GET /tasks`` -- and, since
#333, the devis-side family that described the same structure a second time:
``GET .../estimates/{id}/task-rows``, ``POST .../estimates/{id}/tasks``,
``POST .../estimates/{id}/grid-nodes/move`` and the whole ``cost-lines`` /
``role-assignments`` CRUD.

Why ``/projects/{project_id}/revisions/{revision_id}/...`` and not ``/plannings``
--------------------------------------------------------------------------------

Because that is what the model says. A node belongs to a revision, and a revision
carries the tree of a version **once**, with the planning and the cost hanging off
the same node (EPIC #326). Keeping a ``/plannings`` prefix would have re-published,
in the URL space, the very duplication this EPIC removes -- and would have left
#333 no place to put the cost facet other than a second, parallel tree. The
structure endpoints below (create, move, delete) are deliberately facet-agnostic
and scoped to ``/nodes``: they are the same operation whichever facet the selected
node carries, which is the whole point.

That is why #333 added **two** endpoints and no more. Creating a cost line needs a
payload of its own (``POST .../cost-lines``, the twin of ``POST .../tasks``) and
editing its attributes needs another (``PATCH .../nodes/{node_id}/cost``); moving
one and deleting one do not, because ``POST .../nodes/move`` and
``POST .../nodes/delete`` already do it -- the latter removes the node, its subtree
and *both* its facets (INV-02), and names the chiffrage it took away. A
``DELETE .../cost-lines/{id}`` would have been that same operation under a second
name.

What is **not** here: the lifecycle of a revision -- creating one, validating it,
pointing the project's reference at it. That is E14-08 (#334), which owns the
``wf_revision`` row itself; this module only ever reads its status and its
``lock_version``.

Every write takes ``expected_lock_version`` and answers with the new one. Every
refusal goes through :mod:`waterfall.api.revision_errors` -- one table for both
facets, so "a validated revision refuses every write" is literally the same
``REVISION_IMMUTABLE`` response whichever facet was aimed at, and "a jalon holds no
children" is the same ``REVISION_MILESTONE_HAS_CHILDREN`` whether a task or a cost
line was hung under it.

Two refusals are decided here rather than there, because they are about the
*project* and not about the revision: ``PROJECT_NOT_FOUND`` (404, also the answer
for a project somebody else owns) and ``PROJECT_READ_ONLY`` (409, a project that is
``perdu``/``termine``/``abandonne``). The second is deliberately **not** INV-03 and
carries its own code: the revision may well be a perfectly editable draft.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user
from waterfall.api.revision_errors import revision_operation
from waterfall.db.session import get_db
from waterfall.domain import revision as domain
from waterfall.models.ms_core import MsProject
from waterfall.models.revision import ProjectRevision
from waterfall.models.user import User
from waterfall.schemas.revisions import (
    RevisionAggregatesRead,
    RevisionCostFacetRead,
    RevisionCostFacetUpdate,
    RevisionCostLineCreate,
    RevisionCostLossRead,
    RevisionMissingRateRead,
    RevisionNodeDelete,
    RevisionNodeDeleteRead,
    RevisionNodeMove,
    RevisionNodeRead,
    RevisionNodeWriteRead,
    RevisionPlanFacetRead,
    RevisionPlanFacetUpdate,
    RevisionPredecessorRead,
    RevisionPredecessorsReplace,
    RevisionTaskCreate,
    RevisionTreeRead,
    RevisionWriteRead,
)
from waterfall.services import revision_tree
from waterfall.services.estimate_calculation import calculate_revision_aggregates
from waterfall.services.project_lifecycle import READ_ONLY_PROJECT_STATUSES

router = APIRouter(prefix="/projects", tags=["projects"])


def _readable_project(db: Session, project_id: int, owner_id: int) -> MsProject:
    """The project the caller owns, or a structured 404.

    Deliberately not the shared ``project_access`` helper: that one raises a
    plain-string ``detail``, which
    :func:`waterfall.main._generic_http_exception_handler` flattens into
    ``GENERIC_ERROR``. Every refusal of this API carries a code a client can act
    on, and "no such project of yours" is no exception.
    """
    project = (
        db.query(MsProject)
        .filter(MsProject.id == project_id, MsProject.owner_id == owner_id)
        .first()
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"code": "PROJECT_NOT_FOUND"}
        )
    return project


def _writable_project(db: Session, project_id: int, owner_id: int) -> MsProject:
    """The project, locked for update and refused when its status is read-only.

    A guard **distinct** from INV-03: a project that is ``perdu``, ``termine`` or
    ``abandonne`` accepts no write at all, whatever the status of the revision
    aimed at. The legacy planning routes carried it through their own mutable-project
    lock; it is restated here so that removing those routes does not quietly remove
    it with them. The row lock is what makes the check hold for the rest of the
    transaction instead of being a read a concurrent status change could invalidate.
    """
    project = (
        db.query(MsProject)
        .filter(MsProject.id == project_id, MsProject.owner_id == owner_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"code": "PROJECT_NOT_FOUND"}
        )
    if project.status in READ_ONLY_PROJECT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": "PROJECT_READ_ONLY"}
        )
    return project


def _get_revision_or_404(db: Session, project_id: int, revision_id: int) -> ProjectRevision:
    """The revision, scoped to the project the caller named.

    Scoped rather than fetched by id alone so that a revision id belonging to
    somebody else's project answers 404 and not the revision: ownership is checked
    on the project, and this is what ties the two together.
    """
    revision = (
        db.query(ProjectRevision)
        .filter(ProjectRevision.id == revision_id, ProjectRevision.project_id == project_id)
        .first()
    )
    if revision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REVISION_NOT_FOUND"},
        )
    return revision


def _to_node_read(row: revision_tree.TreeRow) -> RevisionNodeRead:
    return RevisionNodeRead(
        node_id=row.node_id,
        work_item_id=row.work_item_id,
        kind=row.kind.value,
        parent_id=row.parent_id,
        position=row.position,
        row_number=row.row_number,
        level=row.level,
        external_uid=row.external_uid,
        description=row.description,
        planning=(
            None
            if row.plan is None
            else RevisionPlanFacetRead(
                name=row.plan.name,
                calendar_id=row.plan.calendar_id,
                calendar_source=(
                    None if row.plan.calendar_source is None else row.plan.calendar_source.value
                ),
                is_milestone=row.plan.is_milestone,
                duration_minutes=row.plan.duration_minutes,
                duration_format=row.plan.duration_format,
                start_at=row.plan.start_at,
                finish_at=row.plan.finish_at,
                work_minutes=row.plan.work_minutes,
                percent_complete=row.plan.percent_complete,
                is_manual=row.plan.is_manual,
            )
        ),
        cost=(
            None
            if row.cost is None
            else RevisionCostFacetRead(
                nature=row.cost.nature.value,
                label=row.cost.label,
                quantity=row.cost.quantity,
                role_id=row.cost.role_id,
                hours=row.cost.hours,
                cost_type_id=row.cost.cost_type_id,
                cost_category_id=row.cost.cost_category_id,
                unit_cost=row.cost.unit_cost,
                supply_status=(
                    None if row.cost.supply_status is None else row.cost.supply_status.value
                ),
                planned_date=row.cost.planned_date,
                cost_code_id=row.cost.cost_code_id,
                comment=row.cost.comment,
                bearing_task_node_id=(
                    None if row.bearing_task is None else row.bearing_task.node_id
                ),
                bearing_task_name=(None if row.bearing_task is None else row.bearing_task.name),
            )
        ),
        predecessors=[
            RevisionPredecessorRead(
                predecessor_node_id=link.predecessor_node_id,
                link_type=link.link_type,
                lag_tenth_minute=link.lag_tenth_minute,
                lag_format=link.lag_format,
            )
            for link in row.predecessors
        ],
    )


def _to_tree_read(tree: revision_tree.RevisionTree) -> RevisionTreeRead:
    return RevisionTreeRead(
        revision_id=tree.revision_id,
        project_id=tree.project_id,
        version_number=tree.version_number,
        kind=tree.kind.value,
        status=tree.status.value,
        lock_version=tree.lock_version,
        note=tree.note,
        nodes=[_to_node_read(row) for row in tree.rows],
    )


def _to_write_read(write: revision_tree.TreeWrite) -> RevisionWriteRead:
    return RevisionWriteRead(revision_id=write.revision_id, lock_version=write.lock_version)


@router.get(
    "/{project_id}/revisions/{revision_id}/nodes",
    response_model=RevisionTreeRead,
)
def read_revision_nodes(
    project_id: int,
    revision_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RevisionTreeRead:
    """The whole tree of a revision, depth-first, with its planning facet.

    Deliberately unpaginated, for the reason the endpoint it replaces already gave:
    it feeds an editable tree, which needs every node to reconstruct the hierarchy
    and to number the rows -- a truncated page would produce orphaned parents and a
    ``row_number`` restarting at 1 on every page.
    """
    _readable_project(db, project_id, current_user.id)
    _get_revision_or_404(db, project_id, revision_id)
    with revision_operation(db):
        tree = revision_tree.read_revision_tree(db, revision_id)
    return _to_tree_read(tree)


@router.get(
    "/{project_id}/revisions/{revision_id}/aggregates",
    response_model=RevisionAggregatesRead,
)
def read_revision_aggregates(
    project_id: int,
    revision_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RevisionAggregatesRead:
    """The totals of a revision, computed from its cost facets (E14-07b, #364).

    Replaces ``GET .../estimates/{estimate_id}/aggregates``, which summed the frozen
    ``wf_estimate_line`` rows a validation had written and therefore reported
    nothing at all for a devis still being built. The engine prices the facets
    themselves, so a **draft** has totals -- which is the state the figure is
    actually consulted in.

    A missing ``CostRate``/``InflationRate`` is reported in the body and never
    raised: this is a read, and a 500 would make an editable draft unreadable. See
    :class:`~waterfall.schemas.revisions.RevisionMissingRateRead`.

    Every amount is already in euros at the cent when it gets here: the rounding is
    :func:`~waterfall.services.estimate_calculation.calculate_revision_aggregates`'s,
    applied per priced line before anything is summed, because that -- and not a
    rounding of the five totals at this boundary -- is what the ``Numeric(16, 2)``
    columns of the endpoint this replaces did, and what keeps
    ``total_labor_cost + total_purchase_cost`` equal to ``total_unburdened_cost``.
    So this handler re-publishes the five figures and rounds nothing.
    """
    _readable_project(db, project_id, current_user.id)
    _get_revision_or_404(db, project_id, revision_id)
    with revision_operation(db):
        aggregates = calculate_revision_aggregates(db, revision_id)
    return RevisionAggregatesRead(
        revision_id=revision_id,
        total_labor_cost=aggregates["total_labor_cost"],
        total_purchase_cost=aggregates["total_purchase_cost"],
        total_unburdened_cost=aggregates["total_unburdened_cost"],
        by_category=dict(aggregates["by_category"]),
        by_cost_code=dict(aggregates["by_cost_code"]),
        missing_cost_rates=[
            RevisionMissingRateRead(
                category_id=category.id,
                category_name=category.name,
                accounting_code=category.accounting_code,
                year=year,
            )
            for category, year in aggregates["missing_cost_rates"]
        ],
        missing_inflation_years=list(aggregates["missing_inflation_years"]),
    )


@router.post(
    "/{project_id}/revisions/{revision_id}/tasks",
    response_model=RevisionNodeWriteRead,
    status_code=status.HTTP_201_CREATED,
)
def create_revision_task(
    project_id: int,
    revision_id: int,
    payload: RevisionTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RevisionNodeWriteRead:
    """Create a task node: a new ``work_item`` of kind ``task`` and its plan facet.

    ``calendar_source`` is deliberately *not* computed here: Règle 1 -- "a named
    calendar is pinned as ``manual``, an absent one is inherited from the project as
    ``project``" -- lives in ``domain.revision.tree._apply_calendar_defaults``, which
    every creation path already goes through. Restating it in the transport layer
    would leave the cost facet of #333 free to restate it differently.
    """
    _writable_project(db, project_id, current_user.id)
    _get_revision_or_404(db, project_id, revision_id)
    with revision_operation(db):
        created = revision_tree.add_task(
            db,
            revision_id,
            expected_lock_version=payload.expected_lock_version,
            name=payload.name,
            parent_id=payload.parent_id,
            position=payload.position,
            description=payload.description,
            duration_minutes=payload.duration_minutes,
            is_milestone=payload.is_milestone,
            start_at=payload.start_at,
            finish_at=payload.finish_at,
            calendar_id=payload.calendar_id,
        )
        db.commit()
    return RevisionNodeWriteRead(
        revision_id=created.revision_id,
        lock_version=created.lock_version,
        node_id=created.node_id,
        work_item_id=created.work_item_id,
    )


@router.post(
    "/{project_id}/revisions/{revision_id}/cost-lines",
    response_model=RevisionNodeWriteRead,
    status_code=status.HTTP_201_CREATED,
)
def create_revision_cost_line(
    project_id: int,
    revision_id: int,
    payload: RevisionCostLineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RevisionNodeWriteRead:
    """Create a cost node: a new ``work_item`` of kind ``cost`` and its cost facet.

    The cost-side twin of :func:`create_revision_task`, on the same tree and under the
    same lock. ``parent_id`` absent puts the line at the root, where it is a
    project-wide cost with no bearing task (INV-01, and explicitly allowed).

    No milestone check here, and that absence is the point of #333's third deliverable:
    "a jalon holds no children" is INV-27, it lives in
    ``domain.revision.tree._reject_milestone_parent``, and every insertion path already
    goes through it -- so hanging a cost line under a milestone comes back as a 400
    carrying ``REVISION_MILESTONE_HAS_CHILDREN``. The legacy reconciliation import
    still carries its own ``TASK_PARENT_IS_MILESTONE`` check against ``MsTask``
    (``estimates.py``); this path deliberately does not restate it, because a second
    formulation of one rule is what this EPIC exists to remove.
    """
    _writable_project(db, project_id, current_user.id)
    _get_revision_or_404(db, project_id, revision_id)
    with revision_operation(db):
        created = revision_tree.add_cost_line(
            db,
            revision_id,
            expected_lock_version=payload.expected_lock_version,
            nature=domain.CostNature(payload.nature),
            label=payload.label,
            parent_id=payload.parent_id,
            position=payload.position,
            quantity=payload.quantity,
            role_id=payload.role_id,
            hours=payload.hours,
            cost_type_id=payload.cost_type_id,
            cost_category_id=payload.cost_category_id,
            unit_cost=payload.unit_cost,
            supply_status=(
                None
                if payload.supply_status is None
                else domain.SupplyStatus(payload.supply_status)
            ),
            planned_date=payload.planned_date,
            cost_code_id=payload.cost_code_id,
            comment=payload.comment,
            description=payload.description,
        )
        db.commit()
    return RevisionNodeWriteRead(
        revision_id=created.revision_id,
        lock_version=created.lock_version,
        node_id=created.node_id,
        work_item_id=created.work_item_id,
    )


_MOVES = {
    "up": revision_tree.move_nodes_up,
    "down": revision_tree.move_nodes_down,
    "indent": revision_tree.indent_nodes,
    "outdent": revision_tree.outdent_nodes,
}


@router.post(
    "/{project_id}/revisions/{revision_id}/nodes/move",
    response_model=RevisionWriteRead,
)
def move_revision_nodes(
    project_id: int,
    revision_id: int,
    payload: RevisionNodeMove,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RevisionWriteRead:
    """Move a selection of nodes, whatever facet each of them carries."""
    _writable_project(db, project_id, current_user.id)
    _get_revision_or_404(db, project_id, revision_id)
    with revision_operation(db):
        shift = _MOVES.get(payload.mode)
        if shift is None:
            moved = revision_tree.move_nodes(
                db,
                revision_id,
                payload.node_ids,
                expected_lock_version=payload.expected_lock_version,
                target_parent_id=payload.target_parent_id,
                position=payload.position,
            )
        else:
            moved = shift(
                db,
                revision_id,
                payload.node_ids,
                expected_lock_version=payload.expected_lock_version,
            )
        db.commit()
    return _to_write_read(moved)


@router.post(
    "/{project_id}/revisions/{revision_id}/nodes/delete",
    response_model=RevisionNodeDeleteRead,
)
def delete_revision_nodes(
    project_id: int,
    revision_id: int,
    payload: RevisionNodeDelete,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RevisionNodeDeleteRead:
    """Delete a selection, its whole subtree and both facets of every node removed."""
    _writable_project(db, project_id, current_user.id)
    _get_revision_or_404(db, project_id, revision_id)
    with revision_operation(db):
        deleted = revision_tree.delete_nodes(
            db,
            revision_id,
            payload.node_ids,
            expected_lock_version=payload.expected_lock_version,
        )
        db.commit()
    return RevisionNodeDeleteRead(
        revision_id=deleted.revision_id,
        lock_version=deleted.lock_version,
        removed_node_ids=list(deleted.removed_node_ids),
        cost_losses=[
            RevisionCostLossRead(
                node_id=loss.node_id,
                work_item_id=loss.work_item_id,
                label=loss.label,
                nature=loss.nature.value,
                amount=loss.amount,
                bearing_task_name=loss.bearing_task_name,
            )
            for loss in deleted.cost_losses
        ],
    )


@router.patch(
    "/{project_id}/revisions/{revision_id}/nodes/{node_id}/planning",
    response_model=RevisionWriteRead,
)
def update_revision_plan_facet(
    project_id: int,
    revision_id: int,
    node_id: int,
    payload: RevisionPlanFacetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RevisionWriteRead:
    """Edit a node's planning facet: duration, dates, avancement, calendar.

    Partial: ``model_fields_set`` is what decides whether a field was supplied, not
    "is not None" -- ``null`` is a legitimate value here (clear the duration, drop
    the calendar override), and the two must not be confused.

    The four fields that have *no* cleared state (``name``, ``percent_complete``,
    ``is_milestone``, ``is_manual``) are guarded one layer up, by
    :meth:`~waterfall.schemas.revisions.RevisionPlanFacetUpdate.validate_no_null_on_mandatory_fields`:
    an explicit ``null`` on them is a 422, not a silent no-op. So "supplied" and
    "not ``None``" coincide here for them, and this handler needs no second rule.

    A body carrying nothing but ``expected_lock_version`` is legal and is *not* a
    no-op: it bumps ``lock_version`` by one, because the counter records "a write
    happened", and making it conditional would let two clients holding the same
    value both succeed.
    """
    _writable_project(db, project_id, current_user.id)
    _get_revision_or_404(db, project_id, revision_id)
    supplied = payload.model_fields_set
    with revision_operation(db):
        updated = revision_tree.update_plan_facet(
            db,
            revision_id,
            node_id,
            expected_lock_version=payload.expected_lock_version,
            # The ``is not None`` halves below narrow ``str | None`` down to the
            # ``str | Unset`` the service takes; they are not a rule. The rule -- "no
            # explicit null on these four" -- is the schema's, and answers 422.
            name=payload.name if "name" in supplied and payload.name is not None else domain.UNSET,
            duration_minutes=(
                payload.duration_minutes if "duration_minutes" in supplied else domain.UNSET
            ),
            duration_format=(
                payload.duration_format if "duration_format" in supplied else domain.UNSET
            ),
            start_at=payload.start_at if "start_at" in supplied else domain.UNSET,
            finish_at=payload.finish_at if "finish_at" in supplied else domain.UNSET,
            work_minutes=payload.work_minutes if "work_minutes" in supplied else domain.UNSET,
            percent_complete=(
                payload.percent_complete
                if "percent_complete" in supplied and payload.percent_complete is not None
                else domain.UNSET
            ),
            is_milestone=(
                payload.is_milestone
                if "is_milestone" in supplied and payload.is_milestone is not None
                else domain.UNSET
            ),
            is_manual=(
                payload.is_manual
                if "is_manual" in supplied and payload.is_manual is not None
                else domain.UNSET
            ),
            calendar_id=payload.calendar_id if "calendar_id" in supplied else domain.UNSET,
        )
        db.commit()
    return _to_write_read(updated)


@router.put(
    "/{project_id}/revisions/{revision_id}/nodes/{node_id}/predecessors",
    response_model=RevisionWriteRead,
)
def replace_revision_predecessors(
    project_id: int,
    revision_id: int,
    node_id: int,
    payload: RevisionPredecessorsReplace,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RevisionWriteRead:
    """Replace every predecessor of a task node. An empty list clears them."""
    _writable_project(db, project_id, current_user.id)
    _get_revision_or_404(db, project_id, revision_id)
    with revision_operation(db):
        replaced = revision_tree.replace_predecessors(
            db,
            revision_id,
            node_id,
            [
                domain.NodeLink(
                    node_id=node_id,
                    predecessor_node_id=predecessor.predecessor_node_id,
                    link_type=predecessor.link_type,
                    lag_tenth_minute=predecessor.lag_tenth_minute,
                    lag_format=predecessor.lag_format,
                )
                for predecessor in payload.predecessors
            ],
            expected_lock_version=payload.expected_lock_version,
        )
        db.commit()
    return _to_write_read(replaced)


@router.patch(
    "/{project_id}/revisions/{revision_id}/nodes/{node_id}/cost",
    response_model=RevisionWriteRead,
)
def update_revision_cost_facet(
    project_id: int,
    revision_id: int,
    node_id: int,
    payload: RevisionCostFacetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RevisionWriteRead:
    """Edit a node's cost facet: label, quantité, débours, rôle, heures, suivi appro.

    Partial in exactly the way :func:`update_revision_plan_facet` is, and read the same
    way: ``model_fields_set`` decides whether a field was supplied, because ``null`` is
    a legitimate value here (clear the planned date, drop the cost code). The two
    fields with no cleared state -- ``label`` and ``quantity`` -- are guarded one layer
    up by
    :meth:`~waterfall.schemas.revisions.RevisionCostFacetUpdate.validate_no_null_on_mandatory_fields`,
    which answers 422 rather than letting a ``null`` become a silent no-op.

    ``nature`` is not editable: see
    :class:`~waterfall.schemas.revisions.RevisionCostFacetUpdate`.

    A body carrying nothing but ``expected_lock_version`` is legal and bumps
    ``lock_version`` by one, for the reason the planning facet gives: the counter
    records "a write happened".
    """
    _writable_project(db, project_id, current_user.id)
    _get_revision_or_404(db, project_id, revision_id)
    supplied = payload.model_fields_set
    with revision_operation(db):
        updated = revision_tree.update_cost_facet(
            db,
            revision_id,
            node_id,
            expected_lock_version=payload.expected_lock_version,
            # As on the planning facet, the ``is not None`` halves narrow the declared
            # ``T | None`` down to the ``T | Unset`` the service takes; the rule -- "no
            # explicit null on these two" -- is the schema's, and answers 422.
            label=(
                payload.label if "label" in supplied and payload.label is not None else domain.UNSET
            ),
            quantity=(
                payload.quantity
                if "quantity" in supplied and payload.quantity is not None
                else domain.UNSET
            ),
            role_id=payload.role_id if "role_id" in supplied else domain.UNSET,
            hours=payload.hours if "hours" in supplied else domain.UNSET,
            cost_type_id=payload.cost_type_id if "cost_type_id" in supplied else domain.UNSET,
            cost_category_id=(
                payload.cost_category_id if "cost_category_id" in supplied else domain.UNSET
            ),
            unit_cost=payload.unit_cost if "unit_cost" in supplied else domain.UNSET,
            supply_status=(
                (
                    None
                    if payload.supply_status is None
                    else domain.SupplyStatus(payload.supply_status)
                )
                if "supply_status" in supplied
                else domain.UNSET
            ),
            planned_date=payload.planned_date if "planned_date" in supplied else domain.UNSET,
            cost_code_id=payload.cost_code_id if "cost_code_id" in supplied else domain.UNSET,
            comment=payload.comment if "comment" in supplied else domain.UNSET,
        )
        db.commit()
    return _to_write_read(updated)
