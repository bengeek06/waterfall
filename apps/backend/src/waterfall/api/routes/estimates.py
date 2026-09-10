# pyright: reportPrivateUsage=false

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user
from waterfall.api.pagination import ListParams, list_params
from waterfall.api.routes.planning_support import (
    _PlanningTaskBodyValidationRoute,
    order_snapshots_depth_first,
)
from waterfall.api.routes.project_access import (
    get_displayed_draft_planning_lock_or_409,
    get_mutable_project_lock,
    get_planning_or_404,
    get_project_or_404,
    raise_on_estimate_revision_conflict,
)
from waterfall.api.routes.project_cost_codes import resolve_cost_code_id
from waterfall.api.routes.projects import (
    get_draft_estimate_or_409,
    get_estimate_or_404,
    get_non_labor_category_or_400,
    to_estimate_cost_line_read,
    to_estimate_role_assignment_read,
    to_estimate_task_row_read,
    to_project_estimate_read,
    to_project_read,
)
from waterfall.core.config import get_settings
from waterfall.db.session import get_db
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanning, WfPlanningTaskSnapshot
from waterfall.models.resources import (
    CostCategory,
    CostType,
    Estimate,
    EstimateCostLine,
    EstimateGridNode,
    EstimateLine,
    EstimateRoleAssignment,
    EstimateTaskRow,
    ProjectCostCode,
    ResourceRole,
)
from waterfall.models.user import User
from waterfall.models.wf_core import WfChargeLine
from waterfall.schemas.projects import (
    EstimateAggregatesRead,
    EstimateCostLineCreate,
    EstimateCostLineListRead,
    EstimateCostLineMilestonesCreate,
    EstimateCostLineRead,
    EstimateCostLineUpdate,
    EstimateGridNodeMove,
    EstimateRoleAssignmentCreate,
    EstimateRoleAssignmentListRead,
    EstimateRoleAssignmentRead,
    EstimateRoleAssignmentUpdate,
    EstimateTaskCreate,
    EstimateTaskRowListRead,
    EstimateTaskRowRead,
    EstimateValidationRead,
    FastAPIErrorResponse,
    MilestoneTemplate,
    MissingRateCoverage,
    PlanningTaskCreate,
    PlanningTaskDelete,
    PlanningTaskDeleteConflict,
    ProjectEstimateCreate,
    ProjectEstimateListRead,
    ProjectEstimateRead,
    ProjectRead,
    ReconciliationIssue,
    ReconciliationPlanRead,
    TaskLinkWrite,
)
from waterfall.schemas.resources import CostTypeKind
from waterfall.services import (
    CostLineFileRow,
    EstimateGridInvariantError,
    EstimateGridMoveError,
    EstimateGridMoveNotFoundError,
    EstimateReconciliationFormatError,
    LaborFileRow,
    MissingRateCoverageError,
    ParsedReconciliationWorkbook,
    PlanningLinkError,
    PlanningLinkInvariantError,
    PlanningLinkNotFoundError,
    PlanningTreeCascadeConfirmationRequiredError,
    PlanningTreeInvariantError,
    PlanningTreeMoveError,
    PlanningTreeMoveNotFoundError,
    PlanningTreeTaskReferencedError,
    ResolvedTaskDisplay,
    TaskFileRow,
    apply_pagination,
    build_estimate_reconciliation_workbook,
    build_estimate_workbook,
    calculate_estimate_aggregates,
    calculate_estimate_lines,
    collect_missing_rate_coverage,
    create_estimate_grid_node,
    create_planning_task,
    delete_planning_tasks,
    get_estimate_validation_warnings,
    missing_rate_coverage_detail,
    move_estimate_grid_nodes,
    parse_estimate_reconciliation_workbook,
    replace_task_predecessor_links,
    resolve_live_task_display,
    resolve_task_uid_by_id,
    sync_task_role_assignments_from_estimate,
)
from waterfall.services.estimate_reconciliation_export import _scoped_estimate_role_assignments
from waterfall.services.project_lifecycle import ensure_project_mutable

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/{project_id}/estimates", response_model=ProjectEstimateListRead)
def list_project_estimates(
    project_id: int,
    params: ListParams = Depends(list_params),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectEstimateListRead:
    get_project_or_404(db, project_id, current_user.id)
    query = db.query(Estimate).filter(Estimate.project_id == project_id)
    result = apply_pagination(
        query,
        params,
        sortable={
            "version_number": Estimate.version_number,
            "kind": Estimate.kind,
            "status": Estimate.status,
            "created_at": Estimate.created_at,
        },
        searchable=[Estimate.note],
        default_sort=Estimate.version_number,
        tiebreaker=Estimate.id,
    )
    return ProjectEstimateListRead(
        items=[to_project_estimate_read(estimate) for estimate in result.rows],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post(
    "/{project_id}/estimates",
    response_model=ProjectEstimateRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project_estimate(
    project_id: int,
    payload: ProjectEstimateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectEstimateRead:
    project = get_mutable_project_lock(db, project_id, current_user.id)
    if payload.kind == "forecast_remaining" and payload.reference_estimate_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Forecast remaining estimate requires a reference estimate",
        )
    if payload.reference_estimate_id is not None:
        get_estimate_or_404(db, project_id, payload.reference_estimate_id)

    current_version = (
        db.query(func.max(Estimate.version_number))
        .filter(Estimate.project_id == project_id)
        .scalar()
    )
    estimate = Estimate(
        project_id=project_id,
        planning_id=project.displayed_planning_id,
        reference_estimate_id=payload.reference_estimate_id,
        version_number=(current_version or 0) + 1,
        kind=payload.kind,
        status="draft",
        currency_code=payload.currency_code.upper(),
        note=payload.note,
    )
    db.add(estimate)
    db.flush()

    source_planning = (
        get_planning_or_404(db, project_id, project.displayed_planning_id)
        if project.displayed_planning_id is not None
        else None
    )
    snapshots = (
        order_snapshots_depth_first(
            db.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == source_planning.id)
            .all()
        )
        if source_planning is not None
        else []
    )
    legacy_tasks = db.query(MsTask).filter(MsTask.project_id == project_id).all()
    task_by_uid = {task.uid: task for task in legacy_tasks}
    tasks = snapshots or legacy_tasks
    task_id_by_uid = {
        task.uid: task_by_uid[task.uid].id for task in snapshots if task.uid in task_by_uid
    }
    rows: list[EstimateTaskRow] = []
    for position, task in enumerate(tasks, start=1):
        parent_id = (
            task_id_by_uid.get(task.parent_uid)
            if source_planning is not None and task.parent_uid is not None
            else None
        )
        task_id = (
            task_by_uid[task.uid].id
            if source_planning is not None and task.uid in task_by_uid
            else None
            if source_planning is not None
            else task.id
        )
        rows.append(
            EstimateTaskRow(
                estimate_id=estimate.id,
                task_id=task_id,
                parent_task_id=parent_id,
                position=position,
                task_name=task.name,
                outline_number=task.outline_number,
                outline_level=task.outline_level,
                is_milestone=task.is_milestone,
            )
        )
    db.add_all(rows)
    db.commit()
    db.refresh(estimate)
    return to_project_estimate_read(estimate)


@router.get("/{project_id}/estimates/{estimate_id}", response_model=ProjectEstimateRead)
def get_project_estimate(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectEstimateRead:
    get_project_or_404(db, project_id, current_user.id)
    return to_project_estimate_read(get_estimate_or_404(db, project_id, estimate_id))


@router.post(
    "/{project_id}/estimates/{estimate_id}/validate",
    response_model=EstimateValidationRead,
    responses={
        status.HTTP_409_CONFLICT: {
            "model": MissingRateCoverage | FastAPIErrorResponse,
            "description": (
                "Devis non brouillon (detail generique), ou au moins une "
                "(categorie de cout, annee) couverte par une affectation de "
                "main-d'oeuvre sans CostRate/InflationRate (detail.code="
                "MISSING_RATE_COVERAGE, E6-11/#175) -- dans ce dernier cas, "
                "aucune EstimateLine n'est persistee et le devis reste un "
                "brouillon"
            ),
        },
    },
)
def validate_project_estimate(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateValidationRead:
    project = get_mutable_project_lock(db, project_id, current_user.id)
    estimate = get_estimate_or_404(db, project_id, estimate_id)
    if estimate.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Estimate is not a draft")
    try:
        estimate_lines = calculate_estimate_lines(db, estimate_id)
    except MissingRateCoverageError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=missing_rate_coverage_detail(
                exc.missing_cost_rates, exc.missing_inflation_years
            ),
        ) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    # Issue #65 (E6-04): computed from the same in-progress transaction, before commit,
    # so it reflects the estimate/cost-lines state actually being validated -- never a
    # state read back after some later, unrelated write.
    warnings = get_estimate_validation_warnings(db, project_id, estimate_id)
    db.add_all(estimate_lines)
    db.flush()
    # E12-02/#274: resynchronize the legacy, project-wide TaskRoleAssignment from
    # this estimate's own EstimateRoleAssignment rows -- in the same transaction
    # as the calculation above, so a later failure in this function never commits
    # a status change without the matching resync, or vice versa.
    try:
        sync_task_role_assignments_from_estimate(db, project_id, estimate_id)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Role assignment synchronization conflicts with existing data",
        ) from exc
    # Issue #290 (E12-08) Finding Moyenne #3, round 4 review: freeze each
    # EstimateTaskRow's task-derived columns to the *live* state seen right now,
    # in the same transaction as (and immediately before) the status flip below --
    # not the state they had back at row-creation time. A task renamed/moved one
    # or more times while this devis was still a draft must validate with its
    # last-seen name/position, mirroring the same "freeze at validation, not
    # creation" rule this same EPIC already applies to a root labor line's own
    # pricing (calculate_estimate_lines). A row silently kept as-is when
    # resolve_live_task_display omits it (no task_id, or a task_id that can no
    # longer be resolved live) -- the same pre-existing degenerate fallback its
    # own docstring documents.
    task_rows = db.query(EstimateTaskRow).filter(EstimateTaskRow.estimate_id == estimate_id).all()
    resolved_by_row_id = resolve_live_task_display(db, project, task_rows)
    for task_row in task_rows:
        resolved = resolved_by_row_id.get(task_row.id)
        if resolved is None:
            continue
        task_row.task_name = resolved.task_name
        task_row.outline_number = resolved.outline_number
        task_row.outline_level = resolved.outline_level
        task_row.parent_task_id = resolved.parent_task_id
        task_row.position = resolved.position
        db.add(task_row)

    estimate.status = "validated"
    estimate.validated_at = datetime.now(UTC)
    db.add(estimate)
    # Issue #262: build the full response while the row locks are still held,
    # commit last -- never the commit-then-refresh pattern this function used
    # to follow. Every field to_project_estimate_read needs is already in
    # memory from the status/validated_at assignments above.
    db.flush()
    response = EstimateValidationRead(
        **to_project_estimate_read(estimate).model_dump(),
        warnings=warnings,
    )
    db.commit()
    return response


@router.post("/{project_id}/estimates/{estimate_id}/reference", response_model=ProjectRead)
def set_estimate_reference(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    project = get_project_or_404(db, project_id, current_user.id)
    ensure_project_mutable(project)
    estimate = get_estimate_or_404(db, project_id, estimate_id)
    if estimate.status != "validated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Estimate must be validated",
        )
    project.reference_estimate_id = estimate.id
    db.commit()
    db.refresh(project)
    return to_project_read(project)


@router.get(
    "/{project_id}/estimates/{estimate_id}/task-rows",
    response_model=EstimateTaskRowListRead,
)
def list_estimate_task_rows(
    project_id: int,
    estimate_id: int,
    params: ListParams = Depends(list_params),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateTaskRowListRead:
    project = get_project_or_404(db, project_id, current_user.id)
    estimate = get_estimate_or_404(db, project_id, estimate_id)
    query = db.query(EstimateTaskRow).filter(EstimateTaskRow.estimate_id == estimate_id)
    result = apply_pagination(
        query,
        params,
        # Sorting/searching stays on the stored columns (the SQL-level pagination
        # boundary) even though the returned field *values* are resolved live
        # below for a draft estimate -- see resolve_live_task_display's own
        # docstring. Both agree at the moment a row is created; a later
        # rename/move of a task already priced by a draft estimate can make a
        # requested `?sort=task_name`/`?sort=position` order stale until the
        # unified tasks/cost-lines tree (E12-09) replaces this endpoint's
        # ordering altogether.
        sortable={
            "position": EstimateTaskRow.position,
            "task_name": EstimateTaskRow.task_name,
            "outline_number": EstimateTaskRow.outline_number,
            "outline_level": EstimateTaskRow.outline_level,
        },
        default_sort=EstimateTaskRow.position,
        tiebreaker=EstimateTaskRow.id,
        searchable=[EstimateTaskRow.task_name],
    )
    # Issue #290 (E12-08): only a draft estimate's task rows are live -- a
    # validated estimate keeps reading its own frozen stored columns (see
    # resolve_live_task_display's docstring).
    # Finding Haute (round-5 review): resolve_live_task_display renumbers
    # `position` 1..N depth-first across *only the rows it is given* -- not a
    # global rank over the estimate's whole task tree (see its own
    # docstring). `result.rows` is already the paginated page (limit/offset
    # applied in SQL by apply_pagination above), so passing it directly here
    # would make every page report `position` starting back at 1 instead of
    # the row's true position in the full devis. Resolve against every task
    # row of the estimate, then only materialize the current page's entries
    # into the response below.
    resolved = (
        resolve_live_task_display(
            db,
            project,
            db.query(EstimateTaskRow).filter(EstimateTaskRow.estimate_id == estimate_id).all(),
        )
        if estimate.status == "draft"
        else {}
    )
    # task_uid, unlike the fields above, is resolved regardless of draft/validated
    # status (Finding Moyenne #4, round 4 review) -- see to_estimate_task_row_read's
    # own docstring.
    task_uid_by_task_id = resolve_task_uid_by_id(db, project)
    return EstimateTaskRowListRead(
        items=[
            to_estimate_task_row_read(row, resolved.get(row.id), task_uid_by_task_id)
            for row in result.rows
        ],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


def _resolve_legacy_parent_task(
    db: Session, project_id: int, parent_uid: int | None
) -> MsTask | None:
    """Bridge a planning snapshot uid to its legacy ``MsTask`` twin, if any.

    A task added through :func:`create_planning_task` before E6-06 only ever
    lived in ``WfPlanningTaskSnapshot`` -- it has no ``MsTask`` twin unless one
    was separately generated (e.g. by ``generate_planning_structure`` or an
    import). ``EstimateTaskRow.parent_task_id``/``MsTask.parent_uid`` can only
    ever reference an existing ``MsTask`` row (the latter through a DB-level
    foreign key), so a parent with no twin resolves to ``None`` here -- the new
    task becomes a root in the legacy ``MsTask`` tree, mirroring the same
    already-established fallback ``create_project_estimate`` uses when
    snapshotting a task whose uid isn't in its own ``task_by_uid`` map.
    """
    if parent_uid is None:
        return None
    return (
        db.query(MsTask).filter(MsTask.project_id == project_id, MsTask.uid == parent_uid).first()
    )


def _create_estimate_planning_task(
    db: Session,
    project_id: int,
    estimate_id: int,
    planning: WfPlanning,
    *,
    name: str,
    is_milestone: bool,
    target_parent_uid: int | None,
    insert_after_uid: int | None,
) -> tuple[MsTask, EstimateTaskRow]:
    """Create one planning-snapshot + legacy ``MsTask`` twin + ``EstimateTaskRow`` (E6-06/#67).

    Factored out of ``create_estimate_task`` so #68's milestone-template endpoint can
    call it N+2 times within a single transaction without duplicating the
    snapshot/twin/row wiring (including the parent ``is_summary`` flip below). Does
    *not* flush ``planning.revision`` or commit -- the caller owns the transaction
    boundary, since a multi-task batch must bump the revision once for the whole
    call, not once per created task (see ``create_estimate_task``'s and
    ``create_estimate_cost_line_milestones``'s own revision-bump comments).
    """
    command = PlanningTaskCreate(
        name=name,
        is_milestone=is_milestone,
        target_parent_uid=target_parent_uid,
        insert_after_uid=insert_after_uid,
        # Unused by create_planning_task itself (only the plannings.py route layer
        # compares expected_revision against planning.revision) -- set to the
        # current value only to satisfy the schema's required field.
        expected_revision=planning.revision,
    )
    snapshot = create_planning_task(db, planning, command)

    parent_task = _resolve_legacy_parent_task(db, project_id, snapshot.parent_uid)
    if parent_task is not None and not parent_task.is_summary:
        # create_planning_task already recalculated is_summary=True on the
        # parent's snapshot twin (_recalculate_outline_and_durations); the
        # legacy MsTask twin needs the same flip or it goes stale (e.g. a
        # `livrable` leaf freshly promoted to a container by this insert),
        # which get_estimate_validation_warnings and the MS Project XML
        # export both read straight off MsTask.is_summary.
        parent_task.is_summary = True
        db.add(parent_task)
    task = MsTask(
        project_id=project_id,
        uid=snapshot.uid,
        parent_uid=parent_task.uid if parent_task is not None else None,
        position=snapshot.position,
        name=snapshot.name,
        task_type=snapshot.task_type,
        outline_number=snapshot.outline_number,
        outline_level=snapshot.outline_level,
        is_summary=snapshot.is_summary,
        is_milestone=snapshot.is_milestone,
    )
    db.add(task)
    db.flush()

    # Appended after every existing row of this estimate: mid-tree renumbering
    # would require rewriting outline_number/outline_level/position for every
    # other row too, and existing rows with task_id=None (created from a
    # snapshot task with no legacy MsTask twin, see _resolve_legacy_parent_task)
    # cannot be traced back to a planning uid at all to do so safely.
    max_position = (
        db.query(func.max(EstimateTaskRow.position))
        .filter(EstimateTaskRow.estimate_id == estimate_id)
        .scalar()
        or 0
    )
    row = EstimateTaskRow(
        estimate_id=estimate_id,
        task_id=task.id,
        parent_task_id=parent_task.id if parent_task is not None else None,
        position=max_position + 1,
        task_name=task.name,
        outline_number=task.outline_number,
        outline_level=task.outline_level,
        is_milestone=task.is_milestone,
    )
    db.add(row)
    db.flush()
    return task, row


def create_estimate_task(
    project_id: int,
    estimate_id: int,
    payload: EstimateTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateTaskRowRead:
    """Add a task to the project's displayed draft planning from the Devis screen (E6-06/#67).

    Creates, in a single transaction: the ``WfPlanningTaskSnapshot`` (via
    :func:`create_planning_task`), a twin ``MsTask`` row sharing its uid --
    required because ``TaskRoleAssignment``/``EstimateCostLine`` both key off
    ``ms_task.id``, never off the snapshot -- and an ``EstimateTaskRow`` in
    the current estimate pointing at that ``MsTask``.

    Bumps ``planning.revision`` (like every other planning-tree mutation) so a
    concurrently open Planning tree editor detects the change on its own next
    edit -- but does not itself require an ``expected_revision`` from the
    caller: unlike the Planning tree editor, this screen holds no long-lived,
    optimistically-edited in-memory copy of the tree to protect, and the
    project/planning row locks already prevent a lost update.
    """
    project = get_mutable_project_lock(db, project_id, current_user.id)
    planning = get_displayed_draft_planning_lock_or_409(db, project)
    get_draft_estimate_or_409(db, project_id, estimate_id)

    try:
        _, row = _create_estimate_planning_task(
            db,
            project_id,
            estimate_id,
            planning,
            name=payload.name,
            is_milestone=payload.is_milestone,
            target_parent_uid=payload.target_parent_uid,
            insert_after_uid=payload.insert_after_uid,
        )
        planning.revision += 1
        db.add(planning)
        db.flush()
        # Capture the response while the row locks are still held so a concurrent
        # writer cannot make us return a later transaction's state. Always a draft
        # estimate here (get_draft_estimate_or_409 above), so the row is live --
        # `resolved` always has an entry for it, so the task_uid fallback map
        # is never actually consulted here.
        # Finding Haute (round-5 review): resolve against every task row of the
        # estimate, not just the newly created `row` -- resolve_live_task_display
        # renumbers `position` 1..N depth-first across only the rows it is given
        # (see its own docstring), so passing a single-row list here always
        # reported `position: 1` regardless of the task's true place in the tree.
        all_task_rows = (
            db.query(EstimateTaskRow).filter(EstimateTaskRow.estimate_id == estimate_id).all()
        )
        resolved = resolve_live_task_display(db, project, all_task_rows)
        result = to_estimate_task_row_read(row, resolved.get(row.id), {})
        db.commit()
    except PlanningTreeMoveNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PlanningTreeInvariantError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PlanningTreeMoveError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Planning hierarchy conflicts with existing planning data",
        ) from exc
    return result


router.add_api_route(
    "/{project_id}/estimates/{estimate_id}/tasks",
    create_estimate_task,
    methods=["POST"],
    response_model=EstimateTaskRowRead,
    status_code=status.HTTP_201_CREATED,
    route_class_override=_PlanningTaskBodyValidationRoute,
)


@router.get(
    "/{project_id}/estimates/{estimate_id}/aggregates",
    response_model=EstimateAggregatesRead,
)
def get_estimate_aggregates(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateAggregatesRead:
    get_project_or_404(db, project_id, current_user.id)
    get_estimate_or_404(db, project_id, estimate_id)
    aggregates = calculate_estimate_aggregates(db, estimate_id)
    # Issue #71 (E6-10): `calculate_estimate_aggregates` also returns `by_cost_code`,
    # consumed by the Excel export (services/estimate_export.py) -- this JSON endpoint
    # deliberately keeps exposing only the pre-existing fields, so it's built
    # explicitly rather than by unpacking the whole dict.
    return EstimateAggregatesRead(
        total_labor_cost=aggregates["total_labor_cost"],
        total_purchase_cost=aggregates["total_purchase_cost"],
        total_unburdened_cost=aggregates["total_unburdened_cost"],
        by_category=aggregates["by_category"],
    )


@router.get("/{project_id}/estimates/{estimate_id}/export.xlsx")
def export_estimate_excel(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    project = get_project_or_404(db, project_id, current_user.id)
    estimate = get_estimate_or_404(db, project_id, estimate_id)
    workbook_bytes = build_estimate_workbook(db, project, estimate)
    filename = f"devis-{project.name}-v{estimate.version_number}.xlsx".replace(" ", "-")
    return Response(
        content=workbook_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{project_id}/estimates/{estimate_id}/export-reconciliation.xlsx")
def export_estimate_reconciliation_excel(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    """Export the devis for round-trip reimport (E6-08, #69).

    Distinct from ``GET .../export.xlsx`` (a human-readable cost grid): this
    workbook carries one sheet per line nature (`Tâches`/`MO`/`Non-MO`) with
    stable internal ids for reconciliation on reimport (see
    ``.../import-reconciliation/preview`` and ``.../confirm`` below, E6-09/#70).
    See ``estimate_reconciliation_export`` for the exact column layout.
    """
    project = get_project_or_404(db, project_id, current_user.id)
    estimate = get_estimate_or_404(db, project_id, estimate_id)
    workbook_bytes = build_estimate_reconciliation_workbook(db, project, estimate)
    filename = f"devis-{project.name}-v{estimate.version_number}-reconciliation.xlsx".replace(
        " ", "-"
    )
    return Response(
        content=workbook_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@dataclass(frozen=True)
class _TaskCreateCandidate:
    row_number: int
    name: str
    is_milestone: bool
    target_parent_uid: int | None


@dataclass(frozen=True)
class _LaborCreateCandidate:
    row_number: int
    task_id: int
    role_id: int
    cost_code_id: int | None
    quantity: Decimal
    hours: Decimal
    comment: str | None


@dataclass(frozen=True)
class _LaborUpdateCandidate:
    row_number: int
    assignment_id: int
    cost_code_id: int | None
    quantity: Decimal
    hours: Decimal
    comment: str | None


@dataclass(frozen=True)
class _CostLineCreateCandidate:
    row_number: int
    task_id: int | None
    cost_category_id: int
    cost_code_id: int | None
    label: str
    quantity: Decimal
    unit_cost: Decimal
    supply_status: str | None
    planned_date: datetime | None


@dataclass(frozen=True)
class _CostLineUpdateCandidate:
    row_number: int
    line_id: int
    task_id: int | None
    cost_category_id: int | None
    cost_code_id: int | None
    label: str | None
    quantity: Decimal | None
    unit_cost: Decimal | None
    supply_status: str | None
    planned_date: datetime | None


_TASK_FIELD_NAMES = (
    "task_name",
    "is_milestone",
    "parent_task_id",
    "position",
    "outline_number",
    "outline_level",
)


def _planned_dates_equal(file_value: datetime | None, existing_value: datetime | None) -> bool:
    """Compare a Non-MO row's ``planned_date`` at date-only precision.

    The export only ever writes the calendar date (``line.planned_date.date().isoformat()``,
    see ``estimate_reconciliation_export._write_non_labor_sheet``), so a stored
    time-of-day/timezone can never round-trip -- comparing full ``datetime`` equality
    would spuriously report every already-unchanged row with a time component as
    "changed" (and naive-vs-aware ``datetime`` comparison raises outright).
    """
    if file_value is None or existing_value is None:
        return file_value is None and existing_value is None
    return file_value.date() == existing_value.date()


def _changed_task_fields(
    existing: EstimateTaskRow,
    row: TaskFileRow,
    resolved: ResolvedTaskDisplay | None,
) -> list[str]:
    """Compare an imported Tâches row to the same baseline the export wrote it from.

    ``resolved`` is this row's live display (``resolve_live_task_display``,
    keyed by ``EstimateTaskRow.id``) when the devis is a draft, ``None`` for a
    validated devis -- exactly the same draft/validated branch
    ``_write_tasks_sheet``/``to_estimate_task_row_read`` already apply (E12-08
    Finding Haute #1, round 4 review). Comparing against ``existing``'s own
    frozen stored columns instead -- as this used to do unconditionally --
    made a draft devis's reconciliation export/reimport round-trip
    desynchronized: renaming/moving a task live, exporting (which already
    wrote the *live* value), then reimporting with no further edits produced
    a spurious ``TASK_FIELD_CHANGE_IGNORED`` warning, since the file's
    (unedited) live value never matched the still-frozen stored column.
    ``is_milestone`` has no live counterpart (``resolve_live_task_display``
    never derives it), so it is always compared against ``existing`` directly,
    draft or not.
    """
    candidate = {
        "task_name": row.task_name,
        "is_milestone": row.is_milestone,
        "parent_task_id": row.parent_task_id,
        "position": row.position,
        "outline_number": row.outline_number,
        "outline_level": row.outline_level,
    }
    baseline = {
        "task_name": resolved.task_name if resolved is not None else existing.task_name,
        "is_milestone": existing.is_milestone,
        "parent_task_id": (
            resolved.parent_task_id if resolved is not None else existing.parent_task_id
        ),
        "position": resolved.position if resolved is not None else existing.position,
        "outline_number": (
            resolved.outline_number if resolved is not None else existing.outline_number
        ),
        "outline_level": (
            resolved.outline_level if resolved is not None else existing.outline_level
        ),
    }
    return [
        field
        for field in _TASK_FIELD_NAMES
        if candidate[field] is not None and baseline[field] != candidate[field]
    ]


def _resolve_task_parent_uid(
    db: Session,
    project: MsProject,
    parent_task_id: int,
    row_number: int,
    issues: list[ReconciliationIssue],
) -> int | None:
    """Resolve a Tâches-sheet creation row's ``parent_task_id`` to a ``target_parent_uid``.

    Mirrors both invariants ``create_planning_task``/``_validate_target_parent``
    (``planning_tree.py``) enforce for a real parent (E6-09 Finding Haute #1, round 3
    review): the parent must be a node of the project's *currently displayed*
    planning snapshot -- not just any ``MsTask`` the project has ever had, since a
    task can keep its legacy ``MsTask``/``EstimateTaskRow`` twin after being removed
    from the displayed planning -- and it must not be a milestone
    (``create_planning_task`` raises ``PlanningTreeInvariantError("A milestone
    cannot contain children")`` for that case, which -- surfacing as a bare
    ``HTTPException`` from deep inside ``_apply_task_creates``, uncaught by any of
    confirm's own ``except`` clauses -- would otherwise break the
    ``oneOf(ReconciliationPlanRead, PlanningTaskDeleteConflict)`` 409 contract
    documented for that endpoint). Returns ``None`` (with a blocking issue already
    appended) when either check fails.
    """
    parent_task = (
        db.query(MsTask)
        .filter(MsTask.id == parent_task_id, MsTask.project_id == project.id)
        .first()
    )
    if parent_task is None:
        issues.append(
            ReconciliationIssue(
                code="TASK_PARENT_UNRESOLVED",
                message=(
                    f"parent_task_id {parent_task_id} does not match an "
                    "existing task (a newly created task cannot be used as a "
                    "parent within the same import)"
                ),
                sheet="Tâches",
                row=row_number,
            )
        )
        return None
    parent_snapshot = (
        db.query(WfPlanningTaskSnapshot)
        .filter(
            WfPlanningTaskSnapshot.planning_id == project.displayed_planning_id,
            WfPlanningTaskSnapshot.uid == parent_task.uid,
        )
        .first()
    )
    if parent_snapshot is None:
        issues.append(
            ReconciliationIssue(
                code="TASK_PARENT_UNRESOLVED",
                message=(
                    f"parent_task_id {parent_task_id} is not a node of the "
                    "project's currently displayed planning"
                ),
                sheet="Tâches",
                row=row_number,
            )
        )
        return None
    if parent_snapshot.is_milestone:
        issues.append(
            ReconciliationIssue(
                code="TASK_PARENT_IS_MILESTONE",
                message=(
                    f"parent_task_id {parent_task_id} is a milestone and cannot contain children"
                ),
                sheet="Tâches",
                row=row_number,
            )
        )
        return None
    return parent_task.uid


def _stage_task_sheet(
    db: Session,
    project: MsProject,
    parsed_tasks: list[TaskFileRow],
    existing_task_rows: dict[int, EstimateTaskRow],
    resolved_by_row_id: dict[int, ResolvedTaskDisplay],
    issues: list[ReconciliationIssue],
    warnings: list[ReconciliationIssue],
) -> tuple[list[_TaskCreateCandidate], list[int]]:
    """Validate the ``Tâches`` sheet against the current devis, without writing anything.

    An existing row (``id`` set) is never mutated: a difference on any of
    ``_TASK_FIELD_NAMES`` becomes a ``TASK_FIELD_CHANGE_IGNORED`` warning, not
    an update -- unchanged since #70's issue body. Issue #290 (E12-08) later
    added a real rename/move channel (``PATCH .../tasks/{task_uid}``, from
    either the Planning screen or the devis grid), but this reconciliation
    import still never writes ``task_name``/``outline_number``/
    ``outline_level``/``position``/``parent_task_id`` for an existing row --
    only that dedicated endpoint does, and only ``WfPlanningTaskSnapshot``/
    ``MsTask`` themselves, never ``EstimateTaskRow``'s own stored columns
    (which stay frozen at row-creation time on purpose, see
    ``services.estimate_task_display``). A row without an ``id`` is a
    creation candidate whose ``parent_task_id`` must already resolve to an
    existing ``MsTask``.

    ``resolved_by_row_id`` is compared against, not ``existing_row``'s own
    stored columns, so that a difference is only ever reported against the
    same baseline the export wrote the file from (see
    ``_changed_task_fields``'s own docstring, E12-08 Finding Haute #1).
    """
    task_creates: list[_TaskCreateCandidate] = []
    seen_task_row_ids: set[int] = set()
    for row in parsed_tasks:
        if row.id is not None:
            seen_task_row_ids.add(row.id)
            existing_row = existing_task_rows.get(row.id)
            if existing_row is None:
                issues.append(
                    ReconciliationIssue(
                        code="TASK_ROW_ID_UNKNOWN",
                        message=f"Task row id {row.id} does not belong to this estimate",
                        sheet="Tâches",
                        row=row.row_number,
                    )
                )
                continue
            changed = _changed_task_fields(existing_row, row, resolved_by_row_id.get(row.id))
            if changed:
                warnings.append(
                    ReconciliationIssue(
                        code="TASK_FIELD_CHANGE_IGNORED",
                        message=(
                            "Ignored change(s) to: "
                            f"{', '.join(changed)} (renaming/moving a task is not "
                            "supported by this import; use the Planning screen or "
                            "the devis grid instead)"
                        ),
                        sheet="Tâches",
                        row=row.row_number,
                    )
                )
            continue
        if not row.task_name:
            issues.append(
                ReconciliationIssue(
                    code="TASK_NAME_REQUIRED",
                    message="task_name is required to create a task",
                    sheet="Tâches",
                    row=row.row_number,
                )
            )
            continue
        target_parent_uid: int | None = None
        if row.parent_task_id is not None:
            target_parent_uid = _resolve_task_parent_uid(
                db, project, row.parent_task_id, row.row_number, issues
            )
            if target_parent_uid is None:
                continue
        task_creates.append(
            _TaskCreateCandidate(
                row_number=row.row_number,
                name=row.task_name,
                is_milestone=row.is_milestone,
                target_parent_uid=target_parent_uid,
            )
        )
    tasks_to_delete_ids = sorted(set(existing_task_rows) - seen_task_row_ids)
    return task_creates, tasks_to_delete_ids


def _task_belongs_to_project(db: Session, project: MsProject, task_id: int | None) -> bool:
    if task_id is None:
        return True
    return (
        db.query(MsTask.id).filter(MsTask.id == task_id, MsTask.project_id == project.id).first()
        is not None
    )


def _non_labor_category_kind(db: Session, cost_category_id: int) -> str | None:
    """Read-only mirror of ``get_non_labor_category_or_400``'s own query (E6-02/#63).

    Returns the category's ``CostType.kind`` (rather than a plain bool) so staging can
    also evaluate the supply_status/kind compatibility rule below (E6-09 Finding
    Haute, round 2) with the exact same active-category lookup used to decide
    ``COST_LINE_CATEGORY_INVALID`` -- never a second, diverging query.
    """
    row = (
        db.query(CostType.kind)
        .join(CostCategory, CostCategory.cost_type_id == CostType.id)
        .filter(CostCategory.id == cost_category_id)
        .filter(CostCategory.is_active.is_(True))
        .filter(CostType.is_active.is_(True))
        .filter(CostType.kind != CostTypeKind.LABOR)
        .first()
    )
    return row[0] if row is not None else None


def _cost_line_supply_status_is_compatible(kind: str, supply_status: str | None) -> bool:
    """Single source of truth for the Non-MO ``supply_status``/category-kind rule.

    A ``supply_status`` may only ever be set on a ``SUPPLY``-kind cost line -- the
    exact rule ``_apply_cost_line_creates`` and ``_resolve_cost_line_update_supply_status``
    already enforce at apply time. Factored out so ``_stage_cost_line_sheet`` can report
    the same ``COST_LINE_SUPPLY_STATUS_INVALID`` condition as a blocking issue at
    preview/precheck time too (E6-09 Finding Haute, round 2 review): before this, the
    check only existed at apply, so a preview could report ``blocking_issues: []`` for a
    file that ``confirm`` would then reject outright, with a bare 400 instead of a
    structured ``ReconciliationPlanRead`` 409.
    """
    return supply_status is None or kind == CostTypeKind.SUPPLY


def _cost_code_valid(db: Session, project: MsProject, cost_code_id: int | None) -> bool:
    """Read-only mirror of ``resolve_cost_code_id``'s own validation (E6-02/#63).

    ``None`` always resolves to the project's active root at apply time, so it is
    always considered valid here too.
    """
    if cost_code_id is None:
        return True
    cost_code = (
        db.query(ProjectCostCode)
        .filter(ProjectCostCode.id == cost_code_id, ProjectCostCode.project_id == project.id)
        .first()
    )
    return cost_code is not None and cost_code.is_active


def _active_labor_role(db: Session, role_id: int) -> ResourceRole | None:
    """Read-only mirror of ``create_task_role_assignment``'s own role query (``tasks.py``)."""
    return (
        db.query(ResourceRole)
        .join(CostCategory, ResourceRole.cost_category_id == CostCategory.id)
        .join(CostType, CostCategory.cost_type_id == CostType.id)
        .filter(ResourceRole.id == role_id)
        .filter(ResourceRole.is_active.is_(True))
        .filter(CostCategory.is_active.is_(True))
        .filter(CostType.kind == CostTypeKind.LABOR)
        .filter(CostType.is_active.is_(True))
        .first()
    )


def _stage_existing_labor_row(
    db: Session,
    project: MsProject,
    row: LaborFileRow,
    existing_assignments: dict[int, EstimateRoleAssignment],
    issues: list[ReconciliationIssue],
) -> _LaborUpdateCandidate | None:
    assert row.id is not None
    existing_assignment = existing_assignments.get(row.id)
    if existing_assignment is None:
        issues.append(
            ReconciliationIssue(
                code="LABOR_ROW_ID_UNKNOWN",
                message=f"Role assignment id {row.id} does not belong to this estimate",
                sheet="MO",
                row=row.row_number,
            )
        )
        return None
    identity_changed = (row.task_id is not None and row.task_id != existing_assignment.task_id) or (
        row.role_id is not None and row.role_id != existing_assignment.role_id
    )
    if identity_changed:
        issues.append(
            ReconciliationIssue(
                code="LABOR_IDENTITY_CHANGE_REJECTED",
                message="task_id/role_id cannot be changed for an existing role assignment",
                sheet="MO",
                row=row.row_number,
            )
        )
        return None
    if row.quantity is None or row.hours is None:
        issues.append(
            ReconciliationIssue(
                code="LABOR_VALUE_REQUIRED",
                message="quantity and hours are required",
                sheet="MO",
                row=row.row_number,
            )
        )
        return None
    if not _cost_code_valid(db, project, row.cost_code_id):
        issues.append(
            ReconciliationIssue(
                code="LABOR_COST_CODE_INVALID",
                message=f"cost_code_id {row.cost_code_id} does not belong to the project "
                "or is inactive",
                sheet="MO",
                row=row.row_number,
            )
        )
        return None
    if (
        # A blank cost_code_id cell means "unchanged", exactly like task_id/planned_date
        # on the Non-MO sheet -- resolve_cost_code_id's None means "attach to the
        # project's active root", which only applies to a *creation*, never a silent
        # reassignment away from an already-set attachment on an update (E6-09 Critical
        # finding, round 3 review). Comparing it as a plain equality against the
        # persisted value would otherwise report a no-op blank cell as "changed".
        (row.cost_code_id is None or row.cost_code_id == existing_assignment.cost_code_id)
        and row.quantity == existing_assignment.quantity
        and row.hours == existing_assignment.hours
        and (row.comment or None) == (existing_assignment.comment or None)
    ):
        # No actual change from the persisted row: not staged as an update, so a
        # round-trip export/reimport with no edits produces an empty diff.
        return None
    return _LaborUpdateCandidate(
        row_number=row.row_number,
        assignment_id=row.id,
        cost_code_id=row.cost_code_id,
        quantity=row.quantity,
        hours=row.hours,
        comment=row.comment,
    )


def _stage_new_labor_row(
    db: Session,
    project: MsProject,
    row: LaborFileRow,
    staged_pairs: set[tuple[int, int]],
    # Issue #289 (E12-07): EstimateRoleAssignment.task_id is now nullable (a
    # root-detached assignment has no task), so retained_pairs -- built
    # straight from live assignment rows -- can carry a None task_id. `pair`
    # below is always a real (non-None) task_id from the imported file, so it
    # can never match one of those; this is just a type widening, not a
    # behaviour change.
    retained_pairs: set[tuple[int | None, int]],
    issues: list[ReconciliationIssue],
) -> _LaborCreateCandidate | None:
    if row.task_id is None or row.role_id is None or row.quantity is None or row.hours is None:
        issues.append(
            ReconciliationIssue(
                code="LABOR_ROW_INCOMPLETE",
                message="task_id, role_id, quantity and hours are required to create a "
                "role assignment",
                sheet="MO",
                row=row.row_number,
            )
        )
        return None
    if not _task_belongs_to_project(db, project, row.task_id):
        issues.append(
            ReconciliationIssue(
                code="LABOR_TASK_INVALID",
                message=f"task_id {row.task_id} does not belong to the project",
                sheet="MO",
                row=row.row_number,
            )
        )
        return None
    if _active_labor_role(db, row.role_id) is None:
        issues.append(
            ReconciliationIssue(
                code="LABOR_ROLE_INVALID",
                message=f"role_id {row.role_id} must be an active labor role",
                sheet="MO",
                row=row.row_number,
            )
        )
        return None
    if not _cost_code_valid(db, project, row.cost_code_id):
        issues.append(
            ReconciliationIssue(
                code="LABOR_COST_CODE_INVALID",
                message=f"cost_code_id {row.cost_code_id} does not belong to the project "
                "or is inactive",
                sheet="MO",
                row=row.row_number,
            )
        )
        return None
    pair = (row.task_id, row.role_id)
    # Scoped to *this* estimate's own remaining assignments (issue #268/E12-03's fix):
    # `retained_pairs` is `existing_assignments`' own (task_id, role_id) pairs minus
    # whichever of them this same import also stages for deletion (see
    # `_stage_labor_sheet`'s own docstring) -- so a pair that exists only in a
    # *different* estimate of the same project never blocks this creation (the
    # `(estimate_id, task_id, role_id)` unique constraint is per-estimate, never
    # project-wide), and a pair this same file deletes-then-recreates is not
    # spuriously rejected as still assigned.
    if pair in retained_pairs or pair in staged_pairs:
        issues.append(
            ReconciliationIssue(
                code="LABOR_DUPLICATE_ASSIGNMENT",
                message=(
                    f"A role assignment already exists for task_id={row.task_id}/"
                    f"role_id={row.role_id}"
                ),
                sheet="MO",
                row=row.row_number,
            )
        )
        return None
    staged_pairs.add(pair)
    return _LaborCreateCandidate(
        row_number=row.row_number,
        task_id=row.task_id,
        role_id=row.role_id,
        cost_code_id=row.cost_code_id,
        quantity=row.quantity,
        hours=row.hours,
        comment=row.comment,
    )


def _stage_labor_sheet(
    db: Session,
    project: MsProject,
    parsed_labor: list[LaborFileRow],
    existing_assignments: dict[int, EstimateRoleAssignment],
    out_of_scope_assignment_ids: set[int],
    issues: list[ReconciliationIssue],
    warnings: list[ReconciliationIssue],
) -> tuple[list[_LaborCreateCandidate], list[_LaborUpdateCandidate], list[int]]:
    """Validate the ``MO`` sheet against this estimate's own scoped role assignments.

    A ``hors_perimetre_planning`` row is always skipped (never created,
    updated or deleted -- see #69's own export contract), with a plain
    informational warning rather than an error. ``out_of_scope_assignment_ids``
    (every id ``_run_reconciliation`` found flagged out-of-scope in the
    *database*, independently of the file) is excluded wholesale from the
    deletion candidates below: an out-of-scope assignment absent from the file
    must never be proposed for deletion either, matching this same skip for a
    row still present but flagged in the file. Without this exclusion, a row
    the user simply removed from the sheet (rather than flagging) would fall
    through to ``labor_to_delete`` and be genuinely deleted at confirm --
    contradicting the "never deleted" guarantee above.

    Restructured into two passes over ``parsed_labor`` (issue #268, fixed as part
    of E12-03/#275's migration to ``EstimateRoleAssignment``): every row carrying
    an ``id`` (an update or a still-flagged hors-perimetre row) is staged first,
    so ``labor_to_delete_ids`` -- and from it, the exact set of ``(task_id,
    role_id)`` pairs this same import is about to free up -- is fully known
    *before* the second pass evaluates any creation row's uniqueness. A single
    pass could not do this: without it, a file that both deletes the MO row for
    a pair and recreates a fresh row for that very same pair would spuriously
    reject the creation as ``LABOR_DUPLICATE_ASSIGNMENT``, since the pair still
    "exists" in the database until the deletion is actually applied, several
    steps later in ``_run_reconciliation``.
    """
    labor_creates: list[_LaborCreateCandidate] = []
    labor_updates: list[_LaborUpdateCandidate] = []
    seen_assignment_ids: set[int] = set()
    creation_rows: list[LaborFileRow] = []

    # ---- Pass 1: every row carrying an id (updates + hors-perimetre rows) ----
    for labor_row in parsed_labor:
        if labor_row.hors_perimetre_planning:
            if labor_row.id is not None:
                seen_assignment_ids.add(labor_row.id)
            warnings.append(
                ReconciliationIssue(
                    code="LABOR_OUT_OF_PLANNING_SCOPE_IGNORED",
                    message="Row is outside the estimate's source planning and was ignored",
                    sheet="MO",
                    row=labor_row.row_number,
                )
            )
            continue
        if labor_row.id is not None:
            seen_assignment_ids.add(labor_row.id)
            update = _stage_existing_labor_row(db, project, labor_row, existing_assignments, issues)
            if update is not None:
                labor_updates.append(update)
            continue
        creation_rows.append(labor_row)

    labor_to_delete_ids = sorted(
        set(existing_assignments) - seen_assignment_ids - out_of_scope_assignment_ids
    )
    labor_to_delete_id_set = set(labor_to_delete_ids)
    # (task_id, role_id) pairs still assigned in this estimate once this same
    # import's own deletions are applied -- see this function's own docstring and
    # `_stage_new_labor_row`'s for how this fixes #268.
    retained_pairs = {
        (assignment.task_id, assignment.role_id)
        for assignment_id, assignment in existing_assignments.items()
        if assignment_id not in labor_to_delete_id_set
    }

    # ---- Pass 2: rows without an id (creations), now that retained_pairs is final ----
    staged_labor_pairs: set[tuple[int, int]] = set()
    for labor_row in creation_rows:
        create = _stage_new_labor_row(
            db, project, labor_row, staged_labor_pairs, retained_pairs, issues
        )
        if create is not None:
            labor_creates.append(create)

    return labor_creates, labor_updates, labor_to_delete_ids


def _stage_existing_cost_line_row(
    db: Session,
    project: MsProject,
    cost_row: CostLineFileRow,
    existing_line: EstimateCostLine,
    issues: list[ReconciliationIssue],
) -> _CostLineUpdateCandidate | None:
    assert cost_row.id is not None
    if (
        (cost_row.task_id is None or cost_row.task_id == existing_line.task_id)
        and (
            cost_row.cost_category_id is None
            or cost_row.cost_category_id == existing_line.cost_category_id
        )
        # A blank cost_code_id cell means "unchanged", exactly like task_id above --
        # resolve_cost_code_id's None means "attach to the project's active root",
        # which only applies to a *creation*, never a silent reassignment away from
        # an already-set attachment on an update (E6-09 Critical finding, round 3
        # review). Comparing it as a plain equality against the persisted value
        # would otherwise report a no-op blank cell as "changed".
        and (cost_row.cost_code_id is None or cost_row.cost_code_id == existing_line.cost_code_id)
        and cost_row.label == existing_line.label
        and cost_row.quantity == existing_line.quantity
        and cost_row.unit_cost == existing_line.unit_cost
        and (cost_row.supply_status or None) == (existing_line.supply_status or None)
        and _planned_dates_equal(cost_row.planned_date, existing_line.planned_date)
    ):
        # No actual change from the persisted row: not staged as an update, so
        # a round-trip export/reimport with no edits produces an empty diff.
        return None
    if not _task_belongs_to_project(db, project, cost_row.task_id):
        issues.append(
            ReconciliationIssue(
                code="COST_LINE_TASK_INVALID",
                message=f"task_id {cost_row.task_id} does not belong to the project",
                sheet="Non-MO",
                row=cost_row.row_number,
            )
        )
        return None
    # A blank cost_category_id cell means "unchanged" (see the task_id/cost_code_id
    # comment above) -- the effective kind checked below is then the *persisted*
    # line's own category, never the request's (E6-09 Finding Haute, round 2 review).
    # If that persisted category has since become inactive/invalid (e.g. deactivated
    # after this line was created), the apply-time get_non_labor_category_or_400 call
    # would raise a bare 400 the preview never predicted -- so this must be reported
    # as a blocking issue here too, not silently skipped (E6-09 Finding Haute #3,
    # round 3 review).
    if cost_row.cost_category_id is not None:
        category_kind = _non_labor_category_kind(db, cost_row.cost_category_id)
        category_message = (
            f"cost_category_id {cost_row.cost_category_id} must be an active non-labor category"
        )
    else:
        category_kind = _non_labor_category_kind(db, existing_line.cost_category_id)
        category_message = (
            f"cost_category_id {existing_line.cost_category_id} (kept from the "
            "existing row) must be an active non-labor category"
        )
    if category_kind is None:
        issues.append(
            ReconciliationIssue(
                code="COST_LINE_CATEGORY_INVALID",
                message=category_message,
                sheet="Non-MO",
                row=cost_row.row_number,
            )
        )
        return None
    if not _cost_code_valid(db, project, cost_row.cost_code_id):
        issues.append(
            ReconciliationIssue(
                code="COST_LINE_COST_CODE_INVALID",
                message=f"cost_code_id {cost_row.cost_code_id} does not belong to the "
                "project or is inactive",
                sheet="Non-MO",
                row=cost_row.row_number,
            )
        )
        return None
    if not _cost_line_supply_status_is_compatible(category_kind, cost_row.supply_status):
        issues.append(
            ReconciliationIssue(
                code="COST_LINE_SUPPLY_STATUS_INVALID",
                message="supply_status is only valid for supply cost lines",
                sheet="Non-MO",
                row=cost_row.row_number,
            )
        )
        return None
    return _CostLineUpdateCandidate(
        row_number=cost_row.row_number,
        line_id=cost_row.id,
        task_id=cost_row.task_id,
        cost_category_id=cost_row.cost_category_id,
        cost_code_id=cost_row.cost_code_id,
        label=cost_row.label,
        quantity=cost_row.quantity,
        unit_cost=cost_row.unit_cost,
        supply_status=cost_row.supply_status,
        planned_date=cost_row.planned_date,
    )


def _stage_cost_line_sheet(
    db: Session,
    project: MsProject,
    parsed_cost_lines: list[CostLineFileRow],
    existing_cost_lines: dict[int, EstimateCostLine],
    issues: list[ReconciliationIssue],
) -> tuple[list[_CostLineCreateCandidate], list[_CostLineUpdateCandidate], list[int]]:
    """Validate the ``Non-MO`` sheet against this estimate's own cost lines."""
    non_labor_creates: list[_CostLineCreateCandidate] = []
    non_labor_updates: list[_CostLineUpdateCandidate] = []
    seen_cost_line_ids: set[int] = set()
    for cost_row in parsed_cost_lines:
        if cost_row.id is not None:
            seen_cost_line_ids.add(cost_row.id)
            if cost_row.id not in existing_cost_lines:
                issues.append(
                    ReconciliationIssue(
                        code="COST_LINE_ROW_ID_UNKNOWN",
                        message=f"Cost line id {cost_row.id} does not belong to this estimate",
                        sheet="Non-MO",
                        row=cost_row.row_number,
                    )
                )
                continue
            update = _stage_existing_cost_line_row(
                db, project, cost_row, existing_cost_lines[cost_row.id], issues
            )
            if update is not None:
                non_labor_updates.append(update)
            continue
        if (
            cost_row.cost_category_id is None
            or not cost_row.label
            or cost_row.quantity is None
            or cost_row.unit_cost is None
        ):
            issues.append(
                ReconciliationIssue(
                    code="COST_LINE_ROW_INCOMPLETE",
                    message="cost_category_id, label, quantity and unit_cost are required to "
                    "create a cost line",
                    sheet="Non-MO",
                    row=cost_row.row_number,
                )
            )
            continue
        if not _task_belongs_to_project(db, project, cost_row.task_id):
            issues.append(
                ReconciliationIssue(
                    code="COST_LINE_TASK_INVALID",
                    message=f"task_id {cost_row.task_id} does not belong to the project",
                    sheet="Non-MO",
                    row=cost_row.row_number,
                )
            )
            continue
        category_kind = _non_labor_category_kind(db, cost_row.cost_category_id)
        if category_kind is None:
            issues.append(
                ReconciliationIssue(
                    code="COST_LINE_CATEGORY_INVALID",
                    message=f"cost_category_id {cost_row.cost_category_id} must be an active "
                    "non-labor category",
                    sheet="Non-MO",
                    row=cost_row.row_number,
                )
            )
            continue
        if not _cost_code_valid(db, project, cost_row.cost_code_id):
            issues.append(
                ReconciliationIssue(
                    code="COST_LINE_COST_CODE_INVALID",
                    message=f"cost_code_id {cost_row.cost_code_id} does not belong to the "
                    "project or is inactive",
                    sheet="Non-MO",
                    row=cost_row.row_number,
                )
            )
            continue
        if not _cost_line_supply_status_is_compatible(category_kind, cost_row.supply_status):
            issues.append(
                ReconciliationIssue(
                    code="COST_LINE_SUPPLY_STATUS_INVALID",
                    message="supply_status is only valid for supply cost lines",
                    sheet="Non-MO",
                    row=cost_row.row_number,
                )
            )
            continue
        non_labor_creates.append(
            _CostLineCreateCandidate(
                row_number=cost_row.row_number,
                task_id=cost_row.task_id,
                cost_category_id=cost_row.cost_category_id,
                cost_code_id=cost_row.cost_code_id,
                label=cost_row.label,
                quantity=cost_row.quantity,
                unit_cost=cost_row.unit_cost,
                supply_status=cost_row.supply_status,
                planned_date=cost_row.planned_date,
            )
        )
    non_labor_to_delete_ids = sorted(set(existing_cost_lines) - seen_cost_line_ids)
    return non_labor_creates, non_labor_updates, non_labor_to_delete_ids


def _resolve_planning_for_tasks(
    db: Session,
    project: MsProject,
    *,
    needs_mutation: bool,
    issues: list[ReconciliationIssue],
) -> WfPlanning | None:
    """Lock + return the displayed draft planning, or report why it can't be used.

    Mirrors ``get_displayed_draft_planning_lock_or_409``'s own condition
    (E6-06/#67) without raising: a preview must report a non-draft planning
    as a blocking issue rather than abort with that helper's 409, so the same
    condition is inlined here and applies identically to preview and confirm.
    Only called at all when the Tâches sheet's diff needs at least one create
    or delete -- a devis import that only touches MO/Non-MO never requires a
    draft planning.
    """
    if not needs_mutation:
        return None
    candidate_planning = None
    if project.displayed_planning_id is not None:
        candidate_planning = (
            db.query(WfPlanning)
            .filter(
                WfPlanning.id == project.displayed_planning_id,
                WfPlanning.project_id == project.id,
            )
            .populate_existing()
            .with_for_update()
            .first()
        )
    if candidate_planning is None or candidate_planning.status != "draft":
        issues.append(
            ReconciliationIssue(
                code="PLANNING_NOT_DRAFT",
                message=(
                    "The project's displayed planning must be a draft to create or "
                    "delete tasks through this import"
                ),
                sheet="Tâches",
                row=None,
            )
        )
        return None
    return candidate_planning


def _task_deletion_blocking_issue(
    db: Session,
    project: MsProject,
    planning: WfPlanning | None,
    task: MsTask,
    *,
    excluding_task_row_id: int,
    excluded_assignment_ids: set[int],
    excluded_cost_line_ids: set[int],
    referenced_by_new_row: bool,
) -> ReconciliationIssue | None:
    """Read-only replica of ``delete_planning_tasks``'s cascade/reference checks (E3-05).

    Deliberately never attempts the real deletion to find out: SQLite's pysqlite
    driver does not correctly support the "commit a nested SAVEPOINT now, decide
    whether to keep the whole transaction via a later ``Session.rollback()``" pattern
    that would otherwise let this just try the real call and catch the failure --
    releasing a SAVEPOINT silently ends pysqlite's enclosing transaction outright, so
    a subsequent ``Session.rollback()`` (needed for ``preview``, and for a ``confirm``
    that still turns out to have another blocking issue elsewhere in the file) would
    silently fail to undo it. PostgreSQL (production) has no such quirk, but the test
    suite runs on SQLite, so the whole reconciliation import only ever mutates the
    database once, at the very end of a clean ``confirm`` (see ``_run_reconciliation``).

    ``excluded_assignment_ids``/``excluded_cost_line_ids`` are the ids *also* staged
    for deletion by this same import (applied before any task, per the order in
    ``_run_reconciliation``): a reference from one of them does not count as still
    blocking, matching ``delete_planning_tasks``'s own ``TASK_REFERENCED`` invariant
    once those rows are actually gone.

    ``referenced_by_new_row`` is ``True`` when this same file also stages a brand
    new MO/Non-MO row whose ``task_id`` targets this task (E6-09 Finding Haute #2,
    round 3 review): such a row only exists in memory as a create candidate, so
    every DB-backed "still referenced" query below is blind to it -- without this
    flag, staging would validate the deletion and the new row independently, then
    at apply time (deletions before creations, see ``_run_reconciliation``) the task
    would already be gone by the time the new row's FK insert is attempted,
    surfacing as an uncaught ``IntegrityError``/bare 500 instead of a predicted
    blocking issue.
    """
    if referenced_by_new_row:
        return ReconciliationIssue(
            code="TASK_DELETE_REFERENCED_BY_NEW_ROW",
            message=(
                f"Task row {excluding_task_row_id} is referenced by a new MO/Non-MO "
                "row created in the same import and cannot be deleted"
            ),
            sheet="Tâches",
            row=None,
        )
    if planning is not None:
        has_children = (
            db.query(WfPlanningTaskSnapshot.uid)
            .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
            .filter(WfPlanningTaskSnapshot.parent_uid == task.uid)
            .first()
            is not None
        )
        if has_children:
            return ReconciliationIssue(
                code="TASK_DELETE_REQUIRES_CASCADE_CONFIRMATION",
                message=(
                    f"Task row {excluding_task_row_id} has child tasks; delete them "
                    "first from the Planning screen before removing this row"
                ),
                sheet="Tâches",
                row=None,
            )

    # EstimateRoleAssignment (E12-01/#273), not the legacy TaskRoleAssignment: this
    # devis-scoped table is now the reconciliation import's own source of truth for
    # "still assigned" (E12-03/#275), and -- like EstimateCostLine.task_id just below
    # -- deliberately not filtered to this one estimate, so a task still referenced
    # by *another* estimate's own role assignment stays blocked from deletion too.
    remaining_assignment_ids = {
        row_id
        for (row_id,) in db.query(EstimateRoleAssignment.id)
        .filter(EstimateRoleAssignment.task_id == task.id)
        .all()
    } - excluded_assignment_ids
    remaining_cost_line_ids = {
        row_id
        for (row_id,) in db.query(EstimateCostLine.id)
        .filter(EstimateCostLine.task_id == task.id)
        .all()
    } - excluded_cost_line_ids
    still_referenced = (
        bool(remaining_assignment_ids)
        or bool(remaining_cost_line_ids)
        or db.query(EstimateLine.id).filter(EstimateLine.task_id == task.id).first() is not None
        or db.query(EstimateTaskRow.id)
        .filter(EstimateTaskRow.task_id == task.id)
        .filter(EstimateTaskRow.id != excluding_task_row_id)
        .first()
        is not None
        or db.query(EstimateTaskRow.id).filter(EstimateTaskRow.parent_task_id == task.id).first()
        is not None
        or db.query(WfChargeLine.id)
        .filter(WfChargeLine.project_id == project.id, WfChargeLine.task_uid == task.uid)
        .first()
        is not None
    )
    if still_referenced:
        return ReconciliationIssue(
            code="TASK_DELETE_REFERENCED",
            message=(
                f"Task row {excluding_task_row_id} is still referenced by another "
                "estimate, assignment or charge and cannot be deleted"
            ),
            sheet="Tâches",
            row=None,
        )
    return None


def _precheck_task_deletions(
    db: Session,
    project: MsProject,
    planning_for_tasks: WfPlanning | None,
    task_row_ids: list[int],
    existing_task_rows: dict[int, EstimateTaskRow],
    labor_to_delete_ids: list[int],
    non_labor_to_delete_ids: list[int],
    labor_creates: list[_LaborCreateCandidate],
    non_labor_creates: list[_CostLineCreateCandidate],
    issues: list[ReconciliationIssue],
) -> None:
    excluded_assignment_ids = set(labor_to_delete_ids)
    excluded_cost_line_ids = set(non_labor_to_delete_ids)
    # task_ids referenced by a brand new MO/Non-MO row staged in this same file (E6-09
    # Finding Haute #2, round 3 review) -- see _task_deletion_blocking_issue's own
    # docstring for why the DB-backed "still referenced" queries below can never see
    # these on their own.
    new_row_task_ids = {candidate.task_id for candidate in labor_creates} | {
        candidate.task_id for candidate in non_labor_creates if candidate.task_id is not None
    }
    for task_row_id in task_row_ids:
        existing_row = existing_task_rows[task_row_id]
        if existing_row.task_id is None:
            # No legacy MsTask twin to delete from the planning tree -- just the
            # EstimateTaskRow itself, which is always safe to drop.
            continue
        task = (
            db.query(MsTask)
            .filter(MsTask.id == existing_row.task_id, MsTask.project_id == project.id)
            .first()
        )
        if task is None:
            continue
        issue = _task_deletion_blocking_issue(
            db,
            project,
            planning_for_tasks,
            task,
            excluding_task_row_id=task_row_id,
            excluded_assignment_ids=excluded_assignment_ids,
            excluded_cost_line_ids=excluded_cost_line_ids,
            referenced_by_new_row=task.id in new_row_task_ids,
        )
        if issue is not None:
            issues.append(issue)


def _apply_cost_line_deletes(
    db: Session, cost_line_ids: list[int], existing_cost_lines: dict[int, EstimateCostLine]
) -> None:
    # Issue #289 (E12-07): same dangling-node rationale as delete_estimate_cost_line
    # -- node_id is a NOT NULL, unique FK, so the owning grid node is collected
    # before the line itself is deleted, then removed once nothing references it.
    node_ids = [existing_cost_lines[cost_line_id].node_id for cost_line_id in cost_line_ids]
    for cost_line_id in cost_line_ids:
        db.delete(existing_cost_lines[cost_line_id])
    db.flush()
    if node_ids:
        db.query(EstimateGridNode).filter(EstimateGridNode.id.in_(node_ids)).delete(
            synchronize_session=False
        )


def _apply_labor_deletes(
    db: Session, assignment_ids: list[int], existing_assignments: dict[int, EstimateRoleAssignment]
) -> None:
    # Issue #289 (E12-07): same dangling-node rationale as delete_estimate_role_assignment.
    node_ids = [existing_assignments[assignment_id].node_id for assignment_id in assignment_ids]
    for assignment_id in assignment_ids:
        db.delete(existing_assignments[assignment_id])
    db.flush()
    if node_ids:
        db.query(EstimateGridNode).filter(EstimateGridNode.id.in_(node_ids)).delete(
            synchronize_session=False
        )


def _apply_task_deletes(
    db: Session,
    project: MsProject,
    planning_for_tasks: WfPlanning | None,
    task_row_ids: list[int],
    existing_task_rows: dict[int, EstimateTaskRow],
) -> None:
    """Delete each proposed ``EstimateTaskRow``, cascading to its planning task via E3-05.

    Only ever reached once ``_precheck_task_deletions`` has found no blocking issue
    for any of ``task_row_ids`` (see ``_run_reconciliation``): deleting the
    ``EstimateTaskRow`` first is what lets its own ``task_id`` reference stop
    counting against itself once ``delete_planning_tasks`` re-runs
    ``find_referenced_task_uids`` for real.
    """
    for task_row_id in task_row_ids:
        existing_row = existing_task_rows[task_row_id]
        db.delete(existing_row)
        db.flush()
        if existing_row.task_id is None or planning_for_tasks is None:
            continue
        task = (
            db.query(MsTask)
            .filter(MsTask.id == existing_row.task_id, MsTask.project_id == project.id)
            .first()
        )
        if task is not None:
            delete_planning_tasks(
                db,
                planning_for_tasks,
                PlanningTaskDelete(
                    task_uids=[task.uid],
                    confirm_cascade=False,
                    expected_revision=planning_for_tasks.revision,
                ),
            )


def _apply_task_creates(
    db: Session,
    project: MsProject,
    estimate: Estimate,
    planning_for_tasks: WfPlanning | None,
    task_creates: list[_TaskCreateCandidate],
) -> None:
    if planning_for_tasks is None:
        return
    for candidate in task_creates:
        _create_estimate_planning_task(
            db,
            project.id,
            estimate.id,
            planning_for_tasks,
            name=candidate.name,
            is_milestone=candidate.is_milestone,
            target_parent_uid=candidate.target_parent_uid,
            insert_after_uid=None,
        )


def _apply_labor_creates(
    db: Session, project: MsProject, estimate: Estimate, labor_creates: list[_LaborCreateCandidate]
) -> None:
    for candidate in labor_creates:
        cost_code_id = resolve_cost_code_id(db, project.id, candidate.cost_code_id)
        # Issue #289 (E12-07): last child of the devis root, same default as
        # create_estimate_role_assignment's own EstimateRoleAssignmentCreate
        # (this reconciliation import candidate has no explicit tree position).
        node = create_estimate_grid_node(
            db, estimate, kind="labor", target_parent_uid=None, insert_after_uid=None
        )
        assignment = EstimateRoleAssignment(
            estimate_id=estimate.id,
            task_id=candidate.task_id,
            role_id=candidate.role_id,
            cost_code_id=cost_code_id,
            quantity=candidate.quantity,
            hours=candidate.hours,
            comment=candidate.comment,
            node_id=node.id,
        )
        db.add(assignment)
    db.flush()


def _apply_cost_line_creates(
    db: Session,
    project: MsProject,
    estimate: Estimate,
    non_labor_creates: list[_CostLineCreateCandidate],
) -> None:
    for candidate in non_labor_creates:
        category, cost_type = get_non_labor_category_or_400(db, candidate.cost_category_id)
        cost_code_id = resolve_cost_code_id(db, project.id, candidate.cost_code_id)
        supply_status = "planned" if cost_type.kind == CostTypeKind.SUPPLY else None
        if candidate.supply_status is not None:
            if not _cost_line_supply_status_is_compatible(cost_type.kind, candidate.supply_status):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Supply status is only valid for supplies",
                )
            supply_status = candidate.supply_status
        # Issue #289 (E12-07): last child of the devis root, same default as
        # create_estimate_cost_line's own EstimateCostLineCreate (this
        # reconciliation import candidate has no explicit tree position).
        node = create_estimate_grid_node(
            db, estimate, kind="cost_line", target_parent_uid=None, insert_after_uid=None
        )
        line = EstimateCostLine(
            estimate_id=estimate.id,
            task_id=candidate.task_id,
            cost_type_id=cost_type.id,
            cost_category_id=category.id,
            cost_code_id=cost_code_id,
            cost_type_code=cost_type.code,
            accounting_code=category.accounting_code,
            category_code=category.category_code,
            label=candidate.label,
            quantity=candidate.quantity,
            unit_cost=candidate.unit_cost,
            purchase_cost=candidate.quantity * candidate.unit_cost,
            supply_status=supply_status,
            planned_date=candidate.planned_date,
            node_id=node.id,
        )
        db.add(line)
    db.flush()


def _apply_labor_updates(
    db: Session,
    project: MsProject,
    labor_updates: list[_LaborUpdateCandidate],
    existing_assignments: dict[int, EstimateRoleAssignment],
) -> None:
    for update in labor_updates:
        assignment = existing_assignments[update.assignment_id]
        # A blank cost_code_id cell means "unchanged" (see the matching comment in
        # _stage_existing_labor_row, E6-09 Critical finding, round 3 review):
        # resolve_cost_code_id's None means "attach to the project's active root",
        # which is only the right default for a *creation*, never a silent
        # reassignment away from an already-set attachment on an update.
        if update.cost_code_id is not None:
            assignment.cost_code_id = resolve_cost_code_id(db, project.id, update.cost_code_id)
        assignment.quantity = update.quantity
        assignment.hours = update.hours
        assignment.comment = update.comment
        db.add(assignment)
    db.flush()


def _resolve_cost_line_update_supply_status(
    cost_type: CostType, requested: str | None, current: str | None
) -> str | None:
    if cost_type.kind == CostTypeKind.SUPPLY:
        return requested or current or "planned"
    if not _cost_line_supply_status_is_compatible(cost_type.kind, requested):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Supply status is only valid for supplies",
        )
    return None


def _apply_cost_line_updates(
    db: Session,
    project: MsProject,
    non_labor_updates: list[_CostLineUpdateCandidate],
    existing_cost_lines: dict[int, EstimateCostLine],
) -> None:
    for update in non_labor_updates:
        line = existing_cost_lines[update.line_id]
        category, cost_type = get_non_labor_category_or_400(
            db,
            update.cost_category_id
            if update.cost_category_id is not None
            else line.cost_category_id,
        )
        supply_status = _resolve_cost_line_update_supply_status(
            cost_type, update.supply_status, line.supply_status
        )
        # A blank task_id/cost_code_id/planned_date cell means "unchanged", exactly
        # like the label/quantity/unit_cost protection just below -- never a silent
        # detach/clear of an otherwise-untouched row (see #70's Critical finding: a
        # stray blank cell must not delete data by accident). This matters especially
        # for cost_code_id: resolve_cost_code_id's None means "attach to the project's
        # active root", which is only the right default for a *creation*, never a
        # silent reassignment away from an already-set attachment on an update (round
        # 3 review).
        line.task_id = update.task_id if update.task_id is not None else line.task_id
        line.cost_category_id = category.id
        if update.cost_code_id is not None:
            line.cost_code_id = resolve_cost_code_id(db, project.id, update.cost_code_id)
        line.cost_type_id = cost_type.id
        line.cost_type_code = cost_type.code
        line.accounting_code = category.accounting_code
        line.category_code = category.category_code
        line.label = update.label if update.label is not None else line.label
        line.quantity = update.quantity if update.quantity is not None else line.quantity
        line.unit_cost = update.unit_cost if update.unit_cost is not None else line.unit_cost
        line.supply_status = supply_status
        line.purchase_cost = line.quantity * line.unit_cost
        line.planned_date = (
            update.planned_date if update.planned_date is not None else line.planned_date
        )
        db.add(line)
    db.flush()


def _run_reconciliation(
    db: Session,
    project: MsProject,
    estimate: Estimate,
    parsed: ParsedReconciliationWorkbook,
    *,
    apply: bool,
) -> ReconciliationPlanRead:
    """Shared preview/confirm analysis for the Excel reconciliation import (E6-09/#70).

    Takes an already-parsed workbook rather than raw bytes: parsing (CPU-bound
    openpyxl work) is the caller's responsibility, done exactly once per
    request, before any project row lock is taken (see the Finding Haute note
    on ``confirm_estimate_reconciliation_import``, which calls this function
    twice on the *same* ``parsed`` value -- once unlocked to precheck, once
    locked to apply -- without ever parsing the upload a second time).

    Staging (everything up to and including ``_precheck_task_deletions``) is
    always 100% read-only, for both ``preview`` and ``confirm``: it is what
    guarantees the two endpoints report byte-identical diagnostics on the same
    file. Real mutation only ever happens when ``apply=True`` *and* the staging
    phase found zero blocking issues -- meaning ``preview`` (always
    ``apply=False``) never writes anything, and ``confirm`` writes exactly once,
    in one pass, only when it is already known to be safe. See
    ``_task_deletion_blocking_issue``'s own docstring for why this reads ahead
    with plain queries instead of attempting each mutation and catching a
    failure: a nested-SAVEPOINT-then-later-rollback pattern (the more obvious
    design) silently loses its rollback under SQLite's pysqlite driver, which
    the test suite runs on.

    Order, chosen to avoid FK conflicts (see #70's issue body): deletions
    (Non-MO, then MO, then Tasks -- a cost line or assignment can reference a
    task about to be deleted) before creations (Tasks first, so a brand new
    task is queryable by id for any MO/Non-MO row of the same file that
    happens to reference it) before updates (MO, then Non-MO).

    Documented limitation (accepted to keep #70 shippable in one evening,
    see the issue thread): a *new* Tasks-sheet row can only reference an
    *existing* task as its parent (via ``parent_task_id``), never another new
    row created in the same file -- there is no multi-level topological
    resolution of cascaded creations.

    ``estimate.revision`` is bumped exactly once for the whole batch when any
    MO/Non-MO row is created or deleted (Finding Haute, #289 review): every one
    of those four mutates the devis grid node tree, exactly like
    ``create_estimate_cost_line``/``create_estimate_role_assignment``/
    ``delete_estimate_cost_line``/``delete_estimate_role_assignment`` -- a single
    bump for the batch, not one per row, mirroring the ``planning_for_tasks.revision``
    bump just above it.
    """
    issues: list[ReconciliationIssue] = []
    warnings: list[ReconciliationIssue] = []

    existing_task_rows = {
        row.id: row
        for row in db.query(EstimateTaskRow)
        .filter(EstimateTaskRow.estimate_id == estimate.id)
        .all()
    }
    # Same draft/validated branch as the export (_write_tasks_sheet) and the
    # JSON read (list_estimate_task_rows): a draft devis's Tâches sheet was
    # written from the *live* task display, so the reimport diff must be
    # taken against that same baseline, not the frozen stored columns
    # (E12-08 Finding Haute #1, round 4 review).
    resolved_by_row_id = (
        resolve_live_task_display(db, project, list(existing_task_rows.values()))
        if estimate.status == "draft"
        else {}
    )
    existing_assignments: dict[int, EstimateRoleAssignment] = {}
    out_of_scope_assignment_ids: set[int] = set()
    for assignment, _task, _role, _category, hors_perimetre in _scoped_estimate_role_assignments(
        db, project, estimate
    ):
        existing_assignments[assignment.id] = assignment
        if hors_perimetre:
            out_of_scope_assignment_ids.add(assignment.id)
    existing_cost_lines = {
        line.id: line
        for line in db.query(EstimateCostLine)
        .filter(EstimateCostLine.estimate_id == estimate.id)
        .all()
    }

    task_creates, tasks_to_delete_ids = _stage_task_sheet(
        db, project, parsed.tasks, existing_task_rows, resolved_by_row_id, issues, warnings
    )
    labor_creates, labor_updates, labor_to_delete_ids = _stage_labor_sheet(
        db,
        project,
        parsed.labor,
        existing_assignments,
        out_of_scope_assignment_ids,
        issues,
        warnings,
    )
    non_labor_creates, non_labor_updates, non_labor_to_delete_ids = _stage_cost_line_sheet(
        db, project, parsed.cost_lines, existing_cost_lines, issues
    )

    planning_for_tasks = _resolve_planning_for_tasks(
        db,
        project,
        needs_mutation=bool(task_creates or tasks_to_delete_ids),
        issues=issues,
    )
    if tasks_to_delete_ids:
        _precheck_task_deletions(
            db,
            project,
            planning_for_tasks,
            tasks_to_delete_ids,
            existing_task_rows,
            labor_to_delete_ids,
            non_labor_to_delete_ids,
            labor_creates,
            non_labor_creates,
            issues,
        )

    applied = False
    if apply and not issues:
        # ---- Apply: deletions (Non-MO, then MO, then Tâches) ----
        _apply_cost_line_deletes(db, non_labor_to_delete_ids, existing_cost_lines)
        _apply_labor_deletes(db, labor_to_delete_ids, existing_assignments)
        _apply_task_deletes(
            db, project, planning_for_tasks, tasks_to_delete_ids, existing_task_rows
        )

        # ---- Apply: creations (Tâches first, then MO/Non-MO) ----
        _apply_task_creates(db, project, estimate, planning_for_tasks, task_creates)
        if (task_creates or tasks_to_delete_ids) and planning_for_tasks is not None:
            # Single bump for the whole batch, like every other multi-task mutation in
            # this module (see create_estimate_task/create_estimate_cost_line_milestones).
            planning_for_tasks.revision += 1
            db.add(planning_for_tasks)
            db.flush()
        _apply_labor_creates(db, project, estimate, labor_creates)
        _apply_cost_line_creates(db, project, estimate, non_labor_creates)
        if labor_to_delete_ids or non_labor_to_delete_ids or labor_creates or non_labor_creates:
            # Finding Haute (#289 review): every one of the four applies above
            # creates or deletes an EstimateGridNode, exactly like
            # create_estimate_cost_line/create_estimate_role_assignment/
            # delete_estimate_cost_line/delete_estimate_role_assignment -- same
            # single bump for the whole batch as the planning.revision bump
            # just above, not one per row.
            estimate.revision += 1
            db.add(estimate)
            db.flush()

        # ---- Apply: updates (MO, then Non-MO) ----
        _apply_labor_updates(db, project, labor_updates, existing_assignments)
        _apply_cost_line_updates(db, project, non_labor_updates, existing_cost_lines)
        applied = True

    return ReconciliationPlanRead(
        blocking_issues=issues,
        warnings=warnings,
        tasks_to_create=len(task_creates),
        tasks_to_delete=tasks_to_delete_ids,
        labor_to_create=len(labor_creates),
        labor_to_update=[candidate.assignment_id for candidate in labor_updates],
        labor_to_delete=labor_to_delete_ids,
        non_labor_to_create=len(non_labor_creates),
        non_labor_to_update=[candidate.line_id for candidate in non_labor_updates],
        non_labor_to_delete=non_labor_to_delete_ids,
        applied=applied,
    )


def _reconciliation_format_error_response(exc: EstimateReconciliationFormatError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "RECONCILIATION_FORMAT_ERROR", "issues": exc.issues},
    )


_RECONCILIATION_UPLOAD_CHUNK_SIZE = 1024 * 1024


async def _read_reconciliation_upload(file: UploadFile) -> bytes:
    """Read an uploaded reconciliation workbook, rejecting it past the configured size limit.

    Reuses ``settings.import_max_upload_bytes`` -- already enforced on the MS
    Project XML import pipeline, see ``imports.py::_stage_source_xml`` -- rather
    than introducing a second, reconciliation-specific setting: both endpoints
    accept an arbitrary user-supplied file over the same kind of HTTP upload,
    so one limit is enough (E6-09 Finding Moyenne #1). Reads in fixed-size
    chunks rather than the whole body at once, so an oversized upload is
    rejected as soon as the limit is crossed instead of after being fully
    buffered in memory.
    """
    settings = get_settings()
    chunks: list[bytes] = []
    byte_count = 0
    while chunk := await file.read(_RECONCILIATION_UPLOAD_CHUNK_SIZE):
        byte_count += len(chunk)
        if byte_count > settings.import_max_upload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Reconciliation workbook exceeds the configured size limit",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/{project_id}/estimates/{estimate_id}/import-reconciliation/preview",
    response_model=ReconciliationPlanRead,
    responses={
        status.HTTP_413_CONTENT_TOO_LARGE: {
            "model": FastAPIErrorResponse,
            "description": "Classeur de reconciliation trop volumineux",
        },
    },
)
async def preview_estimate_reconciliation_import(
    project_id: int,
    estimate_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ReconciliationPlanRead:
    """Parse + diff an Excel reconciliation file against the current devis (E6-09/#70).

    Never writes anything: ``_run_reconciliation`` is called with ``apply=False``,
    so it stays a pure read-only analysis (see its own docstring). Runs the exact
    same analysis ``.../confirm`` would run on the same file, so this accurately
    predicts what a confirm would do.

    Takes no mutating (``FOR UPDATE``) project lock -- ``get_project_or_404``
    here, exactly like the read-only ``export_estimate_reconciliation_excel``
    sibling route, never ``get_mutable_project_lock`` -- since a preview never
    writes: holding a row lock across the network upload and the (CPU-bound)
    openpyxl parse below would needlessly block every other writer on this
    project for the whole request (E6-09 Finding Haute).
    """
    project = get_project_or_404(db, project_id, current_user.id)
    estimate = get_draft_estimate_or_409(db, project_id, estimate_id)
    content = await _read_reconciliation_upload(file)
    try:
        parsed = parse_estimate_reconciliation_workbook(content)
        plan = _run_reconciliation(db, project, estimate, parsed, apply=False)
    except EstimateReconciliationFormatError as exc:
        db.rollback()
        raise _reconciliation_format_error_response(exc) from exc
    db.rollback()
    return plan


@router.post(
    "/{project_id}/estimates/{estimate_id}/import-reconciliation/confirm",
    response_model=ReconciliationPlanRead,
    responses={
        status.HTTP_409_CONFLICT: {
            "model": ReconciliationPlanRead | PlanningTaskDeleteConflict,
            "description": (
                "Soit des problemes bloquants ont ete trouves et rien n'a ete "
                "applique (ReconciliationPlanRead complet, applied=false) ; soit "
                "le precheck (hors verrou) n'a rien trouve mais une ecriture "
                "concurrente a fait echouer la suppression de tache reelle une "
                "fois le verrou pris (PlanningTaskDeleteConflict, "
                "detail.code=CASCADE_CONFIRMATION_REQUIRED/TASK_REFERENCED), "
                "exactement comme la suppression directe de taches du planning"
            ),
        },
        status.HTTP_413_CONTENT_TOO_LARGE: {
            "model": FastAPIErrorResponse,
            "description": "Classeur de reconciliation trop volumineux",
        },
    },
)
async def confirm_estimate_reconciliation_import(
    project_id: int,
    estimate_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ReconciliationPlanRead | JSONResponse:
    """Re-run ``.../preview``'s analysis on the (re-submitted) file, and apply it (E6-09/#70).

    The client resubmits the exact same file rather than referencing a
    previous preview: there is no server-side import session/staging table
    for this lightweight, synchronous reconciliation (unlike the generic
    ``WfImportBatch``/MS Project XML import pipeline). Any blocking issue
    means nothing is written -- the final ``_run_reconciliation`` call (with
    ``apply=True``) only mutates when it found zero blocking issues, so a
    non-empty ``blocking_issues`` here always means ``applied=False``; the
    response then reports that with a 409, never a misleadingly successful 2xx.

    Lock ordering (E6-09 Finding Haute): the network upload, the size check
    and the openpyxl parse all happen before any project row lock is taken --
    exactly like ``.../preview`` -- via an initial, unlocked
    ``_run_reconciliation(..., apply=False)`` precheck. Only once that
    precheck reports zero blocking issues is ``get_mutable_project_lock``
    acquired, the estimate's draft status re-verified under that lock, and
    staging run a *second* time -- this time with ``apply=True`` -- reusing
    the same already-parsed workbook (``parsed``), so the (comparatively
    expensive) openpyxl parse itself never runs twice, only the cheap DB-read
    staging queries do. Redoing staging under the lock, rather than trusting
    the unlocked precheck, is what closes the TOCTOU window between the two:
    any state change that raced in during that window (e.g. another request
    deleting a task this file also references) is caught by the second pass
    exactly like any other blocking issue -- reported as a 409 with nothing
    applied, never a silent corruption.

    A handful of PlanningTree*/IntegrityError exceptions can still legitimately
    escape the locked ``_run_reconciliation`` call despite that -- its own
    read-only precheck mirrors ``delete_planning_tasks``'s own invariants but
    can still race a concurrent writer between precheck and apply -- translated
    to the same status codes the equivalent direct Planning-tree endpoints
    already use.
    """
    project = get_project_or_404(db, project_id, current_user.id)
    estimate = get_draft_estimate_or_409(db, project_id, estimate_id)
    content = await _read_reconciliation_upload(file)
    try:
        parsed = parse_estimate_reconciliation_workbook(content)
    except EstimateReconciliationFormatError as exc:
        db.rollback()
        raise _reconciliation_format_error_response(exc) from exc

    precheck = _run_reconciliation(db, project, estimate, parsed, apply=False)
    db.rollback()
    if precheck.blocking_issues:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=jsonable_encoder(precheck),
        )

    project = get_mutable_project_lock(db, project_id, current_user.id)
    estimate = get_draft_estimate_or_409(db, project_id, estimate_id)
    try:
        plan = _run_reconciliation(db, project, estimate, parsed, apply=True)
    except PlanningTreeCascadeConfirmationRequiredError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CASCADE_CONFIRMATION_REQUIRED",
                "descendant_uids": exc.descendant_uids,
            },
        ) from exc
    except PlanningTreeTaskReferencedError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "TASK_REFERENCED", "task_uids": exc.task_uids},
        ) from exc
    except PlanningTreeMoveNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PlanningTreeInvariantError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PlanningTreeMoveError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reconciliation import conflicts with existing planning data",
        ) from exc
    if not plan.applied:
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=jsonable_encoder(plan),
        )
    db.commit()
    return plan


