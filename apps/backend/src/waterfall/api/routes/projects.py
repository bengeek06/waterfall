import xml.etree.ElementTree as ET
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from fastapi.routing import APIRoute
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user
from waterfall.db.session import get_db
from waterfall.models.ms_core import MsProject, MsTask, MsTaskLink
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.models.resources import (
    Calendar,
    CalendarWeekday,
    CostCategory,
    CostType,
    Estimate,
    EstimateCostLine,
    EstimateLine,
    EstimateTaskRow,
    ResourceRole,
    TaskRoleAssignment,
)
from waterfall.models.user import User
from waterfall.models.wf_core import WfChargeLine, WfExcelImport, WfImportBatch, WfTaskEnrichment
from waterfall.schemas.projects import (
    EstimateAggregatesRead,
    EstimateCostLineCreate,
    EstimateCostLineRead,
    EstimateCostLineUpdate,
    EstimateTaskRowRead,
    FastAPIErrorResponse,
    PlanningCreate,
    PlanningDetailRead,
    PlanningLinkRead,
    PlanningRead,
    PlanningStructureCreate,
    PlanningStructureDraftRead,
    PlanningStructureRead,
    PlanningTaskMove,
    PlanningTaskScheduleUpdate,
    PlanningTaskTreeRead,
    PlanningTreeRead,
    ProjectCreate,
    ProjectEstimateCreate,
    ProjectEstimateRead,
    ProjectRead,
    ProjectStatus,
    ProjectStatusUpdate,
    ProjectUpdate,
    StructureKind,
    SupplyStatus,
    TaskCreate,
    TaskDescriptionUpdate,
    TaskLinkRead,
    TaskRead,
    TaskRoleAssignmentCreate,
    TaskRoleAssignmentRead,
    TaskRoleAssignmentUpdate,
)
from waterfall.schemas.resources import CostTypeKind
from waterfall.services import (
    PlanningTaskScheduleError,
    PlanningTreeInvariantError,
    PlanningTreeMoveError,
    PlanningTreeMoveNotFoundError,
    build_estimate_workbook,
    calculate_estimate_aggregates,
    calculate_estimate_lines,
    generate_planning_snapshot,
    generate_planning_structure,
    load_planning_structure_draft,
    move_planning_tasks,
    resolve_default_calendar_id,
    resolve_task_calendar_ids,
    save_planning_structure_draft,
    update_planning_task_schedule,
)
from waterfall.services.msproject_xml import (
    MsProjectValidationError,
    format_duration,
    validate_canonical_export_xml,
)
from waterfall.services.project_lifecycle import (
    ensure_project_mutable,
    validate_project_status_transition,
)
from waterfall.services.task_references import is_task_referenced

router = APIRouter(prefix="/projects", tags=["projects"])
MSP_NS = "http://schemas.microsoft.com/project/2007"


