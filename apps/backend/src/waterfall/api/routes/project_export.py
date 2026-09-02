from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user
from waterfall.api.routes.planning_support import (
    order_snapshots_depth_first,
)
from waterfall.api.routes.project_access import (
    get_planning_or_404,
    get_project_or_404,
)
from waterfall.db.session import get_db
from waterfall.models.ms_core import MsTask, MsTaskLink
from waterfall.models.planning import WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.models.user import User
from waterfall.services.msproject_xml import MsProjectValidationError, validate_canonical_export_xml
from waterfall.services.msproject_xml_export import build_project_export_xml

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/{project_id}/export.xml")
def export_project_xml(
    project_id: int,
    planning_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    project = get_project_or_404(db, project_id, current_user.id)
    selected_planning_id = planning_id or project.displayed_planning_id
    selected_planning = (
        get_planning_or_404(db, project_id, selected_planning_id)
        if selected_planning_id is not None
        else None
    )
    if selected_planning is not None:
        tasks = order_snapshots_depth_first(
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

    xml_content = build_project_export_xml(db, project, tasks, links)
    try:
        validate_canonical_export_xml(xml_content)
    except MsProjectValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "EXPORT_VALIDATION_FAILED", "issues": exc.issues},
        ) from exc
    return Response(content=xml_content, media_type="application/xml")
