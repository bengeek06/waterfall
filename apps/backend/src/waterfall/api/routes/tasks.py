from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user
from waterfall.api.routes.planning_support import (
    _planning_detail,  # pyright: ignore[reportPrivateUsage]
    _to_task_reads,  # pyright: ignore[reportPrivateUsage]
    get_mutable_project_with_displayed_planning_lock,
    order_ms_tasks_depth_first,
    order_snapshots_depth_first,
    to_snapshot_task_read,
)
from waterfall.api.routes.project_access import (
    get_planning_or_404,
    get_project_or_404,
)
from waterfall.api.routes.projects import get_task_or_404, to_task_read
from waterfall.db.session import get_db
from waterfall.models.ms_core import MsTask
from waterfall.models.planning import WfPlanningTaskSnapshot
from waterfall.models.user import User
from waterfall.models.wf_core import WfTaskEnrichment
from waterfall.schemas.projects import (
    TaskDescriptionUpdate,
    TaskListRead,
    TaskRead,
)

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
