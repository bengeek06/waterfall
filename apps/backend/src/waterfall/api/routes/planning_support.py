# pyright: reportUnusedClass=false, reportUnusedFunction=false

from collections.abc import Callable, Coroutine
from typing import Any, cast

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from waterfall.api.routes.project_access import (
    create_draft_planning,
    get_latest_draft_planning,
    get_mutable_project_lock,
)
from waterfall.models.ms_core import MsProject, MsTask, MsTaskLink
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.models.wf_core import WfTaskEnrichment
from waterfall.schemas.projects import (
    PlanningDetailRead,
    PlanningLinkRead,
    PlanningRead,
    ProjectRead,
    ProjectStatus,
    StructureKind,
    TaskLinkRead,
    TaskRead,
)


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
        currency_code=project.currency_code,
        planning_reference_id=project.planning_reference_id,
        displayed_planning_id=project.displayed_planning_id,
        reference_estimate_id=project.reference_estimate_id,
    )


def get_mutable_project_with_latest_draft_lock(
    db: Session,
    project_id: int,
    owner_id: int,
    *,
    create: bool = False,
    note: str | None = None,
) -> tuple[MsProject, WfPlanning | None]:
    project = get_mutable_project_lock(db, project_id, owner_id)
    planning = get_latest_draft_planning(db, project_id, for_update=True)
    if planning is None and create:
        planning = create_draft_planning(db, project_id=project_id, note=note)
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


def to_snapshot_task_read(
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


def to_task_read(
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
        to_task_read(
            task,
            descriptions_by_uid.get(task.uid),
            links_by_task_uid.get(task.uid),
        )
        for task in tasks
    ]


def _to_planning_read(planning: WfPlanning) -> PlanningRead:
    return PlanningRead(
        id=planning.id,
        project_id=planning.project_id,
        version_number=planning.version_number,
        status=cast(Any, planning.status),
        revision=planning.revision,
        note=planning.note,
        created_at=planning.created_at,
        validated_at=planning.validated_at,
    )


def order_snapshots_depth_first(
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
    ordered = order_snapshots_depth_first(
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
            to_snapshot_task_read(task, links_by_uid.get(task.uid, []), planning.project_id)
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
