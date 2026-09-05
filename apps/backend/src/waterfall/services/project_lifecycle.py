from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject
from waterfall.models.planning import WfPlanningTaskSnapshot

READ_ONLY_PROJECT_STATUSES = frozenset({"perdu", "termine", "abandonne"})


def ensure_project_mutable(project: MsProject) -> None:
    if project.status in READ_ONLY_PROJECT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project is read-only in its current status",
        )


def _referenced_planning_has_structure(db: Session, project: MsProject) -> bool:
    """Whether the project's currently referenced planning has any task.

    Scoped to ``project.planning_reference_id`` specifically (not "any
    planning the project ever had"), since that is the planning that will
    actually become active when the project reaches ``en_cours``.
    """
    if project.planning_reference_id is None:
        return False
    return (
        db.query(WfPlanningTaskSnapshot.id)
        .filter(WfPlanningTaskSnapshot.planning_id == project.planning_reference_id)
        .first()
        is not None
    )


def validate_project_status_transition(
    db: Session,
    project: MsProject,
    new_status: str,
) -> None:
    if new_status == project.status:
        return
    if project.status in READ_ONLY_PROJECT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived project statuses cannot transition",
        )
    allowed = {
        "cree": {"initialise", "perdu", "abandonne"},
        "initialise": {"en_reponse_appel_offre", "perdu", "abandonne"},
        "en_reponse_appel_offre": {"en_cours", "perdu", "abandonne"},
        "en_cours": {"termine", "abandonne"},
    }
    if new_status not in allowed.get(project.status, set()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid project status transition: {project.status} -> {new_status}",
        )
    if new_status == "en_cours":
        if project.planning_reference_id is None or project.reference_estimate_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Project requires planning and estimate references before en_cours",
            )
        if not _referenced_planning_has_structure(db, project):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Project requires a planning structure before en_cours",
            )