@router.get(
    "/{project_id}/estimates/{estimate_id}/cost-lines",
    response_model=EstimateCostLineListRead,
)
def list_estimate_cost_lines(
    project_id: int,
    estimate_id: int,
    params: ListParams = Depends(list_params),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateCostLineListRead:
    get_project_or_404(db, project_id, current_user.id)
    get_estimate_or_404(db, project_id, estimate_id)
    query = db.query(EstimateCostLine).filter(EstimateCostLine.estimate_id == estimate_id)
    result = apply_pagination(
        query,
        params,
        sortable={
            "label": EstimateCostLine.label,
            "quantity": EstimateCostLine.quantity,
            "unit_cost": EstimateCostLine.unit_cost,
            "purchase_cost": EstimateCostLine.purchase_cost,
            "created_at": EstimateCostLine.created_at,
        },
        tiebreaker=EstimateCostLine.id,
        searchable=[EstimateCostLine.label],
    )
    return EstimateCostLineListRead(
        items=[to_estimate_cost_line_read(line) for line in result.rows],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post(
    "/{project_id}/estimates/{estimate_id}/cost-lines",
    response_model=EstimateCostLineRead,
    status_code=status.HTTP_201_CREATED,
)
def create_estimate_cost_line(
    project_id: int,
    estimate_id: int,
    payload: EstimateCostLineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateCostLineRead:
    get_mutable_project_lock(db, project_id, current_user.id)
    estimate = get_draft_estimate_or_409(db, project_id, estimate_id)
    if payload.task_id is not None:
        task = db.query(MsTask).filter(MsTask.id == payload.task_id).first()
        if task is None or task.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Task does not belong to project",
            )
    category, cost_type = get_non_labor_category_or_400(db, payload.cost_category_id)
    cost_code_id = resolve_cost_code_id(db, project_id, payload.cost_code_id)
    supply_status = "planned" if cost_type.kind == CostTypeKind.SUPPLY else None
    if payload.supply_status is not None:
        if cost_type.kind != CostTypeKind.SUPPLY:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Supply status is only valid for supplies",
            )
        supply_status = payload.supply_status

    # Issue #289 (E12-07): the line's own position in the devis grid tree --
    # defaults to the last child of the devis root, independent of task_id.
    try:
        node = create_estimate_grid_node(
            db,
            estimate,
            kind="cost_line",
            target_parent_uid=payload.target_parent_uid,
            insert_after_uid=payload.insert_after_uid,
        )
    except EstimateGridMoveNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except EstimateGridMoveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    line = EstimateCostLine(
        estimate_id=estimate_id,
        task_id=payload.task_id,
        cost_type_id=cost_type.id,
        cost_category_id=category.id,
        cost_code_id=cost_code_id,
        cost_type_code=cost_type.code,
        accounting_code=category.accounting_code,
        category_code=category.category_code,
        label=payload.label,
        quantity=payload.quantity,
        unit_cost=payload.unit_cost,
        purchase_cost=payload.quantity * payload.unit_cost,
        supply_status=supply_status,
        planned_date=payload.planned_date,
        node_id=node.id,
    )
    db.add(line)
    # Issue #289 (E12-07) review finding (Finding Haute): creating a line adds a
    # node to the grid tree, exactly like grid-nodes/move -- must bump revision
    # the same way, or a concurrent move's optimistic-lock expected_revision
    # check can pass against a tree that actually changed underneath it.
    estimate.revision += 1
    db.add(estimate)
    # Flush (not commit) first, so the response can be built while the project
    # lock is still held -- commit is last, matching create_estimate_task/
    # create_estimate_role_assignment/create_estimate_cost_line_milestones,
    # never the commit-then-refresh pattern (tech debt #262).
    db.flush()
    response = to_estimate_cost_line_read(line)
    db.commit()
    return response


@router.patch(
    "/{project_id}/estimates/{estimate_id}/cost-lines/{line_id}",
    response_model=EstimateCostLineRead,
)
def update_estimate_cost_line(
    project_id: int,
    estimate_id: int,
    line_id: int,
    payload: EstimateCostLineUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateCostLineRead:
    get_mutable_project_lock(db, project_id, current_user.id)
    get_draft_estimate_or_409(db, project_id, estimate_id)
    line = (
        db.query(EstimateCostLine)
        .filter(EstimateCostLine.id == line_id)
        .filter(EstimateCostLine.estimate_id == estimate_id)
        .first()
    )
    if line is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Estimate cost line not found",
        )

    values = payload.model_dump(exclude_unset=True)
    if "task_id" in values and values["task_id"] is not None:
        task = db.query(MsTask).filter(MsTask.id == values["task_id"]).first()
        if task is None or task.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Task does not belong to project",
            )
    if "cost_code_id" in values:
        # An explicit null resolves back to the project's root, exactly like an omitted
        # field does at create time -- never silently detaches the line from imputation
        # (the `.get(...) is not None` form used to let `{"cost_code_id": null}` bypass
        # both validation and the "always attached" invariant).
        values["cost_code_id"] = resolve_cost_code_id(db, project_id, values["cost_code_id"])

    category, cost_type = get_non_labor_category_or_400(
        db,
        values.get("cost_category_id", line.cost_category_id),
    )
    supply_status = values.get("supply_status", line.supply_status)
    if cost_type.kind == CostTypeKind.SUPPLY:
        supply_status = supply_status or "planned"
    else:
        if values.get("supply_status") is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Supply status is only valid for supplies",
            )
        supply_status = None

    for field, value in values.items():
        setattr(line, field, value)
    line.cost_type_id = cost_type.id
    line.cost_category_id = category.id
    line.cost_type_code = cost_type.code
    line.accounting_code = category.accounting_code
    line.category_code = category.category_code
    line.supply_status = supply_status
    line.purchase_cost = line.quantity * line.unit_cost
    db.add(line)
    db.commit()
    db.refresh(line)
    return to_estimate_cost_line_read(line)


