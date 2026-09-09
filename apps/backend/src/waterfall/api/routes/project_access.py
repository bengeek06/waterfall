from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject
from waterfall.models.planning import WfPlanning
from waterfall.services.project_lifecycle import ensure_project_mutable


def get_project_or_404(db: Session, project_id: int, owner_id: int) -> MsProject:
    project = (
        db.query(MsProject)
        .filter(MsProject.id == project_id)
        .filter(MsProject.owner_id == owner_id)
        .first()
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def get_planning_or_404(db: Session, project_id: int, planning_id: int) -> WfPlanning:
    planning = (
        db.query(WfPlanning)
        .filter(WfPlanning.id == planning_id, WfPlanning.project_id == project_id)
        .first()
    )
    if planning is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning not found")
    return planning


def get_mutable_project_lock(db: Session, project_id: int, owner_id: int) -> MsProject:
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


def get_displayed_draft_planning_lock_or_409(db: Session, project: MsProject) -> WfPlanning:
    """Lock and return ``project``'s displayed planning, requiring it to be a draft.

    Used by mutations that add tasks to the currently displayed planning tree
    from a screen other than the Planning tree editor itself (E6-06/#67's "add
    task from the estimate"). ``project`` must already be locked
    (``with_for_update``) by the caller, typically via :func:`get_mutable_project_lock`.

    When the displayed planning is absent, or present but not a draft --
    most commonly because it was validated and no draft has been reopened
    since -- raises a structured 409 pointing the caller at
    ``POST /{project_id}/planning-structure/reopen``, mirroring
    ``PLANNING_STRUCTURE_REOPEN_REQUIRES_VALIDATION``.
    """
    planning = None
    if project.displayed_planning_id is not None:
        planning = (
            db.query(WfPlanning)
            .filter(
                WfPlanning.id == project.displayed_planning_id,
                WfPlanning.project_id == project.id,
            )
            .populate_existing()
            .with_for_update()
            .first()
        )
    if planning is None or planning.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ESTIMATE_TASK_CREATE_REQUIRES_PLANNING_DRAFT"},
        )
    return planning


def raise_on_planning_revision_conflict(
    project_id: int, planning: WfPlanning, expected_revision: int
) -> None:
    """Compare a mutation's expected_revision to the persisted one under the caller's lock."""
    if planning.revision != expected_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PLANNING_REVISION_CONFLICT",
                "project_id": project_id,
                "planning_id": planning.id,
                "expected_revision": expected_revision,
                "current_revision": planning.revision,
            },
        )


def get_latest_draft_planning(
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


def create_draft_planning(
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
