from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user
from waterfall.api.routes.planning_support import (
    _planning_detail,  # pyright: ignore[reportPrivateUsage]
    _PlanningTaskBodyValidationRoute,  # pyright: ignore[reportPrivateUsage]
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
    TaskListRead,
    TaskRead,
    TaskUpdate,
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


def update_task(
    project_id: int,
    task_uid: int,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TaskRead:
    """Update a task's description and/or name (issue #290, E12-08 added ``name``).

    Unlike ``description`` (backed by ``WfTaskEnrichment`` when no planning is
    displayed -- a fallback table that exists only for the no-planning case,
    see that model's own docstring), ``name`` has no such fallback:
    ``MsTask.name`` is always the canonical column, so renaming is simpler --
    it only ever writes ``WfPlanningTaskSnapshot.name``/``MsTask.name``
    themselves, in the same transaction, never a side table. This is also the
    rename channel that makes a draft devis's task rows "live" (E12-08,
    ``services.estimate_task_display``): renaming here is immediately visible
    on every draft estimate referencing this task, without recreating it.

    Both fields are genuinely independent partial updates: a request with
    only ``name`` (or only ``description``) never touches the other --
    checked via ``model_fields_set`` rather than "is not None", since an
    explicit ``description: null`` is a valid, pre-existing way to clear it
    (``name`` has no such clearing form, see ``TaskUpdate``'s own docstring).
    """
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
        if "description" in payload.model_fields_set:
            snapshot.notes = payload.description
        if payload.name is not None:
            snapshot.name = payload.name
            twin = (
                db.query(MsTask)
                .filter(MsTask.project_id == project_id, MsTask.uid == task_uid)
                .first()
            )
            # A snapshot-only task (no MsTask twin yet, see
            # _resolve_legacy_parent_task's own docstring) has nothing else to
            # keep in sync -- silently skipped, same fallback as elsewhere.
            if twin is not None:
                twin.name = payload.name
        # Capture the response while the project/planning row locks are still held (autoflush
        # sees this transaction's own pending `notes`/`name` change) so a concurrent writer
        # cannot make us return a later transaction's state -- same convention as
        # `_planning_detail`'s callers.
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
    if payload.name is not None:
        task.name = payload.name
    enrichment = (
        db.query(WfTaskEnrichment)
        .filter(WfTaskEnrichment.project_id == project_id)
        .filter(WfTaskEnrichment.task_uid == task_uid)
        .first()
    )
    if "description" in payload.model_fields_set:
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
    # Same rationale as the planning-snapshot branch above: compute the response while the
    # project lock is still held, before releasing it via commit. Reads the description
    # back off `enrichment` (rather than `payload.description`) so a name-only request
    # (no "description" key) reports the pre-existing description unchanged, not `null`.
    ordered_tasks = order_ms_tasks_depth_first(
        db.query(MsTask).filter(MsTask.project_id == project_id).all()
    )
    row_number = _row_number_of(ordered_tasks, task_uid)
    resolved_description = enrichment.description if enrichment is not None else None
    response = to_task_read(task, description=resolved_description, row_number=row_number)
    db.commit()
    return response


router.add_api_route(
    "/{project_id}/tasks/{task_uid}",
    update_task,
    methods=["PATCH"],
    response_model=TaskRead,
    # E12-08 Finding Haute #2, round 4 review: `openapi/spec/paths/projects.yaml`
    # documents a 400 (FastAPIErrorResponse) for an invalid `TaskUpdate` body
    # (e.g. an empty/too-long `name`), but FastAPI's own default behaviour
    # raises the framework's 422 RequestValidationError -- never converted to
    # the documented 400 without this override, same pattern already applied
    # to `create_estimate_task` (`api/routes/estimates.py`).
    route_class_override=_PlanningTaskBodyValidationRoute,
)