@router.delete(
    "/{project_id}/estimates/{estimate_id}/cost-lines/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_estimate_cost_line(
    project_id: int,
    estimate_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    get_mutable_project_lock(db, project_id, current_user.id)
    estimate = get_draft_estimate_or_409(db, project_id, estimate_id)
    line = (
        db.query(EstimateCostLine)
        .filter(EstimateCostLine.id == line_id)
        .filter(EstimateCostLine.estimate_id == estimate_id)
        .first()
    )
    if line is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Estimate cost line not found",
        )
    # Issue #289 (E12-07): node_id is a NOT NULL, unique FK -- every line owns
    # exactly one grid node, so deleting the line without its node would leave
    # a dangling, unreferenced node behind.
    node = db.query(EstimateGridNode).filter(EstimateGridNode.id == line.node_id).one()
    db.delete(line)
    # Flushed before deleting node: EstimateCostLine.node_id has no declared ORM
    # relationship() to EstimateGridNode (a plain FK column only), so the unit of
    # work has no dependency info to order these two deletes correctly on its own.
    db.flush()
    db.delete(node)
    # Finding Haute (#289 review): removing a line removes a grid node too --
    # same revision-bump obligation as create_estimate_cost_line/grid-nodes/move.
    estimate.revision += 1
    db.add(estimate)
    db.commit()


