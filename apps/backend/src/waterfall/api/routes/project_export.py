from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user
from waterfall.api.revision_errors import revision_operation
from waterfall.api.routes.planning_support import (
    order_ms_tasks_depth_first,
    order_snapshots_depth_first,
)
from waterfall.api.routes.project_access import (
    get_planning_or_404,
    get_project_or_404,
)
from waterfall.db.session import get_db
from waterfall.models.ms_core import MsTask, MsTaskLink
from waterfall.models.planning import WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.models.revision import ProjectRevision
from waterfall.models.user import User
from waterfall.services.msproject_xml import MsProjectValidationError, validate_canonical_export_xml
from waterfall.services.msproject_xml_export import (
    build_project_export_xml,
    build_revision_export_xml,
)

router = APIRouter(prefix="/projects", tags=["projects"])


def _get_revision_or_404(db: Session, project_id: int, revision_id: int) -> ProjectRevision:
    """The revision, scoped to the project the caller named.

    Scoped rather than fetched by id alone, exactly as
    :mod:`waterfall.api.routes.revisions` does it: a revision id belonging to
    somebody else's project answers 404 and not the document.
    """
    revision = (
        db.query(ProjectRevision)
        .filter(ProjectRevision.id == revision_id, ProjectRevision.project_id == project_id)
        .first()
    )
    if revision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"code": "REVISION_NOT_FOUND"}
        )
    return revision


@router.get("/{project_id}/export.xml")
def export_project_xml(
    project_id: int,
    planning_id: int | None = Query(default=None, gt=0),
    revision_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    """Export a project as MS Project XML, from a revision or from the legacy planning.

    ``revision_id`` is the revision-model path (E14-06, #332): the document's task
    uids are then the ``external_uid`` carried by the ``work_item``, which is what
    makes "export then re-import" land on the same elements of work rather than
    duplicating the tree, and each task's calendar is read from its planning facet
    (Règle 1) instead of being resolved back from the roles.

    Without it the legacy planning is exported, unchanged. The default is
    deliberately still the legacy one: the tables the import writes in parallel are
    what every current consumer reads, until #333 migrates them.

    The two selectors are **exclusive**, as the contract has always said, and now
    as the handler behaves: naming both used to serve the revision and drop
    ``planning_id`` on the floor (#332 review, B3). Silently ignoring a parameter a
    caller deliberately sent is how a client ends up convinced it exported a
    planning it never asked the server for, so it is refused instead.

    The revision branch runs under ``revision_operation`` for the same reason every
    other revision route does (#332 review, round 3): loading a revision goes through
    ``ensure_project_calendar``, which raises ``MissingProjectCalendarError`` when no
    active calendar is flagged as the organisation default (Règle 1/INV-15). Untranslated
    it escaped as a bare 500 on a condition the rest of the API publishes as a 409
    ``PROJECT_CALENDAR_MISSING`` -- an asymmetry between an export and its own import,
    on a state the operator can actually repair. The legacy branch below stays outside
    the wrapper on purpose: it reads snapshot rows and never builds a domain project,
    so it has no revision failure to translate.

    The wrapper translates the **whole** ``RevisionFailure`` family, not just that one
    calendar refusal (#332 review, B-4): ``_TRANSLATIONS`` ends on a catch-all
    ``RevisionDomainError -> 400 REVISION_REFUSED``, so this endpoint can answer a 400
    that names no ``EXPORT_SELECTION_AMBIGUOUS``. The contract says so on its 400,
    which is worth stating explicitly here because the parity guard
    (``test_every_emitted_error_code_is_documented_in_the_contract``) only walks
    ``components.responses`` and would not catch a path-level description drifting
    narrower than the code.
    """
    if revision_id is not None and planning_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "EXPORT_SELECTION_AMBIGUOUS"},
        )
    if revision_id is not None:
        project = get_project_or_404(db, project_id, current_user.id)
        _get_revision_or_404(db, project_id, revision_id)
        with revision_operation(db):
            document = build_revision_export_xml(db, project, revision_id)
        return _validated_xml_response(document)

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
        # Depth-first, not MsTask.id.asc(): the exported <ID> is the task's row_number
        # (#147/E9-02, #148/E9-03), which must match its actual displayed rank, not creation
        # order.
        tasks = order_ms_tasks_depth_first(
            db.query(MsTask).filter(MsTask.project_id == project_id).all()
        )
        links = (
            db.query(MsTaskLink)
            .filter(MsTaskLink.project_id == project_id)
            .order_by(MsTaskLink.id.asc())
            .all()
        )

    return _validated_xml_response(build_project_export_xml(db, project, tasks, links))


def _validated_xml_response(xml_content: bytes) -> Response:
    """Serve a document only once it validates against the canonical MSPDI schema.

    A 500 rather than a 4xx on failure, and deliberately so: an export that does not
    validate is a defect of this repository, never something the caller did.
    """
    try:
        validate_canonical_export_xml(xml_content)
    except MsProjectValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "EXPORT_VALIDATION_FAILED", "issues": exc.issues},
        ) from exc
    return Response(content=xml_content, media_type="application/xml")
