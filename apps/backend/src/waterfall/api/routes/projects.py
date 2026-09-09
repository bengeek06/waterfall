from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user
from waterfall.api.pagination import ListParams, list_params
from waterfall.api.routes.project_access import (
    get_project_or_404,
)
from waterfall.db.session import get_db
from waterfall.models.ms_core import MsProject, MsTask, MsTaskLink
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.models.resources import (
    CostCategory,
    CostType,
    Estimate,
    EstimateCostLine,
    EstimateLine,
    EstimateRoleAssignment,
    EstimateTaskRow,
    ProjectCostCode,
    ResourceRole,
    TaskRoleAssignment,
)
from waterfall.models.user import User
from waterfall.models.wf_core import WfChargeLine, WfExcelImport, WfImportBatch, WfTaskEnrichment
from waterfall.schemas.projects import (
    EstimateCostLineRead,
    EstimateRoleAssignmentRead,
    EstimateTaskRowRead,
    ProjectCreate,
    ProjectEstimateRead,
    ProjectListRead,
    ProjectRead,
    ProjectSetupWarningsRead,
    ProjectStatus,
    ProjectStatusUpdate,
    ProjectUpdate,
    StructureKind,
    SupplyStatus,
    TaskLinkRead,
    TaskRead,
)
from waterfall.schemas.resources import CostTypeKind
from waterfall.services import apply_pagination, get_project_setup_warnings
from waterfall.services.project_lifecycle import (
    ensure_project_mutable,
    validate_project_status_transition,
)

router = APIRouter(prefix="/projects", tags=["projects"])


def to_project_read(project: MsProject) -> ProjectRead:
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
        minutes_per_day=project.minutes_per_day,
        minutes_per_week=project.minutes_per_week,
        days_per_month=project.days_per_month,
        currency_code=project.currency_code,
        planning_reference_id=project.planning_reference_id,
        displayed_planning_id=project.displayed_planning_id,
        reference_estimate_id=project.reference_estimate_id,
    )


def get_estimate_or_404(db: Session, project_id: int, estimate_id: int) -> Estimate:
    estimate = (
        db.query(Estimate)
        .filter(Estimate.id == estimate_id)
        .filter(Estimate.project_id == project_id)
        .first()
    )
    if estimate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Estimate not found")
    return estimate


def to_project_estimate_read(estimate: Estimate) -> ProjectEstimateRead:
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


def to_estimate_task_row_read(row: EstimateTaskRow) -> EstimateTaskRowRead:
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


def to_estimate_cost_line_read(line: EstimateCostLine) -> EstimateCostLineRead:
    return EstimateCostLineRead(
        id=line.id,
        estimate_id=line.estimate_id,
        task_id=line.task_id,
        cost_type_id=line.cost_type_id,
        cost_category_id=line.cost_category_id,
        cost_code_id=line.cost_code_id,
        cost_type_code=line.cost_type_code,
        accounting_code=line.accounting_code,
        category_code=line.category_code,
        label=line.label,
        quantity=line.quantity,
        unit_cost=line.unit_cost,
        purchase_cost=line.purchase_cost,
        supply_status=cast(SupplyStatus | None, line.supply_status),
        planned_date=line.planned_date,
    )