@router.get(
    "/{project_id}/estimates/{estimate_id}/role-assignments",
    response_model=EstimateRoleAssignmentListRead,
)
def list_estimate_role_assignments(
    project_id: int,
    estimate_id: int,
    params: ListParams = Depends(list_params),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateRoleAssignmentListRead:
    get_project_or_404(db, project_id, current_user.id)
    get_estimate_or_404(db, project_id, estimate_id)
    query = (
        db.query(EstimateRoleAssignment, ResourceRole, CostCategory)
        .join(ResourceRole, EstimateRoleAssignment.role_id == ResourceRole.id)
        .join(CostCategory, ResourceRole.cost_category_id == CostCategory.id)
        .filter(EstimateRoleAssignment.estimate_id == estimate_id)
    )
    result = apply_pagination(
        query,
        params,
        sortable={
            "role_name": ResourceRole.name,
            "quantity": EstimateRoleAssignment.quantity,
            "hours": EstimateRoleAssignment.hours,
        },
        default_sort=ResourceRole.name,
        tiebreaker=EstimateRoleAssignment.id,
        searchable=(ResourceRole.name,),
    )
    return EstimateRoleAssignmentListRead(
        items=[
            to_estimate_role_assignment_read(assignment, role, category)
            for assignment, role, category in result.rows
        ],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post(
    "/{project_id}/estimates/{estimate_id}/role-assignments",
    response_model=EstimateRoleAssignmentRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": MissingRateCoverage | FastAPIErrorResponse,
            "description": (
                "Requete invalide -- tache hors du projet, role hors d'une "
                "categorie de cout main-d'oeuvre active (detail generique), "
                "ou tache deja datee avec au moins une (categorie de cout, "
                "annee) sans CostRate/InflationRate (detail.code="
                "MISSING_RATE_COVERAGE, E6-11/#175)"
            ),
        },
    },
)
def create_estimate_role_assignment(
    project_id: int,
    estimate_id: int,
    payload: EstimateRoleAssignmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateRoleAssignmentRead:
    """Create a devis-scoped labor role assignment (E12-01/#273).

    Replaces the removed project-wide ``create_task_role_assignment``
    (``tasks.py``): ``payload.task_id`` refers directly to ``MsTask.id`` (like
    ``EstimateCostLineCreate.task_id``), so the "snapshot-only task" 409 guard
    the removed route needed (to bridge a planning uid to its legacy ``MsTask``
    twin) no longer applies -- a task with no ``MsTask`` twin simply has no id
    a caller could reference here at all. Refuses with 409 if ``estimate_id``
    is not a draft (new in this issue, mirroring ``EstimateCostLine``'s own rule).
    """
    get_mutable_project_lock(db, project_id, current_user.id)
    estimate = get_draft_estimate_or_409(db, project_id, estimate_id)

    task = (
        db.query(MsTask)
        .filter(MsTask.id == payload.task_id, MsTask.project_id == project_id)
        .first()
    )
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task does not belong to project",
        )

    row = (
        db.query(ResourceRole, CostCategory, CostType)
        .join(CostCategory, ResourceRole.cost_category_id == CostCategory.id)
        .join(CostType, CostCategory.cost_type_id == CostType.id)
        .filter(ResourceRole.id == payload.role_id)
        .filter(ResourceRole.is_active.is_(True))
        .filter(CostCategory.is_active.is_(True))
        .filter(CostType.kind == CostTypeKind.LABOR)
        .filter(CostType.is_active.is_(True))
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must belong to an active labor cost category",
        )
    role, category, _ = row
    cost_code_id = resolve_cost_code_id(db, project_id, payload.cost_code_id)

    # Issue #175 (E6-11): same creation-time guard the removed
    # create_task_role_assignment (tasks.py) applied -- a task that is already
    # dated (both start_at and finish_at set) must have full CostRate/
    # InflationRate coverage for every year it spans.
    if task.start_at is not None and task.finish_at is not None:
        category_years = [
            (category, year) for year in range(task.start_at.year, task.finish_at.year + 1)
        ]
        missing_cost_rates, missing_inflation_years = collect_missing_rate_coverage(
            db, category_years
        )
        if missing_cost_rates or missing_inflation_years:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=missing_rate_coverage_detail(missing_cost_rates, missing_inflation_years),
            )

    # Issue #289 (E12-07): the assignment's own position in the devis grid
    # tree -- defaults to the last child of the devis root, independent of
    # task_id.
    try:
        node = create_estimate_grid_node(
            db,
            estimate,
            kind="labor",
            target_parent_uid=payload.target_parent_uid,
            insert_after_uid=payload.insert_after_uid,
        )
    except EstimateGridMoveNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except EstimateGridMoveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    assignment = EstimateRoleAssignment(
        estimate_id=estimate_id,
        task_id=task.id,
        role_id=payload.role_id,
        cost_code_id=cost_code_id,
        quantity=payload.quantity,
        hours=payload.hours,
        comment=payload.comment,
        node_id=node.id,
    )
    db.add(assignment)
    # Issue #289 (E12-07) review finding (Finding Haute): same revision-bump
    # obligation as create_estimate_cost_line -- adding a node to the grid tree
    # must not go unnoticed by a concurrent grid-nodes/move's optimistic lock.
    estimate.revision += 1
    db.add(estimate)
    try:
        # Flush (not commit) first, so the response can be built while the project
        # lock is still held -- commit is last, matching create_estimate_task/
        # create_estimate_cost_line_milestones, never the commit-then-refresh
        # pattern (tech debt #262) the removed create_task_role_assignment used.
        db.flush()
        response = to_estimate_role_assignment_read(assignment, role, category)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Role is already assigned to this task on this estimate",
        ) from exc
    return response


