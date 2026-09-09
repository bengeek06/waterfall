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
    order_ms_tasks_depth_first,
    order_snapshots_depth_first,
    to_snapshot_task_read,
)
from waterfall.api.routes.project_access import (
    get_mutable_project_lock,
    get_planning_or_404,
    get_project_or_404,
)
from waterfall.api.routes.project_cost_codes import resolve_cost_code_id
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

router = APIRouter(prefix="/projects", tags=["projects"])


def _row_number_of(ordered_tasks: list[WfPlanningTaskSnapshot] | list[MsTask], uid: int) -> int:
    """1-based rank of `uid` within an already depth-first-ordered task list."""
    return next(position for position, task in enumerate(ordered_tasks, start=1) if task.uid == uid)


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
        # Ordering is applied inside _to_task_reads (depth-first, same sibling sort as
        # row_number -- E9-02/#147), so the query itself need not order the rows.
        tasks = db.query(MsTask).filter(MsTask.project_id == project_id).all()
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
        # Capture the response while the project/planning row locks are still held (autoflush
        # sees this transaction's own pending `notes` change) so a concurrent writer cannot make
        # us return a later transaction's state -- same convention as `_planning_detail`'s callers.
        ordered_snapshots = order_snapshots_depth_first(
            db.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == displayed_planning.id)
            .all()
        )
        row_number = _row_number_of(ordered_snapshots, task_uid)
        response = to_snapshot_task_read(snapshot, [], project_id, row_number=row_number)
        db.commit()
        return response

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
    # Same rationale as the planning-snapshot branch above: compute the response while the
    # project lock is still held, before releasing it via commit.
    ordered_tasks = order_ms_tasks_depth_first(
        db.query(MsTask).filter(MsTask.project_id == project_id).all()
    )
    row_number = _row_number_of(ordered_tasks, task_uid)
    response = to_task_read(task, description=payload.description, row_number=row_number)
    db.commit()
    return response


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
    payload_data = payload.model_dump(exclude={"cost_code_id"})
    cost_code_id = resolve_cost_code_id(db, project_id, payload.cost_code_id)
    assignment = TaskRoleAssignment(task_id=task.id, cost_code_id=cost_code_id, **payload_data)
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
    get_mutable_project_lock(db, project_id, current_user.id)
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
    values = payload.model_dump(exclude_unset=True)
    if "cost_code_id" in values:
        # An explicit null resolves back to the project's root, exactly like an omitted
        # field does at create time -- never silently detaches the line from imputation
        # (the `.get(...) is not None` form used to let `{"cost_code_id": null}` bypass
        # both validation and the "always attached" invariant).
        values["cost_code_id"] = resolve_cost_code_id(db, project_id, values["cost_code_id"])
    for field, value in values.items():
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
    get_mutable_project_lock(db, project_id, current_user.id)
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