class _PlanningTaskBodyValidationRoute(APIRoute):
    """Route class that converts a request-body Pydantic validation error (422) into a 400.

    Shared by the planning task mutation endpoints (move, and the E3-03
    manual/automatic schedule update) so a malformed request body is reported
    the same way as a business-rule violation on the same resource, instead
    of FastAPI's default 422.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_route_handler = super().get_route_handler()

        async def body_validation_route_handler(request: Request) -> Response:
            try:
                return await original_route_handler(request)
            except RequestValidationError as exc:
                if any(error["loc"][0] == "body" for error in exc.errors()):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=exc.errors(),
                    ) from exc
                raise

        return body_validation_route_handler


def _bool_to_msp_flag(value: bool) -> str:
    return "1" if value else "0"


def _dt_to_msp_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    return value.isoformat(timespec="seconds")


def _get_project_or_404(db: Session, project_id: int, owner_id: int) -> MsProject:
    project = (
        db.query(MsProject)
        .filter(MsProject.id == project_id)
        .filter(MsProject.owner_id == owner_id)
        .first()
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _to_project_read(project: MsProject) -> ProjectRead:
    return ProjectRead(
        id=project.id,
        name=project.name,
        status=cast(ProjectStatus, project.status),
        code=project.code,
        short_description=project.short_description,
        source_version=project.source_version,
        save_version_out=project.save_version_out,
        schedule_from_start=project.schedule_from_start,
        start_date=project.start_date,
        finish_date=project.finish_date,
        currency_code=project.currency_code,
        planning_reference_id=project.planning_reference_id,
        displayed_planning_id=project.displayed_planning_id,
        reference_estimate_id=project.reference_estimate_id,
    )


def _get_planning_or_404(db: Session, project_id: int, planning_id: int) -> WfPlanning:
    planning = (
        db.query(WfPlanning)
        .filter(WfPlanning.id == planning_id, WfPlanning.project_id == project_id)
        .first()
    )
    if planning is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning not found")
    return planning


def get_mutable_draft_planning_with_locks(
    db: Session,
    project_id: int,
    planning_id: int,
    owner_id: int,
) -> tuple[MsProject, WfPlanning]:
    project = (
        db.query(MsProject)
        .filter(MsProject.id == project_id, MsProject.owner_id == owner_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    planning = (
        db.query(WfPlanning)
        .filter(WfPlanning.id == planning_id, WfPlanning.project_id == project_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if planning is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning not found")

    ensure_project_mutable(project)
    if planning.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Planning is not a draft")
    return project, planning


def get_mutable_project_lock(
    db: Session,
    project_id: int,
    owner_id: int,
) -> MsProject:
    project = (
        db.query(MsProject)
        .filter(MsProject.id == project_id, MsProject.owner_id == owner_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    ensure_project_mutable(project)
    return project


def get_mutable_project_with_latest_draft_lock(
    db: Session,
    project_id: int,
    owner_id: int,
    *,
    create: bool = False,
    note: str | None = None,
) -> tuple[MsProject, WfPlanning | None]:
    project = get_mutable_project_lock(db, project_id, owner_id)
    planning = _get_latest_draft_planning(db, project_id, for_update=True)
    if planning is None and create:
        planning = _create_draft_planning(db, project_id=project_id, note=note)
    return project, planning


def get_mutable_project_with_displayed_planning_lock(
    db: Session,
    project_id: int,
    owner_id: int,
) -> tuple[MsProject, WfPlanning | None]:
    project = get_mutable_project_lock(db, project_id, owner_id)
    if project.displayed_planning_id is None:
        return project, None

    planning = (
        db.query(WfPlanning)
        .filter(
            WfPlanning.id == project.displayed_planning_id,
            WfPlanning.project_id == project_id,
        )
        .populate_existing()
        .with_for_update()
        .first()
    )
    if planning is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Displayed planning not found",
        )

    if planning.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Displayed planning is immutable because it is not a draft",
        )
    return project, planning


def get_mutable_displayed_draft_planning_with_locks(
    db: Session,
    project_id: int,
    owner_id: int,
) -> tuple[MsProject, WfPlanning]:
    project, planning = get_mutable_project_with_displayed_planning_lock(db, project_id, owner_id)
    if planning is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Displayed planning not found",
        )
    return project, planning


def _get_latest_draft_planning(
    db: Session, project_id: int, *, for_update: bool = False
) -> WfPlanning | None:
    query = (
        db.query(WfPlanning)
        .filter(WfPlanning.project_id == project_id, WfPlanning.status == "draft")
        .populate_existing()
        .order_by(WfPlanning.version_number.desc())
    )
    if for_update:
        query = query.with_for_update()
    return query.first()


def _create_draft_planning(
    db: Session,
    *,
    project_id: int,
    note: str | None,
) -> WfPlanning:

    version_number = (
        db.query(func.max(WfPlanning.version_number))
        .filter(WfPlanning.project_id == project_id)
        .scalar()
        or 0
    )
    planning = WfPlanning(
        project_id=project_id,
        version_number=version_number + 1,
        status="draft",
        note=note,
        created_at=datetime.now(UTC),
    )
    db.add(planning)
    db.flush()
    return planning


def _to_snapshot_task_read(
    task: WfPlanningTaskSnapshot,
    links: list[WfPlanningLinkSnapshot],
    project_id: int,
) -> TaskRead:
    return TaskRead(
        id=task.id,
        project_id=project_id,
        uid=task.uid,
        id_display=task.id_display,
        structure_key=task.structure_key,
        structure_kind=cast(StructureKind | None, task.structure_kind),
        parent_uid=task.parent_uid,
        position=task.position,
        name=task.name,
        outline_number=task.outline_number,
        outline_level=task.outline_level,
        start_at=task.start_at,
        finish_at=task.finish_at,
        duration_minutes=task.duration_minutes,
        percent_complete=task.percent_complete,
        is_summary=task.is_summary,
        is_milestone=task.is_milestone,
        is_manual=task.is_manual,
        description=task.notes,
        predecessor_links=[
            TaskLinkRead(
                predecessor_uid=link.predecessor_uid,
                link_type=link.link_type,
                lag_tenth_minute=link.lag_tenth_minute,
                lag_format=link.lag_format,
            )
            for link in links
        ],
    )


def _to_planning_read(planning: WfPlanning) -> PlanningRead:
    return PlanningRead(
        id=planning.id,
        project_id=planning.project_id,
        version_number=planning.version_number,
        status=cast(Any, planning.status),
        note=planning.note,
        created_at=planning.created_at,
        validated_at=planning.validated_at,
    )


def _order_snapshots_depth_first(
    snapshots: list[WfPlanningTaskSnapshot],
) -> list[WfPlanningTaskSnapshot]:
    """Return snapshots depth-first: each parent immediately followed by its children.

    ``position`` is local to a sibling group, so a global sort mixes branches. Roots
    (``parent_uid`` NULL or referencing an absent parent) and each sibling group are
    sorted by ``position`` (NULLs last) with ``id`` as a stable tie-breaker.
    """
    known_uids = {task.uid for task in snapshots}
    children_by_parent: dict[int | None, list[WfPlanningTaskSnapshot]] = {}
    for task in snapshots:
        parent = task.parent_uid if task.parent_uid in known_uids else None
        children_by_parent.setdefault(parent, []).append(task)

    def sort_key(task: WfPlanningTaskSnapshot) -> tuple[int, int, int]:
        return (0 if task.position is not None else 1, task.position or 0, task.id)

    for group in children_by_parent.values():
        group.sort(key=sort_key)

    ordered: list[WfPlanningTaskSnapshot] = []
    visited: set[int] = set()

    def traverse(start: WfPlanningTaskSnapshot) -> None:
        stack = [start]
        while stack:
            node = stack.pop()
            if node.uid in visited:
                continue
            visited.add(node.uid)
            ordered.append(node)
            stack.extend(reversed(children_by_parent.get(node.uid, [])))

    for root in children_by_parent.get(None, []):
        traverse(root)
    # Guard against orphan cycles that never surface as roots.
    for task in sorted(snapshots, key=sort_key):
        if task.uid not in visited:
            traverse(task)

    return ordered


def _planning_detail(
    db: Session,
    planning: WfPlanning,
    offset: int = 0,
    limit: int | None = None,
) -> PlanningDetailRead:
    ordered = _order_snapshots_depth_first(
        db.query(WfPlanningTaskSnapshot)
        .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
        .all()
    )
    snapshots = ordered[offset : offset + limit] if limit is not None else ordered
    task_uids = [task.uid for task in snapshots]
    links = (
        db.query(WfPlanningLinkSnapshot)
        .filter(WfPlanningLinkSnapshot.planning_id == planning.id)
        .filter(WfPlanningLinkSnapshot.task_uid.in_(task_uids))
        .order_by(WfPlanningLinkSnapshot.id)
        .all()
        if task_uids
        else []
    )
    links_by_uid: dict[int, list[WfPlanningLinkSnapshot]] = {}
    for link in links:
        links_by_uid.setdefault(link.task_uid, []).append(link)
    return PlanningDetailRead(
        **_to_planning_read(planning).model_dump(),
        tasks=[
            _to_snapshot_task_read(task, links_by_uid.get(task.uid, []), planning.project_id)
            for task in snapshots
        ],
        links=[
            PlanningLinkRead(
                task_uid=link.task_uid,
                predecessor_uid=link.predecessor_uid,
                link_type=link.link_type,
                lag_tenth_minute=link.lag_tenth_minute,
                lag_format=link.lag_format,
            )
            for link in links
        ],
    )


def _get_estimate_or_404(db: Session, project_id: int, estimate_id: int) -> Estimate:
    estimate = (
        db.query(Estimate)
        .filter(Estimate.id == estimate_id)
        .filter(Estimate.project_id == project_id)
        .first()
    )
    if estimate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Estimate not found")
    return estimate


def _to_project_estimate_read(estimate: Estimate) -> ProjectEstimateRead:
    return ProjectEstimateRead(
        id=estimate.id,
        project_id=estimate.project_id,
        planning_id=estimate.planning_id,
        reference_estimate_id=estimate.reference_estimate_id,
        version_number=estimate.version_number,
        kind=estimate.kind,
        status=estimate.status,
        currency_code=estimate.currency_code,
        created_at=estimate.created_at,
        validated_at=estimate.validated_at,
        note=estimate.note,
    )


def _to_estimate_task_row_read(row: EstimateTaskRow) -> EstimateTaskRowRead:
    return EstimateTaskRowRead(
        id=row.id,
        estimate_id=row.estimate_id,
        task_id=row.task_id,
        parent_task_id=row.parent_task_id,
        position=row.position,
        task_name=row.task_name,
        outline_number=row.outline_number,
        outline_level=row.outline_level,
        is_milestone=row.is_milestone,
    )


def _to_estimate_cost_line_read(line: EstimateCostLine) -> EstimateCostLineRead:
    return EstimateCostLineRead(
        id=line.id,
        estimate_id=line.estimate_id,
        task_id=line.task_id,
        cost_type_id=line.cost_type_id,
        cost_category_id=line.cost_category_id,
        cost_type_code=line.cost_type_code,
        accounting_code=line.accounting_code,
        category_code=line.category_code,
        label=line.label,
        quantity=line.quantity,
        unit_cost=line.unit_cost,
        purchase_cost=line.purchase_cost,
        supply_status=cast(SupplyStatus | None, line.supply_status),
    )


def _get_draft_estimate_or_409(db: Session, project_id: int, estimate_id: int) -> Estimate:
    project = db.get(MsProject, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    ensure_project_mutable(project)
    estimate = _get_estimate_or_404(db, project_id, estimate_id)
    if estimate.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Estimate is not a draft")
    return estimate


def _get_non_labor_category_or_400(
    db: Session,
    cost_category_id: int,
) -> tuple[CostCategory, CostType]:
    row = (
        db.query(CostCategory, CostType)
        .join(CostType, CostCategory.cost_type_id == CostType.id)
        .filter(CostCategory.id == cost_category_id)
        .filter(CostCategory.is_active.is_(True))
        .filter(CostType.is_active.is_(True))
        .filter(CostType.kind != CostTypeKind.LABOR)
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cost category must belong to an active non-labor cost type",
        )
    category, cost_type = row
    return category, cost_type


def _get_task_or_404(db: Session, project_id: int, task_uid: int) -> MsTask:
    task = (
        db.query(MsTask)
        .filter(MsTask.project_id == project_id)
        .filter(MsTask.uid == task_uid)
        .first()
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def _to_task_read(
    task: MsTask,
    description: str | None,
    predecessor_links: list[MsTaskLink] | None = None,
) -> TaskRead:
    return TaskRead(
        id=task.id,
        project_id=task.project_id,
        uid=task.uid,
        id_display=task.id_display,
        structure_key=task.structure_key,
        structure_kind=cast(StructureKind | None, task.structure_kind),
        parent_uid=task.parent_uid,
        position=task.position,
        name=task.name,
        outline_number=task.outline_number,
        outline_level=task.outline_level,
        start_at=task.start_at,
        finish_at=task.finish_at,
        duration_minutes=task.duration_minutes,
        percent_complete=task.percent_complete,
        is_summary=task.is_summary,
        is_milestone=task.is_milestone,
        is_manual=task.is_manual,
        description=description,
        predecessor_links=[
            TaskLinkRead(
                predecessor_uid=link.predecessor_uid,
                link_type=link.link_type,
                lag_tenth_minute=link.lag_tenth_minute,
                lag_format=link.lag_format,
            )
            for link in predecessor_links or []
        ],
    )


def _to_task_role_assignment_read(
    assignment: TaskRoleAssignment,
    role: ResourceRole,
    category: CostCategory,
) -> TaskRoleAssignmentRead:
    return TaskRoleAssignmentRead(
        id=assignment.id,
        task_id=assignment.task_id,
        role_id=role.id,
        role_code=role.code,
        role_name=role.name,
        cost_category_id=category.id,
        accounting_code=category.accounting_code,
        quantity=assignment.quantity,
        hours=assignment.hours,
        comment=assignment.comment,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


def _to_task_reads(db: Session, project_id: int, tasks: list[MsTask]) -> list[TaskRead]:
    task_uids = [task.uid for task in tasks]
    descriptions_by_uid: dict[int, str | None] = {}
    links_by_task_uid: dict[int, list[MsTaskLink]] = {}
    if task_uids:
        enrichments = (
            db.query(WfTaskEnrichment)
            .filter(WfTaskEnrichment.project_id == project_id)
            .filter(WfTaskEnrichment.task_uid.in_(task_uids))
            .all()
        )
        descriptions_by_uid = {item.task_uid: item.description for item in enrichments}
        links = (
            db.query(MsTaskLink)
            .filter(MsTaskLink.project_id == project_id)
            .filter(MsTaskLink.task_uid.in_(task_uids))
            .order_by(MsTaskLink.id.asc())
            .all()
        )
        for link in links:
            links_by_task_uid.setdefault(link.task_uid, []).append(link)

    return [
        _to_task_read(
            task,
            descriptions_by_uid.get(task.uid),
            links_by_task_uid.get(task.uid),
        )
        for task in tasks
    ]


@router.get("", response_model=list[ProjectRead])
def list_projects(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[ProjectRead]:
    query = db.query(MsProject).filter(MsProject.owner_id == current_user.id)
    if not include_archived:
        query = query.filter(MsProject.status.notin_(["perdu", "termine", "abandonne"]))
    projects = query.order_by(MsProject.id.asc()).offset(offset).limit(limit).all()
    return [_to_project_read(project) for project in projects]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    now = datetime.now(UTC)
    project = MsProject(
        owner_id=current_user.id,
        external_uid=None,
        code=payload.code.strip() if payload.code else None,
        short_description=payload.short_description.strip() if payload.short_description else None,
        source_version=2016,
        save_version_out=16,
        name=payload.name.strip(),
        schedule_from_start=True,
        start_date=now,
        finish_date=now,
        calendar_uid=None,
        minutes_per_day=480,
        minutes_per_week=2400,
        days_per_month=20,
        currency_code=payload.currency_code.upper() if payload.currency_code else None,
        status=cast(ProjectStatus, "cree"),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return _to_project_read(project)


@router.get("/{project_id}/plannings", response_model=list[PlanningRead])
def list_plannings(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[PlanningRead]:
    _get_project_or_404(db, project_id, current_user.id)
    plannings = (
        db.query(WfPlanning)
        .filter(WfPlanning.project_id == project_id)
        .order_by(WfPlanning.version_number.asc())
        .all()
    )
    return [_to_planning_read(planning) for planning in plannings]


@router.post(
    "/{project_id}/plannings",
    response_model=PlanningDetailRead,
    status_code=status.HTTP_201_CREATED,
)
def create_planning(
    project_id: int,
    payload: PlanningCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningDetailRead:
    project = get_mutable_project_lock(db, project_id, current_user.id)
    source_id = payload.source_planning_id or project.displayed_planning_id
    source: WfPlanning | None = None
    if source_id is not None:
        source = (
            db.query(WfPlanning)
            .filter(WfPlanning.id == source_id, WfPlanning.project_id == project_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        if source is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning not found")
    version_number = (
        db.query(func.max(WfPlanning.version_number))
        .filter(WfPlanning.project_id == project_id)
        .scalar()
        or 0
    ) + 1
    planning = WfPlanning(
        project_id=project_id,
        version_number=version_number,
        status="draft",
        note=payload.note,
        created_at=datetime.now(UTC),
    )
    db.add(planning)
    db.flush()

    if source is not None:
        source_tasks = (
            db.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == source.id)
            .all()
        )
        source_links = (
            db.query(WfPlanningLinkSnapshot)
            .filter(WfPlanningLinkSnapshot.planning_id == source.id)
            .all()
        )
        db.add_all(
            [
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=task.uid,
                    id_display=task.id_display,
                    structure_key=task.structure_key,
                    structure_kind=task.structure_kind,
                    parent_uid=task.parent_uid,
                    position=task.position,
                    name=task.name,
                    notes=task.notes,
                    task_type=task.task_type,
                    outline_number=task.outline_number,
                    outline_level=task.outline_level,
                    wbs=task.wbs,
                    start_at=task.start_at,
                    finish_at=task.finish_at,
                    duration_minutes=task.duration_minutes,
                    duration_format=task.duration_format,
                    work_minutes=task.work_minutes,
                    percent_complete=task.percent_complete,
                    is_summary=task.is_summary,
                    is_milestone=task.is_milestone,
                    is_manual=task.is_manual,
                    calendar_uid=task.calendar_uid,
                )
                for task in source_tasks
            ]
        )
        db.add_all(
            [
                WfPlanningLinkSnapshot(
                    planning_id=planning.id,
                    task_uid=link.task_uid,
                    predecessor_uid=link.predecessor_uid,
                    link_type=link.link_type,
                    lag_tenth_minute=link.lag_tenth_minute,
                    lag_format=link.lag_format,
                )
                for link in source_links
            ]
        )
    else:
        tasks = db.query(MsTask).filter(MsTask.project_id == project_id).all()
        db.add_all(
            [
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=task.uid,
                    id_display=task.id_display,
                    structure_key=task.structure_key,
                    structure_kind=task.structure_kind,
                    parent_uid=task.parent_uid,
                    position=task.position,
                    name=task.name,
                    task_type=task.task_type,
                    outline_number=task.outline_number,
                    outline_level=task.outline_level,
                    wbs=task.wbs,
                    start_at=task.start_at,
                    finish_at=task.finish_at,
                    duration_minutes=task.duration_minutes,
                    duration_format=task.duration_format,
                    work_minutes=task.work_minutes,
                    percent_complete=task.percent_complete,
                    is_summary=task.is_summary,
                    is_milestone=task.is_milestone,
                    is_manual=task.is_manual,
                    calendar_uid=task.calendar_uid,
                )
                for task in tasks
            ]
        )
        links = db.query(MsTaskLink).filter(MsTaskLink.project_id == project_id).all()
        db.add_all(
            [
                WfPlanningLinkSnapshot(
                    planning_id=planning.id,
                    task_uid=link.task_uid,
                    predecessor_uid=link.predecessor_uid,
                    link_type=link.link_type,
                    lag_tenth_minute=link.lag_tenth_minute,
                    lag_format=link.lag_format,
                )
                for link in links
            ]
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Planning version conflicts with existing project data",
        ) from exc
    db.refresh(planning)
    return _planning_detail(db, planning)


@router.get("/{project_id}/plannings/{planning_id}", response_model=PlanningDetailRead)
def get_planning(
    project_id: int,
    planning_id: int,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningDetailRead:
    _get_project_or_404(db, project_id, current_user.id)
    return _planning_detail(
        db, _get_planning_or_404(db, project_id, planning_id), offset=offset, limit=limit
    )


def move_planning_tasks_route(
    project_id: int,
    planning_id: int,
    payload: PlanningTaskMove,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningDetailRead:
    _, planning = get_mutable_draft_planning_with_locks(
        db, project_id, planning_id, current_user.id
    )
    try:
        move_planning_tasks(db, planning, payload)
        # Capture the response while the row locks are still held so a concurrent
        # writer cannot make us return a later transaction's state.
        detail = _planning_detail(db, planning)
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
    return detail


router.add_api_route(
    "/{project_id}/plannings/{planning_id}/tasks/move",
    move_planning_tasks_route,
    methods=["POST"],
    response_model=PlanningDetailRead,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": FastAPIErrorResponse,
            "description": "Requete de deplacement invalide",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": FastAPIErrorResponse,
            "description": "Projet, planning ou tache introuvable pendant le deplacement",
        },
        status.HTTP_409_CONFLICT: {
            "model": FastAPIErrorResponse,
            "description": "Le deplacement entre en conflit avec le planning",
        },
    },
    route_class_override=_PlanningTaskBodyValidationRoute,
)


def update_planning_task_schedule_route(
    project_id: int,
    planning_id: int,
    task_uid: int,
    payload: PlanningTaskScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningDetailRead:
    _, planning = get_mutable_draft_planning_with_locks(
        db, project_id, planning_id, current_user.id
    )
    try:
        update_planning_task_schedule(db, planning, task_uid, payload)
        # Capture the response while the row locks are still held so a concurrent
        # writer cannot make us return a later transaction's state.
        detail = _planning_detail(db, planning)
        db.commit()
    except PlanningTreeMoveNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PlanningTaskScheduleError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task schedule conflicts with existing planning data",
        ) from exc
    return detail


router.add_api_route(
    "/{project_id}/plannings/{planning_id}/tasks/{task_uid}",
    update_planning_task_schedule_route,
    methods=["PATCH"],
    response_model=PlanningDetailRead,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": FastAPIErrorResponse,
            "description": "Combinaison mode/dates/duree invalide",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": FastAPIErrorResponse,
            "description": "Projet, planning ou tache introuvable",
        },
        status.HTTP_409_CONFLICT: {
            "model": FastAPIErrorResponse,
            "description": "La mise a jour du planning entre en conflit avec les donnees",
        },
    },
    route_class_override=_PlanningTaskBodyValidationRoute,
)


@router.post("/{project_id}/plannings/{planning_id}/validate", response_model=PlanningRead)
def validate_planning(
    project_id: int,
    planning_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningRead:
    _, planning = get_mutable_draft_planning_with_locks(
        db, project_id, planning_id, current_user.id
    )
    planning.status = "validated"
    planning.validated_at = datetime.now(UTC)
    db.commit()
    db.refresh(planning)
    return _to_planning_read(planning)


@router.post("/{project_id}/plannings/{planning_id}/reference", response_model=ProjectRead)
def set_planning_reference(
    project_id: int,
    planning_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    project = get_mutable_project_lock(db, project_id, current_user.id)
    planning = (
        db.query(WfPlanning)
        .filter(WfPlanning.id == planning_id, WfPlanning.project_id == project_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if planning is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning not found")
    if planning.status != "validated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Planning must be validated",
        )
    previous = project.planning_reference_id
    if previous is not None and previous != planning.id:
        old = (
            db.query(WfPlanning)
            .filter(WfPlanning.id == previous, WfPlanning.project_id == project_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        if old is not None:
            old.status = "superseded"
    project.planning_reference_id = planning.id
    if project.displayed_planning_id is None:
        project.displayed_planning_id = planning.id
    db.commit()
    db.refresh(project)
    return _to_project_read(project)


@router.post("/{project_id}/plannings/{planning_id}/display", response_model=ProjectRead)
def set_displayed_planning(
    project_id: int,
    planning_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    project = get_mutable_project_lock(db, project_id, current_user.id)
    planning = (
        db.query(WfPlanning)
        .filter(WfPlanning.id == planning_id, WfPlanning.project_id == project_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if planning is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning not found")
    project.displayed_planning_id = planning_id
    db.commit()
    db.refresh(project)
    return _to_project_read(project)


@router.post("/{project_id}/planning-structure/reopen", response_model=ProjectRead)
def reopen_planning_structure(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    project, existing_draft = get_mutable_project_with_latest_draft_lock(
        db, project_id, current_user.id
    )
    if existing_draft is not None:
        project.displayed_planning_id = existing_draft.id
        if project.status == "cree":
            validate_project_status_transition(db, project, "initialise")
            project.status = "initialise"
        db.commit()
        db.refresh(project)
        return _to_project_read(project)
    if project.planning_reference_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A validated planning is required to reopen the structure",
        )
    source = (
        db.query(WfPlanning)
        .filter(
            WfPlanning.id == project.planning_reference_id,
            WfPlanning.project_id == project_id,
        )
        .populate_existing()
        .with_for_update()
        .first()
    )
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning not found")
    if source.status != "validated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Planning reference must be validated",
        )
    version_number = (
        db.query(func.max(WfPlanning.version_number))
        .filter(WfPlanning.project_id == project_id)
        .scalar()
        or 0
    )
    planning = WfPlanning(
        project_id=project_id,
        version_number=version_number + 1,
        status="draft",
        note="Structure reopened",
        created_at=datetime.now(UTC),
    )
    db.add(planning)
    db.flush()
    source_tasks = (
        db.query(WfPlanningTaskSnapshot)
        .filter(WfPlanningTaskSnapshot.planning_id == source.id)
        .all()
    )
    cloned_tasks = [
        WfPlanningTaskSnapshot(
            planning_id=planning.id,
            uid=task.uid,
            id_display=task.id_display,
            structure_key=task.structure_key,
            structure_kind=task.structure_kind,
            parent_uid=None,
            position=task.position,
            name=task.name,
            task_type=task.task_type,
            outline_number=task.outline_number,
            outline_level=task.outline_level,
            wbs=task.wbs,
            start_at=task.start_at,
            finish_at=task.finish_at,
            duration_minutes=task.duration_minutes,
            duration_format=task.duration_format,
            work_minutes=task.work_minutes,
            percent_complete=task.percent_complete,
            is_summary=task.is_summary,
            is_milestone=task.is_milestone,
            is_manual=task.is_manual,
            notes=task.notes,
            calendar_uid=task.calendar_uid,
        )
        for task in source_tasks
    ]
    db.add_all(cloned_tasks)
    db.flush()
    parent_by_uid = {task.uid: task.parent_uid for task in source_tasks}
    for task in cloned_tasks:
        task.parent_uid = parent_by_uid[task.uid]
    db.flush()
    source_links = (
        db.query(WfPlanningLinkSnapshot)
        .filter(WfPlanningLinkSnapshot.planning_id == source.id)
        .all()
    )
    db.add_all(
        WfPlanningLinkSnapshot(
            planning_id=planning.id,
            task_uid=link.task_uid,
            predecessor_uid=link.predecessor_uid,
            link_type=link.link_type,
            lag_tenth_minute=link.lag_tenth_minute,
            lag_format=link.lag_format,
        )
        for link in source_links
    )
    project.displayed_planning_id = planning.id
    if project.status == "cree":
        validate_project_status_transition(db, project, "initialise")
        project.status = "initialise"
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Planning reopen conflict"
        ) from exc
    db.refresh(project)
    return _to_project_read(project)


@router.get("/{project_id}/estimates", response_model=list[ProjectEstimateRead])
def list_project_estimates(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[ProjectEstimateRead]:
    _get_project_or_404(db, project_id, current_user.id)
    estimates = (
        db.query(Estimate)
        .filter(Estimate.project_id == project_id)
        .order_by(Estimate.version_number)
        .all()
    )
    return [_to_project_estimate_read(estimate) for estimate in estimates]


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
    project = _get_project_or_404(db, project_id, current_user.id)
    ensure_project_mutable(project)
    if payload.kind == "forecast_remaining" and payload.reference_estimate_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Forecast remaining estimate requires a reference estimate",
        )
    if payload.reference_estimate_id is not None:
        _get_estimate_or_404(db, project_id, payload.reference_estimate_id)

    current_version = (
        db.query(func.max(Estimate.version_number))
        .filter(Estimate.project_id == project_id)
        .scalar()
    )
    next_version = (current_version or 0) + 1
    estimate = Estimate(
        project_id=project_id,
        planning_id=project.displayed_planning_id,
        reference_estimate_id=payload.reference_estimate_id,
        version_number=next_version,
        kind=payload.kind,
        status="draft",
        currency_code=payload.currency_code.upper(),
        note=payload.note,
    )
    db.add(estimate)
    db.flush()

    source_planning = (
        _get_planning_or_404(db, project_id, project.displayed_planning_id)
        if project.displayed_planning_id is not None
        else None
    )
    snapshots = (
        _order_snapshots_depth_first(
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
        rows.append(
            EstimateTaskRow(
                estimate_id=estimate.id,
                task_id=(
                    task_by_uid[task.uid].id
                    if source_planning is not None and task.uid in task_by_uid
                    else None
                    if source_planning is not None
                    else task.id
                ),
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
    return _to_project_estimate_read(estimate)


@router.get("/{project_id}/estimates/{estimate_id}", response_model=ProjectEstimateRead)
def get_project_estimate(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectEstimateRead:
    _get_project_or_404(db, project_id, current_user.id)
    return _to_project_estimate_read(_get_estimate_or_404(db, project_id, estimate_id))


@router.get(
    "/{project_id}/estimates/{estimate_id}/task-rows",
    response_model=list[EstimateTaskRowRead],
)
def list_estimate_task_rows(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[EstimateTaskRowRead]:
    _get_project_or_404(db, project_id, current_user.id)
    _get_estimate_or_404(db, project_id, estimate_id)
    rows = (
        db.query(EstimateTaskRow)
        .filter(EstimateTaskRow.estimate_id == estimate_id)
        .order_by(EstimateTaskRow.position)
        .all()
    )
    return [_to_estimate_task_row_read(row) for row in rows]


@router.post("/{project_id}/estimates/{estimate_id}/validate", response_model=ProjectEstimateRead)
def validate_project_estimate(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectEstimateRead:
    project = _get_project_or_404(db, project_id, current_user.id)
    ensure_project_mutable(project)
    estimate = _get_estimate_or_404(db, project_id, estimate_id)
    if estimate.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Estimate is not a draft")

    # Calculate and snapshot all estimate lines (labor and non-labor)
    try:
        estimate_lines = calculate_estimate_lines(db, estimate_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.add_all(estimate_lines)
    db.flush()

    # Freeze estimate
    estimate.status = "validated"
    estimate.validated_at = datetime.now(UTC)
    db.add(estimate)
    db.commit()
    db.refresh(estimate)
    return _to_project_estimate_read(estimate)


@router.post("/{project_id}/estimates/{estimate_id}/reference", response_model=ProjectRead)
def set_estimate_reference(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    project = _get_project_or_404(db, project_id, current_user.id)
    ensure_project_mutable(project)
    estimate = _get_estimate_or_404(db, project_id, estimate_id)
    if estimate.status != "validated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Estimate must be validated",
        )
    project.reference_estimate_id = estimate.id
    db.commit()
    db.refresh(project)
    return _to_project_read(project)


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
    _get_project_or_404(db, project_id, current_user.id)
    _get_estimate_or_404(db, project_id, estimate_id)
    aggregates = calculate_estimate_aggregates(db, estimate_id)
    return EstimateAggregatesRead(**aggregates)


@router.get("/{project_id}/estimates/{estimate_id}/export.xlsx")
def export_estimate_excel(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    project = _get_project_or_404(db, project_id, current_user.id)
    estimate = _get_estimate_or_404(db, project_id, estimate_id)
    workbook_bytes = build_estimate_workbook(db, project, estimate)
    filename = f"devis-{project.name}-v{estimate.version_number}.xlsx".replace(" ", "-")
    return Response(
        content=workbook_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{project_id}/estimates/{estimate_id}/cost-lines",
    response_model=list[EstimateCostLineRead],
)
def list_estimate_cost_lines(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[EstimateCostLineRead]:
    _get_project_or_404(db, project_id, current_user.id)
    _get_estimate_or_404(db, project_id, estimate_id)
    lines = (
        db.query(EstimateCostLine)
        .filter(EstimateCostLine.estimate_id == estimate_id)
        .order_by(EstimateCostLine.id)
        .all()
    )
    return [_to_estimate_cost_line_read(line) for line in lines]


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
    _get_project_or_404(db, project_id, current_user.id)
    _get_draft_estimate_or_409(db, project_id, estimate_id)
    if payload.task_id is not None:
        task = db.query(MsTask).filter(MsTask.id == payload.task_id).first()
        if task is None or task.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Task does not belong to project",
            )
    category, cost_type = _get_non_labor_category_or_400(db, payload.cost_category_id)
    supply_status = "planned" if cost_type.kind == CostTypeKind.SUPPLY else None
    if payload.supply_status is not None:
        if cost_type.kind != CostTypeKind.SUPPLY:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Supply status is only valid for supplies",
            )
        supply_status = payload.supply_status

    line = EstimateCostLine(
        estimate_id=estimate_id,
        task_id=payload.task_id,
        cost_type_id=cost_type.id,
        cost_category_id=category.id,
        cost_type_code=cost_type.code,
        accounting_code=category.accounting_code,
        category_code=category.category_code,
        label=payload.label,
        quantity=payload.quantity,
        unit_cost=payload.unit_cost,
        purchase_cost=payload.quantity * payload.unit_cost,
        supply_status=supply_status,
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    return _to_estimate_cost_line_read(line)


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
    _get_project_or_404(db, project_id, current_user.id)
    _get_draft_estimate_or_409(db, project_id, estimate_id)
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

    category, cost_type = _get_non_labor_category_or_400(
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
    return _to_estimate_cost_line_read(line)


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
    _get_project_or_404(db, project_id, current_user.id)
    _get_draft_estimate_or_409(db, project_id, estimate_id)
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
    db.delete(line)
    db.commit()


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    return _to_project_read(_get_project_or_404(db, project_id, current_user.id))


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    project = _get_project_or_404(db, project_id, current_user.id)
    ensure_project_mutable(project)

    values = payload.model_dump(exclude_unset=True)
    if "name" in values:
        new_name = (values["name"] or "").strip()
        if not new_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Project name is required",
            )
        project.name = new_name
    if "code" in values:
        project.code = values["code"].strip() if values["code"] else None
    if "short_description" in values:
        project.short_description = (
            values["short_description"].strip() if values["short_description"] else None
        )
    if "status" in values and values["status"] is not None:
        new_status = values["status"]
        validate_project_status_transition(db, project, new_status)
        project.status = new_status

    db.add(project)
    db.commit()
    db.refresh(project)

    return _to_project_read(project)


@router.patch("/{project_id}/status", response_model=ProjectRead)
def update_project_status(
    project_id: int,
    payload: ProjectStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    project = _get_project_or_404(db, project_id, current_user.id)
    ensure_project_mutable(project)
    validate_project_status_transition(db, project, payload.status)
    project.status = payload.status
    db.commit()
    db.refresh(project)
    return _to_project_read(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    project = _get_project_or_404(db, project_id, current_user.id)
    ensure_project_mutable(project)
    planning_ids = [
        row[0] for row in db.query(WfPlanning.id).filter(WfPlanning.project_id == project_id).all()
    ]
    if planning_ids:
        project.planning_reference_id = None
        project.displayed_planning_id = None
        db.query(Estimate).filter(Estimate.project_id == project_id).update(
            {Estimate.planning_id: None}, synchronize_session=False
        )
        db.query(WfPlanningLinkSnapshot).filter(
            WfPlanningLinkSnapshot.planning_id.in_(planning_ids)
        ).delete(synchronize_session=False)
        db.query(WfPlanningTaskSnapshot).filter(
            WfPlanningTaskSnapshot.planning_id.in_(planning_ids)
        ).delete(synchronize_session=False)
        db.query(WfPlanning).filter(WfPlanning.id.in_(planning_ids)).delete(
            synchronize_session=False
        )

    estimate_ids = [
        row[0] for row in db.query(Estimate.id).filter(Estimate.project_id == project_id).all()
    ]
    # Drop the project's reference to any estimate before deleting estimates, otherwise
    # fk_ms_project_reference_estimate (no ON DELETE) is violated on PostgreSQL.
    project.reference_estimate_id = None
    db.flush()
    if estimate_ids:
        db.query(EstimateCostLine).filter(EstimateCostLine.estimate_id.in_(estimate_ids)).delete(
            synchronize_session=False
        )
        db.query(EstimateLine).filter(EstimateLine.estimate_id.in_(estimate_ids)).delete(
            synchronize_session=False
        )
        db.query(EstimateTaskRow).filter(EstimateTaskRow.estimate_id.in_(estimate_ids)).delete(
            synchronize_session=False
        )
        # Clear self-references before deleting, since a validated estimate may be
        # the reference_estimate_id of a later forecast/contract version.
        db.query(Estimate).filter(Estimate.id.in_(estimate_ids)).update(
            {Estimate.reference_estimate_id: None}, synchronize_session=False
        )
        db.query(Estimate).filter(Estimate.id.in_(estimate_ids)).delete(synchronize_session=False)

    db.query(TaskRoleAssignment).filter(
        TaskRoleAssignment.task_id.in_(
            db.query(MsTask.id).filter(MsTask.project_id == project_id).scalar_subquery()
        )
    ).delete(synchronize_session=False)

    db.query(WfImportBatch).filter(WfImportBatch.project_id == project_id).update(
        {WfImportBatch.project_id: None}, synchronize_session=False
    )
    db.query(WfExcelImport).filter(WfExcelImport.project_id == project_id).delete(
        synchronize_session=False
    )
    db.query(WfChargeLine).filter(WfChargeLine.project_id == project_id).delete(
        synchronize_session=False
    )
    db.query(WfTaskEnrichment).filter(WfTaskEnrichment.project_id == project_id).delete(
        synchronize_session=False
    )
    db.query(MsTaskLink).filter(MsTaskLink.project_id == project_id).delete(
        synchronize_session=False
    )
    db.query(MsTask).filter(MsTask.project_id == project_id).delete(synchronize_session=False)
    db.delete(project)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/tasks", response_model=list[TaskRead])
def list_project_tasks(
    project_id: int,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    planning_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[TaskRead]:
    project = _get_project_or_404(db, project_id, current_user.id)
    selected_id = planning_id or project.displayed_planning_id
    if selected_id is not None:
        planning = _get_planning_or_404(db, project_id, selected_id)
        return _planning_detail(db, planning, offset=offset, limit=limit).tasks

    tasks = (
        db.query(MsTask)
        .filter(MsTask.project_id == project_id)
        .order_by(MsTask.outline_number.asc().nulls_last(), MsTask.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return _to_task_reads(db, project_id, tasks)


@router.get("/{project_id}/planning-tree", response_model=PlanningTreeRead)
def get_planning_tree(
    project_id: int,
    planning_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningTreeRead:
    project = _get_project_or_404(db, project_id, current_user.id)
    selected_id = planning_id or project.displayed_planning_id
    if selected_id is not None:
        detail = _planning_detail(db, _get_planning_or_404(db, project_id, selected_id))
        tasks = detail.tasks
    else:
        stored_tasks = (
            db.query(MsTask)
            .filter(MsTask.project_id == project_id)
            .order_by(MsTask.outline_number.asc().nulls_last(), MsTask.id.asc())
            .all()
        )
        tasks = _to_task_reads(db, project_id, stored_tasks)
    tree_by_uid = {task.uid: PlanningTaskTreeRead(**task.model_dump()) for task in tasks}
    roots: list[PlanningTaskTreeRead] = []
    for task in tree_by_uid.values():
        if task.parent_uid is not None and task.parent_uid in tree_by_uid:
            tree_by_uid[task.parent_uid].children.append(task)
        else:
            roots.append(task)
    return PlanningTreeRead(tasks=roots)


@router.post(
    "/{project_id}/planning-structure",
    response_model=PlanningStructureRead,
    status_code=status.HTTP_201_CREATED,
)
def create_planning_structure(
    project_id: int,
    payload: PlanningStructureCreate | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningStructureRead:
    try:
        project, planning = get_mutable_project_with_latest_draft_lock(
            db,
            project_id,
            current_user.id,
            create=True,
            note="Generated from planning structure",
        )
        assert planning is not None
        if payload is None:
            payload = load_planning_structure_draft(planning)
            if payload is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A saved planning structure draft is required",
                )
        snapshots = generate_planning_snapshot(db, project, payload, planning)
        if project.planning_reference_id is None:
            generate_planning_structure(db, project, payload)
        # Keep the persisted draft in sync with the structure actually generated so the
        # editor reopens on the latest content instead of a stale saved draft.
        save_planning_structure_draft(planning, payload)
        project.displayed_planning_id = planning.id
        if project.status == "cree":
            project.status = "initialise"
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Planning structure conflicts with existing project data",
        ) from exc

    return PlanningStructureRead(
        tasks=[_to_snapshot_task_read(snapshot, [], project_id) for snapshot in snapshots]
    )


@router.put(
    "/{project_id}/planning-structure/draft",
    response_model=PlanningStructureDraftRead,
)
def save_planning_structure_draft_route(
    project_id: int,
    payload: PlanningStructureCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningStructureDraftRead:
    try:
        _, planning = get_mutable_project_with_latest_draft_lock(
            db,
            project_id,
            current_user.id,
            create=True,
        )
        assert planning is not None
        save_planning_structure_draft(planning, payload)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Planning structure conflicts with existing project data",
        ) from exc

    return PlanningStructureDraftRead(planning_id=planning.id, structure=payload)


@router.get(
    "/{project_id}/planning-structure/draft",
    response_model=PlanningStructureDraftRead,
)
def get_planning_structure_draft_route(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningStructureDraftRead:
    project = _get_project_or_404(db, project_id, current_user.id)
    planning = (
        db.query(WfPlanning)
        .filter(
            WfPlanning.project_id == project.id,
            WfPlanning.status == "draft",
            WfPlanning.structure_draft_json.isnot(None),
        )
        .order_by(WfPlanning.version_number.desc())
        .first()
    )
    if planning is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No planning structure draft found",
        )
    try:
        payload = load_planning_structure_draft(planning)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No planning structure draft found",
        )
    return PlanningStructureDraftRead(planning_id=planning.id, structure=payload)


@router.post("/{project_id}/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_project_task(
    project_id: int,
    payload: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TaskRead:
    """Add a planning task for devis purposes; dates stay driven by MS Project."""
    project, planning = get_mutable_project_with_displayed_planning_lock(
        db, project_id, current_user.id
    )

    if planning is not None:
        parent_snapshot: WfPlanningTaskSnapshot | None = None
        if payload.parent_task_id is not None:
            parent_snapshot = (
                db.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.id == payload.parent_task_id)
                .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
                .first()
            )
            if parent_snapshot is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Parent task does not belong to displayed planning",
                )

        max_uid = (
            db.query(func.max(WfPlanningTaskSnapshot.uid))
            .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
            .scalar()
        )
        max_id_display = (
            db.query(func.max(WfPlanningTaskSnapshot.id_display))
            .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
            .scalar()
        )
        if parent_snapshot is not None:
            outline_level = (parent_snapshot.outline_level or 0) + 1
            max_position = (
                db.query(func.max(WfPlanningTaskSnapshot.position))
                .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
                .filter(WfPlanningTaskSnapshot.parent_uid == parent_snapshot.uid)
                .scalar()
            )
            next_index = (max_position or 0) + 1
            outline_number = f"{parent_snapshot.outline_number}.{next_index}"
            position = next_index
            parent_uid = parent_snapshot.uid
        else:
            outline_level = 1
            max_position = (
                db.query(func.max(WfPlanningTaskSnapshot.position))
                .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
                .filter(WfPlanningTaskSnapshot.parent_uid.is_(None))
                .scalar()
            )
            next_index = (max_position or 0) + 1
            outline_number = str(next_index)
            position = next_index
            parent_uid = None

        snapshot = WfPlanningTaskSnapshot(
            planning_id=planning.id,
            uid=(max_uid or 0) + 1,
            id_display=(max_id_display or 0) + 1,
            parent_uid=parent_uid,
            position=position,
            name=payload.name.strip(),
            task_type=0,
            outline_number=outline_number,
            outline_level=outline_level,
            is_summary=False,
            is_milestone=payload.is_milestone,
        )
        db.add(snapshot)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Displayed planning task conflicts with existing planning data",
            ) from exc
        db.refresh(snapshot)
        return _to_snapshot_task_read(snapshot, [], project_id)

    ensure_project_mutable(project)
    parent_task: MsTask | None = None
    if payload.parent_task_id is not None:
        parent_task = (
            db.query(MsTask)
            .filter(MsTask.id == payload.parent_task_id)
            .filter(MsTask.project_id == project_id)
            .first()
        )
        if parent_task is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent task does not belong to project",
            )

    max_uid = db.query(func.max(MsTask.uid)).filter(MsTask.project_id == project_id).scalar()
    max_id_display = (
        db.query(func.max(MsTask.id_display)).filter(MsTask.project_id == project_id).scalar()
    )

    if parent_task is not None:
        outline_level = (parent_task.outline_level or 0) + 1
        sibling_prefix = f"{parent_task.outline_number}."
        sibling_count = (
            db.query(MsTask)
            .filter(MsTask.project_id == project_id)
            .filter(MsTask.outline_number.like(f"{sibling_prefix}%"))
            .filter(MsTask.outline_level == outline_level)
            .count()
        )
        outline_number = f"{parent_task.outline_number}.{sibling_count + 1}"
        position = sibling_count + 1
    else:
        outline_level = 1
        root_count = (
            db.query(MsTask)
            .filter(MsTask.project_id == project_id)
            .filter(MsTask.outline_level == 1)
            .count()
        )
        outline_number = str(root_count + 1)
        position = root_count + 1

    task = MsTask(
        project_id=project_id,
        uid=(max_uid or 0) + 1,
        id_display=(max_id_display or 0) + 1,
        parent_uid=parent_task.uid if parent_task is not None else None,
        position=position,
        name=payload.name.strip(),
        outline_number=outline_number,
        outline_level=outline_level,
        is_summary=False,
        is_milestone=payload.is_milestone,
    )
    db.add(task)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task conflicts with existing project data",
        ) from exc
    db.refresh(task)
    return _to_task_read(task, description=None)


@router.patch("/{project_id}/tasks/{task_uid}", response_model=TaskRead)
def update_task_description(
    project_id: int,
    task_uid: int,
    payload: TaskDescriptionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TaskRead:
    _project, displayed_planning = get_mutable_project_with_displayed_planning_lock(
        db, project_id, current_user.id
    )
    if displayed_planning is not None:
        snapshot = (
            db.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == displayed_planning.id)
            .filter(WfPlanningTaskSnapshot.uid == task_uid)
            .first()
        )
        if snapshot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        snapshot.notes = payload.description
        db.commit()
        return _to_snapshot_task_read(snapshot, [], project_id)

    task = (
        db.query(MsTask)
        .filter(MsTask.project_id == project_id)
        .filter(MsTask.uid == task_uid)
        .first()
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    enrichment = (
        db.query(WfTaskEnrichment)
        .filter(WfTaskEnrichment.project_id == project_id)
        .filter(WfTaskEnrichment.task_uid == task_uid)
        .first()
    )

    now = datetime.now(UTC)
    if enrichment is None:
        enrichment = WfTaskEnrichment(
            project_id=project_id,
            task_uid=task_uid,
            description=payload.description,
            created_at=now,
            updated_at=now,
        )
        db.add(enrichment)
    else:
        enrichment.description = payload.description
        enrichment.updated_at = now

    db.commit()

    return _to_task_read(task, description=payload.description)


@router.delete("/{project_id}/tasks/{task_uid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_task(
    project_id: int,
    task_uid: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    project, planning = get_mutable_project_with_displayed_planning_lock(
        db, project_id, current_user.id
    )
    if planning is not None:
        task = (
            db.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
            .filter(WfPlanningTaskSnapshot.uid == task_uid)
            .first()
        )
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        if (
            db.query(WfPlanningTaskSnapshot.id)
            .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
            .filter(WfPlanningTaskSnapshot.parent_uid == task.uid)
            .first()
            is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Task has child tasks and cannot be deleted",
            )

        legacy_task = (
            db.query(MsTask).filter(MsTask.project_id == project_id, MsTask.uid == task_uid).first()
        )
        if is_task_referenced(
            db,
            project_id=project_id,
            task_uid=task_uid,
            task_id=legacy_task.id if legacy_task is not None else None,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Planning task is referenced by estimates, assignments, or charges",
            )

        db.query(WfPlanningLinkSnapshot).filter(
            WfPlanningLinkSnapshot.planning_id == planning.id,
            (WfPlanningLinkSnapshot.task_uid == task_uid)
            | (WfPlanningLinkSnapshot.predecessor_uid == task_uid),
        ).delete(synchronize_session=False)
        db.delete(task)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Planning task is still referenced and cannot be deleted",
            ) from exc
        return
    ensure_project_mutable(project)
    task = _get_task_or_404(db, project_id, task_uid)

    has_children = (
        db.query(MsTask)
        .filter(MsTask.project_id == project_id)
        .filter(MsTask.outline_number.like(f"{task.outline_number}.%"))
        .filter(MsTask.id != task.id)
        .first()
        is not None
    )
    if has_children:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task has child tasks and cannot be deleted",
        )

    in_use = is_task_referenced(db, project_id=project_id, task_uid=task_uid, task_id=task.id)
    if in_use:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task is referenced by estimates, assignments, or charges and cannot be deleted",
        )

    db.query(MsTaskLink).filter(MsTaskLink.project_id == project_id).filter(
        (MsTaskLink.task_uid == task_uid) | (MsTaskLink.predecessor_uid == task_uid)
    ).delete(synchronize_session=False)
    db.query(WfTaskEnrichment).filter(WfTaskEnrichment.project_id == project_id).filter(
        WfTaskEnrichment.task_uid == task_uid
    ).delete(synchronize_session=False)
    db.delete(task)
    db.commit()


@router.get(
    "/{project_id}/tasks/{task_uid}/role-assignments",
    response_model=list[TaskRoleAssignmentRead],
)
def list_task_role_assignments(
    project_id: int,
    task_uid: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[TaskRoleAssignmentRead]:
    _get_project_or_404(db, project_id, current_user.id)
    task = _get_task_or_404(db, project_id, task_uid)
    rows = (
        db.query(TaskRoleAssignment, ResourceRole, CostCategory)
        .join(ResourceRole, TaskRoleAssignment.role_id == ResourceRole.id)
        .join(CostCategory, ResourceRole.cost_category_id == CostCategory.id)
        .filter(TaskRoleAssignment.task_id == task.id)
        .order_by(ResourceRole.code)
        .all()
    )
    return [
        _to_task_role_assignment_read(assignment, role, category)
        for assignment, role, category in rows
    ]


@router.post(
    "/{project_id}/tasks/{task_uid}/role-assignments",
    response_model=TaskRoleAssignmentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_task_role_assignment(
    project_id: int,
    task_uid: int,
    payload: TaskRoleAssignmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TaskRoleAssignmentRead:
    # Known v1 limitation shared with update_task_role_assignment and
    # delete_task_role_assignment below: adding/changing/removing a role
    # assignment here does not recalculate duration_minutes on any draft
    # planning summary task above it -- that only happens on the next
    # move_planning_tasks call (see planning_tree.py). Left for E3-03.
    project = _get_project_or_404(db, project_id, current_user.id)
    ensure_project_mutable(project)
    if project.displayed_planning_id is not None:
        planning = _get_planning_or_404(db, project_id, project.displayed_planning_id)
        snapshot = (
            db.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
            .filter(WfPlanningTaskSnapshot.uid == task_uid)
            .first()
        )
        legacy_task = (
            db.query(MsTask).filter(MsTask.project_id == project_id, MsTask.uid == task_uid).first()
        )
        if snapshot is not None and legacy_task is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Snapshot-only tasks cannot receive legacy role assignments",
            )
    task = _get_task_or_404(db, project_id, task_uid)
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
    assignment = TaskRoleAssignment(task_id=task.id, **payload.model_dump())
    db.add(assignment)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Role is already assigned to this task",
        ) from exc
    db.refresh(assignment)
    return _to_task_role_assignment_read(assignment, role, category)


@router.patch(
    "/{project_id}/tasks/{task_uid}/role-assignments/{assignment_id}",
    response_model=TaskRoleAssignmentRead,
)
def update_task_role_assignment(
    project_id: int,
    task_uid: int,
    assignment_id: int,
    payload: TaskRoleAssignmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TaskRoleAssignmentRead:
    project = _get_project_or_404(db, project_id, current_user.id)
    ensure_project_mutable(project)
    task = _get_task_or_404(db, project_id, task_uid)
    row = (
        db.query(TaskRoleAssignment, ResourceRole, CostCategory)
        .join(ResourceRole, TaskRoleAssignment.role_id == ResourceRole.id)
        .join(CostCategory, ResourceRole.cost_category_id == CostCategory.id)
        .filter(TaskRoleAssignment.id == assignment_id)
        .filter(TaskRoleAssignment.task_id == task.id)
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role assignment not found",
        )

    assignment, role, category = row
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(assignment, field, value)
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return _to_task_role_assignment_read(assignment, role, category)


@router.delete(
    "/{project_id}/tasks/{task_uid}/role-assignments/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_task_role_assignment(
    project_id: int,
    task_uid: int,
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    project = _get_project_or_404(db, project_id, current_user.id)
    ensure_project_mutable(project)
    task = _get_task_or_404(db, project_id, task_uid)
    assignment = (
        db.query(TaskRoleAssignment)
        .filter(TaskRoleAssignment.id == assignment_id)
        .filter(TaskRoleAssignment.task_id == task.id)
        .first()
    )
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role assignment not found",
        )
    db.delete(assignment)
    db.commit()


def _resolve_project_reference_calendar(
    standard_calendar_id: int | None,
    task_calendar_ids: dict[int, int],
    calendars_by_id: dict[int, Calendar],
    weekdays_by_calendar_id: dict[int, list[CalendarWeekday]],
) -> tuple[int | None, tuple[int, int, int] | None]:
    """Pick the calendar exported as the project's reference calendar.

    The current data model has no explicit "project calendar" concept at the
    ms_project level, so this is an E5-02 implementation decision: prefer the
    well-known active STANDARD calendar, and otherwise fall back to the lowest
    calendar id actually referenced by an exported task (deterministic, and
    guarantees the calendar is one we are already exporting).

    STANDARD can legally exist with no working day at all (an empty
    ``weekdays`` list, or every day at 0 hours -- see ``CalendarCreate``), in
    which case it would be useless as a reference calendar
    (``_calendar_header_minutes`` cannot derive MinutesPerDay/Week from it).
    Mirroring the fallback cascade already used by
    ``calendar_schedule.resolve_calendars_for_tasks``
    (see ``_has_any_working_day`` there), a STANDARD with no working day is
    treated as if it did not exist, and resolution falls through to the same
    "lowest referenced task calendar id" rule used when there is no STANDARD
    at all -- rather than abandoning the reference calendar outright.

    Returns ``(None, None)`` when no candidate calendar has any working day,
    in which case the caller preserves legacy stored project header values.
    """
    candidate_ids: list[int] = []
    if standard_calendar_id is not None:
        candidate_ids.append(standard_calendar_id)
    if task_calendar_ids:
        fallback_id = min(task_calendar_ids.values())
        if fallback_id not in candidate_ids:
            candidate_ids.append(fallback_id)

    for calendar_id in candidate_ids:
        calendar = calendars_by_id.get(calendar_id)
        if calendar is None:
            continue
        header_minutes = _calendar_header_minutes(
            calendar, weekdays_by_calendar_id.get(calendar_id, [])
        )
        if header_minutes is not None:
            return calendar_id, header_minutes
    return None, None


def _calendar_header_minutes(
    calendar: Calendar, weekdays: list[CalendarWeekday]
) -> tuple[int, int, int] | None:
    """Derive MinutesPerDay/MinutesPerWeek/DaysPerMonth from a calendar's weekdays.

    Returns None when the calendar has no working day at all, so callers can
    fall back to the legacy stored project values instead of dividing by zero.

    This intentionally does not reuse ``calendar_schedule._day_capacity_minutes``:
    that helper converts a *single* day's ``hours_per_day`` to that day's
    minute capacity, whereas ``minutes_per_day`` here is an *average* over all
    working days and ``minutes_per_week`` is a *sum* across them -- a
    different formula shape, not just the same hours->minutes conversion
    applied once. It already rounds (not truncates) its own hours->minutes
    conversions, so it does not share the truncation bug that motivated
    ``_day_capacity_minutes``.
    """
    working = [weekday for weekday in weekdays if weekday.hours_per_day > 0]
    if not working:
        return None
    total_hours = sum((weekday.hours_per_day for weekday in working), start=Decimal(0))
    minutes_per_day = round(total_hours / len(working) * 60)
    minutes_per_week = round(total_hours * 60)
    days_per_month = max(1, round(calendar.weeks_per_year * len(working) / 12))
    return minutes_per_day, minutes_per_week, days_per_month


def _calendar_working_time_to_text(hours_per_day: Decimal) -> str:
    """Format a calendar day's working hours as a WorkingTime/ToTime xs:time value.

    hours_per_day is capped at 24 by the DB constraint; a full 24h day would
    format as "24:00:00", which is not a valid xs:time, so it is clamped to
    "23:59:59" (E5-02 edge case, no MS Project semantic loss in practice since
    a 24h/day working calendar is not a realistic scenario).
    """
    total_seconds = int(hours_per_day * 3600)
    if total_seconds >= 24 * 3600:
        return "23:59:59"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


@router.get("/{project_id}/export.xml")
def export_project_xml(
    project_id: int,
    planning_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    project = _get_project_or_404(db, project_id, current_user.id)

    selected_planning_id = planning_id or project.displayed_planning_id
    selected_planning = (
        _get_planning_or_404(db, project_id, selected_planning_id)
        if selected_planning_id is not None
        else None
    )
    if selected_planning is not None:
        tasks = _order_snapshots_depth_first(
            db.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == selected_planning.id)
            .all()
        )
        links = (
            db.query(WfPlanningLinkSnapshot)
            .filter(WfPlanningLinkSnapshot.planning_id == selected_planning.id)
            .order_by(WfPlanningLinkSnapshot.id.asc())
            .all()
        )
    else:
        tasks = (
            db.query(MsTask).filter(MsTask.project_id == project_id).order_by(MsTask.id.asc()).all()
        )
        links = (
            db.query(MsTaskLink)
            .filter(MsTaskLink.project_id == project_id)
            .order_by(MsTaskLink.id.asc())
            .all()
        )
    enrichments = db.query(WfTaskEnrichment).filter(WfTaskEnrichment.project_id == project_id).all()

    descriptions_by_uid = {
        enrichment.task_uid: enrichment.description for enrichment in enrichments
    }
    links_by_task_uid: dict[int, list[Any]] = {}
    for link in links:
        links_by_task_uid.setdefault(link.task_uid, []).append(link)

    # Waterfall is the source of truth for working calendars (E5-02): CalendarUID
    # values emitted below are always recomputed from wf_calendar.id, never
    # replayed from an imported file's foreign uids (ms_project.calendar_uid /
    # ms_task.calendar_uid), which are never read here.
    task_calendar_ids = resolve_task_calendar_ids(db, project_id, {task.uid for task in tasks})
    standard_calendar_id = resolve_default_calendar_id(db)

    # Load every candidate calendar (STANDARD plus every task-referenced one)
    # up front, so the reference-calendar resolution below can check whether
    # STANDARD actually has a working day before committing to it as the
    # export's reference, instead of discovering that too late to fall back.
    exported_calendar_ids = set(task_calendar_ids.values())
    if standard_calendar_id is not None:
        exported_calendar_ids.add(standard_calendar_id)

    calendars_by_id: dict[int, Calendar] = {}
    weekdays_by_calendar_id: dict[int, list[CalendarWeekday]] = {}
    if exported_calendar_ids:
        calendars_by_id = {
            calendar.id: calendar
            for calendar in db.query(Calendar).filter(Calendar.id.in_(exported_calendar_ids)).all()
        }
        for weekday in (
            db.query(CalendarWeekday)
            .filter(CalendarWeekday.calendar_id.in_(exported_calendar_ids))
            .all()
        ):
            weekdays_by_calendar_id.setdefault(weekday.calendar_id, []).append(weekday)

    reference_calendar_id, header_minutes = _resolve_project_reference_calendar(
        standard_calendar_id, task_calendar_ids, calendars_by_id, weekdays_by_calendar_id
    )

    ET.register_namespace("", MSP_NS)
    root = ET.Element(f"{{{MSP_NS}}}Project")

    ET.SubElement(root, f"{{{MSP_NS}}}SaveVersion").text = str(project.save_version_out)
    if project.external_uid is not None:
        ET.SubElement(root, f"{{{MSP_NS}}}GUID").text = project.external_uid
    ET.SubElement(root, f"{{{MSP_NS}}}Name").text = project.name
    ET.SubElement(root, f"{{{MSP_NS}}}ScheduleFromStart").text = _bool_to_msp_flag(
        project.schedule_from_start
    )

    start_date = _dt_to_msp_text(project.start_date)
    if start_date is not None:
        ET.SubElement(root, f"{{{MSP_NS}}}StartDate").text = start_date

    finish_date = _dt_to_msp_text(project.finish_date)
    if finish_date is not None:
        ET.SubElement(root, f"{{{MSP_NS}}}FinishDate").text = finish_date

    if reference_calendar_id is not None:
        ET.SubElement(root, f"{{{MSP_NS}}}CalendarUID").text = str(reference_calendar_id)

    if header_minutes is not None:
        minutes_per_day, minutes_per_week, days_per_month = header_minutes
    else:
        minutes_per_day = project.minutes_per_day
        minutes_per_week = project.minutes_per_week
        days_per_month = project.days_per_month
    ET.SubElement(root, f"{{{MSP_NS}}}MinutesPerDay").text = str(minutes_per_day)
    ET.SubElement(root, f"{{{MSP_NS}}}MinutesPerWeek").text = str(minutes_per_week)
    ET.SubElement(root, f"{{{MSP_NS}}}DaysPerMonth").text = str(days_per_month)

    if project.currency_code is not None:
        ET.SubElement(root, f"{{{MSP_NS}}}CurrencyCode").text = project.currency_code

    if exported_calendar_ids:
        calendars_node = ET.SubElement(root, f"{{{MSP_NS}}}Calendars")
        for calendar_id in sorted(exported_calendar_ids):
            calendar = calendars_by_id.get(calendar_id)
            if calendar is None:
                continue
            calendar_node = ET.SubElement(calendars_node, f"{{{MSP_NS}}}Calendar")
            ET.SubElement(calendar_node, f"{{{MSP_NS}}}UID").text = str(calendar.id)
            ET.SubElement(calendar_node, f"{{{MSP_NS}}}Name").text = calendar.name
            weekdays_node = ET.SubElement(calendar_node, f"{{{MSP_NS}}}WeekDays")
            hours_by_day_type = {
                weekday.day_type: weekday.hours_per_day
                for weekday in weekdays_by_calendar_id.get(calendar_id, [])
            }
            for day_type in range(1, 8):
                hours_per_day = hours_by_day_type.get(day_type, Decimal(0))
                weekday_node = ET.SubElement(weekdays_node, f"{{{MSP_NS}}}WeekDay")
                ET.SubElement(weekday_node, f"{{{MSP_NS}}}DayType").text = str(day_type)
                is_working = hours_per_day > 0
                ET.SubElement(weekday_node, f"{{{MSP_NS}}}DayWorking").text = _bool_to_msp_flag(
                    is_working
                )
                if is_working:
                    working_times_node = ET.SubElement(weekday_node, f"{{{MSP_NS}}}WorkingTimes")
                    working_time_node = ET.SubElement(
                        working_times_node, f"{{{MSP_NS}}}WorkingTime"
                    )
                    ET.SubElement(working_time_node, f"{{{MSP_NS}}}FromTime").text = "00:00:00"
                    ET.SubElement(
                        working_time_node, f"{{{MSP_NS}}}ToTime"
                    ).text = _calendar_working_time_to_text(hours_per_day)

    tasks_node = ET.SubElement(root, f"{{{MSP_NS}}}Tasks")
    for task in tasks:
        task_node = ET.SubElement(tasks_node, f"{{{MSP_NS}}}Task")
        ET.SubElement(task_node, f"{{{MSP_NS}}}UID").text = str(task.uid)

        if task.id_display is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}ID").text = str(task.id_display)

        ET.SubElement(task_node, f"{{{MSP_NS}}}Name").text = task.name

        if task.task_type is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}Type").text = str(task.task_type)

        if task.outline_number is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}OutlineNumber").text = task.outline_number

        if task.outline_level is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}OutlineLevel").text = str(task.outline_level)

        start_at = _dt_to_msp_text(task.start_at)
        if start_at is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}Start").text = start_at

        finish_at = _dt_to_msp_text(task.finish_at)
        if finish_at is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}Finish").text = finish_at

        duration = format_duration(task.duration_minutes)
        if duration is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}Duration").text = duration

        if task.duration_format is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}DurationFormat").text = str(task.duration_format)

        if task.percent_complete is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}PercentComplete").text = str(
                task.percent_complete
            )

        ET.SubElement(task_node, f"{{{MSP_NS}}}Summary").text = _bool_to_msp_flag(task.is_summary)
        ET.SubElement(task_node, f"{{{MSP_NS}}}Milestone").text = _bool_to_msp_flag(
            task.is_milestone
        )
        if task.is_manual is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}Manual").text = _bool_to_msp_flag(task.is_manual)

        task_calendar_id = task_calendar_ids.get(task.uid)
        if task_calendar_id is not None and task_calendar_id in calendars_by_id:
            ET.SubElement(task_node, f"{{{MSP_NS}}}CalendarUID").text = str(task_calendar_id)

        description = getattr(task, "notes", None) or descriptions_by_uid.get(task.uid)
        if description:
            ET.SubElement(task_node, f"{{{MSP_NS}}}Notes").text = description

        for link in links_by_task_uid.get(task.uid, []):
            predecessor_link_node = ET.SubElement(task_node, f"{{{MSP_NS}}}PredecessorLink")
            ET.SubElement(predecessor_link_node, f"{{{MSP_NS}}}PredecessorUID").text = str(
                link.predecessor_uid
            )
            ET.SubElement(predecessor_link_node, f"{{{MSP_NS}}}Type").text = str(link.link_type)
            if link.lag_tenth_minute is not None:
                ET.SubElement(predecessor_link_node, f"{{{MSP_NS}}}LinkLag").text = str(
                    link.lag_tenth_minute
                )
            if link.lag_format is not None:
                ET.SubElement(predecessor_link_node, f"{{{MSP_NS}}}LagFormat").text = str(
                    link.lag_format
                )

    xml_content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    try:
        validate_canonical_export_xml(xml_content)
    except MsProjectValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "EXPORT_VALIDATION_FAILED", "issues": exc.issues},
        ) from exc
    return Response(content=xml_content, media_type="application/xml")