@router.patch(
    "/{project_id}/estimates/{estimate_id}/role-assignments/{assignment_id}",
    response_model=EstimateRoleAssignmentRead,
)
def update_estimate_role_assignment(
    project_id: int,
    estimate_id: int,
    assignment_id: int,
    payload: EstimateRoleAssignmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateRoleAssignmentRead:
    """``task_id``/``role_id`` are immutable once created, so unlike ``create``
    above, no rate-coverage recheck is needed here -- only ``cost_code_id``/
    ``quantity``/``hours``/``comment`` may change."""
    get_mutable_project_lock(db, project_id, current_user.id)
    get_draft_estimate_or_409(db, project_id, estimate_id)
    row = (
        db.query(EstimateRoleAssignment, ResourceRole, CostCategory)
        .join(ResourceRole, EstimateRoleAssignment.role_id == ResourceRole.id)
        .join(CostCategory, ResourceRole.cost_category_id == CostCategory.id)
        .filter(EstimateRoleAssignment.id == assignment_id)
        .filter(EstimateRoleAssignment.estimate_id == estimate_id)
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role assignment not found",
        )

    assignment, role, category = row
    values = payload.model_dump(exclude_unset=True)
    if "cost_code_id" in values:
        # An explicit null resolves back to the project's root, exactly like an omitted
        # field does at create time -- never silently detaches the line from imputation.
        values["cost_code_id"] = resolve_cost_code_id(db, project_id, values["cost_code_id"])
    for field, value in values.items():
        setattr(assignment, field, value)
    db.add(assignment)
    # Same before-commit response construction as create_estimate_role_assignment.
    db.flush()
    response = to_estimate_role_assignment_read(assignment, role, category)
    db.commit()
    return response


@router.delete(
    "/{project_id}/estimates/{estimate_id}/role-assignments/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_estimate_role_assignment(
    project_id: int,
    estimate_id: int,
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    get_mutable_project_lock(db, project_id, current_user.id)
    estimate = get_draft_estimate_or_409(db, project_id, estimate_id)
    assignment = (
        db.query(EstimateRoleAssignment)
        .filter(EstimateRoleAssignment.id == assignment_id)
        .filter(EstimateRoleAssignment.estimate_id == estimate_id)
        .first()
    )
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role assignment not found",
        )
    # Issue #289 (E12-07): same dangling-node rationale (and flush-before-delete
    # ordering need) as delete_estimate_cost_line.
    node = db.query(EstimateGridNode).filter(EstimateGridNode.id == assignment.node_id).one()
    db.delete(assignment)
    db.flush()
    db.delete(node)
    # Finding Haute (#289 review): same revision-bump obligation as
    # delete_estimate_cost_line.
    estimate.revision += 1
    db.add(estimate)
    db.commit()


@router.post(
    "/{project_id}/estimates/{estimate_id}/grid-nodes/move",
    response_model=ProjectEstimateRead,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": FastAPIErrorResponse,
            "description": "Requete de deplacement invalide",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": FastAPIErrorResponse,
            "description": "Projet, devis, tache ou noeud introuvable pendant le deplacement",
        },
        status.HTTP_409_CONFLICT: {
            "model": FastAPIErrorResponse,
            "description": (
                "Le deplacement entre en conflit avec l'arbre du devis, ou "
                "expected_revision ne correspond plus a la revision persistee "
                "(code ESTIMATE_REVISION_CONFLICT)"
            ),
        },
    },
)
def move_estimate_grid_nodes_route(
    project_id: int,
    estimate_id: int,
    payload: EstimateGridNodeMove,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectEstimateRead:
    """Move/reorder a selection of a draft devis grid's cost-line/role-assignment
    nodes (E12-07, issue #289) -- mirrors ``move_planning_tasks_route``.
    """
    get_mutable_project_lock(db, project_id, current_user.id)
    estimate = get_draft_estimate_or_409(db, project_id, estimate_id)
    raise_on_estimate_revision_conflict(project_id, estimate, payload.expected_revision)
    try:
        move_estimate_grid_nodes(db, estimate, payload)
        estimate.revision += 1
        db.add(estimate)
        # Capture the response while the project lock is still held so a concurrent
        # writer cannot make us return a later transaction's state.
        response = to_project_estimate_read(estimate)
        db.commit()
    except EstimateGridMoveNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except EstimateGridInvariantError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except EstimateGridMoveError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Grid node hierarchy conflicts with existing estimate data",
        ) from exc
    return response