def get_draft_estimate_or_409(db: Session, project_id: int, estimate_id: int) -> Estimate:
    project = db.get(MsProject, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    ensure_project_mutable(project)
    estimate = get_estimate_or_404(db, project_id, estimate_id)
    if estimate.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Estimate is not a draft")
    return estimate


def get_non_labor_category_or_400(
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


def get_task_or_404(db: Session, project_id: int, task_uid: int) -> MsTask:
    task = (
        db.query(MsTask)
        .filter(MsTask.project_id == project_id)
        .filter(MsTask.uid == task_uid)
        .first()
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def to_task_read(
    task: MsTask,
    description: str | None,
    predecessor_links: list[MsTaskLink] | None = None,
    *,
    row_number: int,
) -> TaskRead:
    return TaskRead(
        id=task.id,
        project_id=task.project_id,
        uid=task.uid,
        row_number=row_number,
        structure_key=task.structure_key,
        structure_kind=cast(StructureKind | None, task.structure_kind),
        parent_uid=task.parent_uid,
        position=task.position,
        name=task.name,
        outline_number=task.outline_number,
        outline_level=task.outline_level,
        wbs=task.wbs,
        start_at=task.start_at,
        finish_at=task.finish_at,
        duration_minutes=task.duration_minutes,
        duration_format=task.duration_format,
        work_minutes=task.work_minutes,
        task_type=task.task_type,
        percent_complete=task.percent_complete,
        is_summary=task.is_summary,
        is_milestone=task.is_milestone,
        is_manual=task.is_manual,
        calendar_uid=task.calendar_uid,
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


def to_estimate_role_assignment_read(
    assignment: EstimateRoleAssignment,
    role: ResourceRole,
    category: CostCategory,
) -> EstimateRoleAssignmentRead:
    return EstimateRoleAssignmentRead(
        id=assignment.id,
        estimate_id=assignment.estimate_id,
        task_id=assignment.task_id,
        role_id=role.id,
        role_code=role.name,
        role_name=role.name,
        cost_category_id=category.id,
        accounting_code=category.accounting_code,
        cost_code_id=assignment.cost_code_id,
        quantity=assignment.quantity,
        hours=assignment.hours,
        comment=assignment.comment,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


@router.get("", response_model=ProjectListRead)
def list_projects(
    include_archived: bool = Query(default=False),
    params: ListParams = Depends(list_params),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectListRead:
    query = db.query(MsProject).filter(MsProject.owner_id == current_user.id)
    if not include_archived:
        query = query.filter(MsProject.status.notin_(["perdu", "termine", "abandonne"]))
    result = apply_pagination(
        query,
        params,
        sortable={
            "name": MsProject.name,
            "status": MsProject.status,
            "id": MsProject.id,
        },
        tiebreaker=MsProject.id,
        searchable=[MsProject.name],
    )
    return ProjectListRead(
        items=[to_project_read(project) for project in result.rows],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


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
    # Flush (not commit) to obtain project.id without ending the transaction: the root cost
    # code below must be created atomically with the project itself, never as a second,
    # separately-committed write -- a failure creating it must roll back the whole project
    # creation instead of leaving a durable MsProject row with no root cost code (#62/E6-01
    # review finding: E6-02 depends on every project always having one).
    db.flush()

    # Issue #62 (E6-01): every project gets a single automatically-created root cost
    # code, named after the project's own code -- or the deterministic PRJ-{id}
    # fallback when the project has none, since `MsProject.code` is nullable. The
    # user may rename this root afterward like any other cost code; only its
    # creation is automatic.
    root_cost_code = ProjectCostCode(
        project_id=project.id,
        parent_id=None,
        code=project.code or f"PRJ-{project.id}",
        name=project.name,
    )
    db.add(root_cost_code)
    db.commit()
    db.refresh(project)
    return to_project_read(project)


@router.get("/setup-warnings", response_model=ProjectSetupWarningsRead)
def get_setup_warnings(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> ProjectSetupWarningsRead:
    """Issue #109: non-blocking global setup prerequisites for project creation.

    Registered before ``/{project_id}`` so this literal path is matched
    first -- otherwise ``project_id: int`` would reject ``"setup-warnings"``
    with a 422 before this route ever got a chance to run.

    Never blocks ``POST /projects``: the frontend calls this to warn the user
    before they open the project-creation dialog, but project creation
    itself remains possible regardless of what this returns.
    """
    return ProjectSetupWarningsRead(warnings=get_project_setup_warnings(db))


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    return to_project_read(get_project_or_404(db, project_id, current_user.id))


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    project = get_project_or_404(db, project_id, current_user.id)
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

    return to_project_read(project)


@router.patch("/{project_id}/status", response_model=ProjectRead)
def update_project_status(
    project_id: int,
    payload: ProjectStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    project = get_project_or_404(db, project_id, current_user.id)
    ensure_project_mutable(project)
    validate_project_status_transition(db, project, payload.status)
    project.status = payload.status
    db.commit()
    db.refresh(project)
    return to_project_read(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    project = get_project_or_404(db, project_id, current_user.id)
    ensure_project_mutable(project)
    planning_ids = [
        row[0] for row in db.query(WfPlanning.id).filter(WfPlanning.project_id == project_id).all()
    ]
    if planning_ids:
        project.planning_reference_id = None
        project.displayed_planning_id = None
        # Autoflush is disabled on this session (see db/session.py): without an explicit flush,
        # these ORM-level updates stay pending while the raw deletes below run directly against
        # the database, so ms_project.displayed_planning_id still points at the about-to-be-deleted
        # wf_planning row and fk_ms_project_displayed_planning rejects the DELETE.
        db.flush()
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
        db.query(EstimateRoleAssignment).filter(
            EstimateRoleAssignment.estimate_id.in_(estimate_ids)
        ).delete(synchronize_session=False)
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
    # Issue #62 (E6-01): a single bulk DELETE removing every ProjectCostCode row for
    # this project -- root and every descendant -- in one SQL statement. PostgreSQL's
    # default (immediate, not-deferrable) FK constraint check for the self-referencing
    # parent_id column is evaluated at the end of the statement, not per row, so this
    # works regardless of tree order without needing a leaf-first delete or ON DELETE
    # CASCADE.
    db.query(ProjectCostCode).filter(ProjectCostCode.project_id == project_id).delete(
        synchronize_session=False
    )
    db.delete(project)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
