from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user
from waterfall.api.pagination import ListParams, list_params
from waterfall.api.routes.planning_support import (
    _planning_detail,  # pyright: ignore[reportPrivateUsage]
    _to_task_reads,  # pyright: ignore[reportPrivateUsage]
    get_mutable_project_with_displayed_planning_lock,
    to_snapshot_task_read,
)
from waterfall.api.routes.project_access import (
    get_mutable_project_lock,
    get_planning_or_404,
    get_project_or_404,
)
from waterfall.api.routes.projects import (
    get_task_or_404,
    to_task_read,
    to_task_role_assignment_read,
)
from waterfall.db.session import get_db
from waterfall.models.ms_core import MsTask
from waterfall.models.planning import WfPlanningTaskSnapshot
from waterfall.models.resources import CostCategory, CostType, ResourceRole, TaskRoleAssignment
from waterfall.models.user import User
from waterfall.models.wf_core import WfTaskEnrichment
from waterfall.schemas.projects import (
    TaskDescriptionUpdate,
    TaskListRead,
    TaskRead,
    TaskRoleAssignmentCreate,
    TaskRoleAssignmentListRead,
    TaskRoleAssignmentRead,
    TaskRoleAssignmentUpdate,
)
from waterfall.schemas.resources import CostTypeKind
from waterfall.services import apply_pagination
from waterfall.services.project_lifecycle import ensure_project_mutable

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/{project_id}/tasks", response_model=TaskListRead)
def list_project_tasks(
    project_id: int,
    planning_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TaskListRead:
    # Intentionally not paginated (EPIC E7, issue #115): this endpoint feeds the
    # planning editor, which needs the whole task tree to reconstruct the
    # hierarchy and compute summary-task durations -- truncating it would
    # produce orphaned parents and wrong aggregates.
    project = get_project_or_404(db, project_id, current_user.id)
    selected_id = planning_id or project.displayed_planning_id
    if selected_id is not None:
        planning = get_planning_or_404(db, project_id, selected_id)
        items = _planning_detail(db, planning).tasks
    else:
        tasks = (
            db.query(MsTask)
            .filter(MsTask.project_id == project_id)
            .order_by(MsTask.outline_number.asc().nulls_last(), MsTask.id.asc())
            .all()
        )
        items = _to_task_reads(db, project_id, tasks)
    return TaskListRead(items=items, total=len(items), limit=None, offset=0)


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
        return to_snapshot_task_read(snapshot, [], project_id)

    task = get_task_or_404(db, project_id, task_uid)
    enrichment = (
        db.query(WfTaskEnrichment)
        .filter(WfTaskEnrichment.project_id == project_id)
        .filter(WfTaskEnrichment.task_uid == task_uid)
        .first()
    )
    now = datetime.now(UTC)
    if enrichment is None:
        db.add(
            WfTaskEnrichment(
                project_id=project_id,
                task_uid=task_uid,
                description=payload.description,
                created_at=now,
                updated_at=now,
            )
        )
    else:
        enrichment.description = payload.description
        enrichment.updated_at = now
    db.commit()
    return to_task_read(task, description=payload.description)


@router.get(
    "/{project_id}/tasks/{task_uid}/role-assignments",
    response_model=TaskRoleAssignmentListRead,
)
def list_task_role_assignments(
    project_id: int,
    task_uid: int,
    params: ListParams = Depends(list_params),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TaskRoleAssignmentListRead:
    get_project_or_404(db, project_id, current_user.id)
    task = get_task_or_404(db, project_id, task_uid)
    query = (
        db.query(TaskRoleAssignment, ResourceRole, CostCategory)
        .join(ResourceRole, TaskRoleAssignment.role_id == ResourceRole.id)
        .join(CostCategory, ResourceRole.cost_category_id == CostCategory.id)
        .filter(TaskRoleAssignment.task_id == task.id)
    )
    result = apply_pagination(
        query,
        params,
        sortable={
            "role_name": ResourceRole.name,
            "quantity": TaskRoleAssignment.quantity,
            "hours": TaskRoleAssignment.hours,
        },
        default_sort=ResourceRole.name,
        tiebreaker=TaskRoleAssignment.id,
        searchable=(ResourceRole.name,),
    )
    return TaskRoleAssignmentListRead(
        items=[
            to_task_role_assignment_read(assignment, role, category)
            for assignment, role, category in result.rows
        ],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


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
    project = get_mutable_project_lock(db, project_id, current_user.id)
    if project.displayed_planning_id is not None:
        planning = get_planning_or_404(db, project_id, project.displayed_planning_id)
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
    task = get_task_or_404(db, project_id, task_uid)
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
    return to_task_role_assignment_read(assignment, role, category)


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
    project = get_project_or_404(db, project_id, current_user.id)
    ensure_project_mutable(project)
    task = get_task_or_404(db, project_id, task_uid)
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
    return to_task_role_assignment_read(assignment, role, category)


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
    project = get_project_or_404(db, project_id, current_user.id)
    ensure_project_mutable(project)
    task = get_task_or_404(db, project_id, task_uid)
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