def _milestone_template_names(payload: EstimateCostLineMilestonesCreate) -> list[str]:
    """Fixed milestone names for each template (E6-07/#68) -- see ``MilestoneTemplate``."""
    if payload.template == MilestoneTemplate.FOURNITURE:
        return ["Commande", "Réception"]
    names = ["Commande"]
    names.extend(
        f"Jalon intermédiaire {index}"
        for index in range(1, payload.intermediate_milestones_count + 1)
    )
    names.append("Livraison")
    return names


def create_estimate_cost_line_milestones(
    project_id: int,
    estimate_id: int,
    line_id: int,
    payload: EstimateCostLineMilestonesCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateTaskRowListRead:
    """Apply a chained-milestone template to a non-labor cost line (E6-07/#68).

    Creates N+2 milestone tasks (``FOURNITURE``: 2, ``SOUS_TRAITANCE``: 2 +
    ``payload.intermediate_milestones_count``) via
    :func:`_create_estimate_planning_task` -- the same snapshot/``MsTask`` twin/
    ``EstimateTaskRow`` wiring #67 introduced -- then chains them pairwise with
    N+1 Finish-to-Start links (``link_type=1``) carrying the same
    ``payload.lag_minutes`` via :func:`replace_task_predecessor_links`. The
    milestones are siblings (all children of the same parent, or all roots),
    never a parent/child chain among themselves -- only the FS links relate
    them.

    When ``EstimateCostLine.task_id`` is set, the first milestone becomes that
    task's child (flipping its ``is_summary`` to ``True`` if it was a leaf,
    exactly like #67); otherwise every milestone is a root task. Either way,
    the whole chain is appended after every existing sibling rather than
    inserted at the front, since the templates model a sequence of *future*
    events for an already-priced cost line.

    Single transaction, single ``planning.revision`` bump for the whole
    call -- like every other batch planning-tree mutation in this module (see
    ``create_estimate_task``) -- not one per created task/link.
    """
    project = get_mutable_project_lock(db, project_id, current_user.id)
    planning = get_displayed_draft_planning_lock_or_409(db, project)
    get_draft_estimate_or_409(db, project_id, estimate_id)

    line = (
        db.query(EstimateCostLine)
        .filter(EstimateCostLine.id == line_id)
        .filter(EstimateCostLine.estimate_id == estimate_id)
        .first()
    )
    if line is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Estimate cost line not found",
        )
    cost_type = db.get(CostType, line.cost_type_id)
    if cost_type is None or cost_type.kind == CostTypeKind.LABOR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Milestone templates are only available for a non-labor cost line",
        )

    target_parent_uid: int | None = None
    if line.task_id is not None:
        parent_task = (
            db.query(MsTask)
            .filter(MsTask.id == line.task_id, MsTask.project_id == project_id)
            .first()
        )
        if parent_task is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cost line task does not belong to project",
            )
        target_parent_uid = parent_task.uid

    # Appended at the end of the resolved parent's (or the root level's) existing
    # children, mirroring create_estimate_task's own append-only placement --
    # never inserted at the front, which would silently reorder tasks priced
    # before this one.
    last_sibling = (
        db.query(WfPlanningTaskSnapshot)
        .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
        .filter(WfPlanningTaskSnapshot.parent_uid == target_parent_uid)
        .order_by(WfPlanningTaskSnapshot.position.desc())
        .first()
    )
    insert_after_uid = last_sibling.uid if last_sibling is not None else None
    names = _milestone_template_names(payload)
    lag_tenth_minute = payload.lag_minutes * 10

    try:
        rows: list[EstimateTaskRow] = []
        previous_uid: int | None = None
        for name in names:
            task, row = _create_estimate_planning_task(
                db,
                project_id,
                estimate_id,
                planning,
                name=name,
                is_milestone=True,
                target_parent_uid=target_parent_uid,
                insert_after_uid=insert_after_uid,
            )
            rows.append(row)
            insert_after_uid = task.uid
            if previous_uid is not None:
                replace_task_predecessor_links(
                    db,
                    planning,
                    task.uid,
                    [
                        TaskLinkWrite(
                            predecessor_uid=previous_uid,
                            link_type=1,
                            lag_tenth_minute=lag_tenth_minute,
                            lag_format=7,
                        )
                    ],
                )
            previous_uid = task.uid
        planning.revision += 1
        db.add(planning)
        db.flush()
        # Capture the response while the row locks are still held so a concurrent
        # writer cannot make us return a later transaction's state. Always a draft
        # estimate here (get_draft_estimate_or_409 above), so every row is live --
        # `resolved` always has an entry for each of them, so the task_uid fallback
        # map is never actually consulted here.
        # Finding Haute (round-5 review): resolve against every task row of the
        # estimate, not just the newly created `rows` -- resolve_live_task_display
        # renumbers `position` 1..N depth-first across only the rows it is given
        # (see its own docstring), so passing only this batch's milestones here
        # always reported positions 1..N among themselves instead of their true
        # place in the full devis.
        all_task_rows = (
            db.query(EstimateTaskRow).filter(EstimateTaskRow.estimate_id == estimate_id).all()
        )
        resolved = resolve_live_task_display(db, project, all_task_rows)
        result = EstimateTaskRowListRead(
            items=[to_estimate_task_row_read(row, resolved.get(row.id), {}) for row in rows],
            total=len(rows),
            limit=None,
            offset=0,
        )
        db.commit()
    except PlanningTreeMoveNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PlanningTreeInvariantError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PlanningTreeMoveError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except PlanningLinkNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PlanningLinkInvariantError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PlanningLinkError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Planning hierarchy conflicts with existing planning data",
        ) from exc
    return result


router.add_api_route(
    "/{project_id}/estimates/{estimate_id}/cost-lines/{line_id}/milestones",
    create_estimate_cost_line_milestones,
    methods=["POST"],
    response_model=EstimateTaskRowListRead,
    status_code=status.HTTP_201_CREATED,
    route_class_override=_PlanningTaskBodyValidationRoute,
)
