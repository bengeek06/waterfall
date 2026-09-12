# pyright: reportPrivateUsage=false

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user
from waterfall.api.pagination import ListParams, list_params
from waterfall.api.routes.planning_support import (
    _planning_detail,
    _to_planning_read,
    get_mutable_project_with_latest_draft_lock,
    order_snapshots_depth_first,
    to_project_read,
    to_snapshot_task_read,
)
from waterfall.api.routes.project_access import (
    create_draft_planning,
    get_mutable_draft_planning_with_locks,
    get_mutable_project_lock,
    get_planning_or_404,
    get_project_or_404,
)
from waterfall.db.session import get_db
from waterfall.models.ms_core import MsTask, MsTaskLink
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.models.user import User
from waterfall.models.wf_core import WfTaskEnrichment
from waterfall.schemas.projects import (
    PlanningCreate,
    PlanningDetailRead,
    PlanningListRead,
    PlanningRead,
    PlanningStructureCreate,
    PlanningStructureDraftRead,
    PlanningStructureRead,
    ProjectRead,
)
from waterfall.services import (
    apply_pagination,
    generate_planning_snapshot,
    generate_planning_structure,
    load_planning_structure_draft,
    save_planning_structure_draft,
)
from waterfall.services.project_lifecycle import validate_project_status_transition

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/{project_id}/plannings", response_model=PlanningListRead)
def list_plannings(
    project_id: int,
    params: ListParams = Depends(list_params),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningListRead:
    get_project_or_404(db, project_id, current_user.id)
    query = db.query(WfPlanning).filter(WfPlanning.project_id == project_id)
    result = apply_pagination(
        query,
        params,
        sortable={
            "version_number": WfPlanning.version_number,
            "status": WfPlanning.status,
            "created_at": WfPlanning.created_at,
        },
        searchable=(WfPlanning.note,),
        default_sort=WfPlanning.version_number,
        tiebreaker=WfPlanning.id,
    )
    return PlanningListRead(
        items=[_to_planning_read(planning) for planning in result.rows],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post(
    "/{project_id}/plannings",
    response_model=PlanningDetailRead,
    status_code=status.HTTP_201_CREATED,
)
def create_planning(
    project_id: int,
    payload: PlanningCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningDetailRead:
    project = get_mutable_project_lock(db, project_id, current_user.id)
    source_id = payload.source_planning_id or project.displayed_planning_id
    source: WfPlanning | None = None
    if source_id is not None:
        source = (
            db.query(WfPlanning)
            .filter(WfPlanning.id == source_id, WfPlanning.project_id == project_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        if source is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning not found")
    version_number = (
        db.query(func.max(WfPlanning.version_number))
        .filter(WfPlanning.project_id == project_id)
        .scalar()
        or 0
    ) + 1
    planning = WfPlanning(
        project_id=project_id,
        version_number=version_number,
        status="draft",
        note=payload.note,
        created_at=datetime.now(UTC),
    )
    db.add(planning)
    db.flush()

    if source is not None:
        source_tasks = (
            db.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == source.id)
            .all()
        )
        source_links = (
            db.query(WfPlanningLinkSnapshot)
            .filter(WfPlanningLinkSnapshot.planning_id == source.id)
            .all()
        )
        # parent_uid is a composite self-reference onto (planning_id, uid) within this same
        # batch: inserting it directly here risks a child snapshot landing before its parent in
        # PostgreSQL's per-row FK check order, since `source_tasks` carries no hierarchy-aware
        # ordering guarantee. Insert every clone with parent_uid=None first (a flushed, real uid
        # with no parent is always valid), then backfill the real parent_uid in a second pass once
        # every row already exists -- mirrors reopen_planning_structure below.
        cloned_tasks = [
            WfPlanningTaskSnapshot(
                planning_id=planning.id,
                uid=task.uid,
                structure_key=task.structure_key,
                structure_kind=task.structure_kind,
                parent_uid=None,
                position=task.position,
                name=task.name,
                notes=task.notes,
                task_type=task.task_type,
                outline_number=task.outline_number,
                outline_level=task.outline_level,
                wbs=task.wbs,
                start_at=task.start_at,
                finish_at=task.finish_at,
                duration_minutes=task.duration_minutes,
                duration_format=task.duration_format,
                work_minutes=task.work_minutes,
                percent_complete=task.percent_complete,
                is_summary=task.is_summary,
                is_milestone=task.is_milestone,
                is_manual=task.is_manual,
                calendar_uid=task.calendar_uid,
            )
            for task in source_tasks
        ]
        db.add_all(cloned_tasks)
        db.flush()
        parent_by_uid = {task.uid: task.parent_uid for task in source_tasks}
        for cloned_task in cloned_tasks:
            cloned_task.parent_uid = parent_by_uid[cloned_task.uid]
        db.flush()
        db.add_all(
            [
                WfPlanningLinkSnapshot(
                    planning_id=planning.id,
                    task_uid=link.task_uid,
                    predecessor_uid=link.predecessor_uid,
                    link_type=link.link_type,
                    lag_tenth_minute=link.lag_tenth_minute,
                    lag_format=link.lag_format,
                )
                for link in source_links
            ]
        )
    else:
        tasks = db.query(MsTask).filter(MsTask.project_id == project_id).all()
        # MsTask carries no `notes` column of its own -- legacy task notes live in
        # WfTaskEnrichment, keyed by (project_id, task_uid), the same table
        # update_task falls back to writing/reading while no WfPlanning
        # exists yet for the project (see tasks.py). Build a uid -> description lookup
        # up front so it can be reported onto WfPlanningTaskSnapshot.notes below.
        enrichments = (
            db.query(WfTaskEnrichment).filter(WfTaskEnrichment.project_id == project_id).all()
        )
        enrichment_by_uid = {
            enrichment.task_uid: enrichment.description for enrichment in enrichments
        }
        # Same composite self-reference hazard as the source_planning_id branch above:
        # parent_uid is a self-reference onto (planning_id, uid) within this same batch,
        # and `tasks` carries no hierarchy-aware ordering guarantee. Insert every clone
        # with parent_uid=None first, then backfill the real parent_uid in a second pass
        # once every row already exists.
        cloned_tasks = [
            WfPlanningTaskSnapshot(
                planning_id=planning.id,
                uid=task.uid,
                structure_key=task.structure_key,
                structure_kind=task.structure_kind,
                parent_uid=None,
                position=task.position,
                name=task.name,
                notes=enrichment_by_uid.get(task.uid),
                task_type=task.task_type,
                outline_number=task.outline_number,
                outline_level=task.outline_level,
                wbs=task.wbs,
                start_at=task.start_at,
                finish_at=task.finish_at,
                duration_minutes=task.duration_minutes,
                duration_format=task.duration_format,
                work_minutes=task.work_minutes,
                percent_complete=task.percent_complete,
                is_summary=task.is_summary,
                is_milestone=task.is_milestone,
                is_manual=task.is_manual,
                calendar_uid=task.calendar_uid,
            )
            for task in tasks
        ]
        db.add_all(cloned_tasks)
        db.flush()
        parent_by_uid = {task.uid: task.parent_uid for task in tasks}
        for cloned_task in cloned_tasks:
            cloned_task.parent_uid = parent_by_uid[cloned_task.uid]
        db.flush()
        links = db.query(MsTaskLink).filter(MsTaskLink.project_id == project_id).all()
        db.add_all(
            [
                WfPlanningLinkSnapshot(
                    planning_id=planning.id,
                    task_uid=link.task_uid,
                    predecessor_uid=link.predecessor_uid,
                    link_type=link.link_type,
                    lag_tenth_minute=link.lag_tenth_minute,
                    lag_format=link.lag_format,
                )
                for link in links
            ]
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Planning version conflicts with existing project data",
        ) from exc
    db.refresh(planning)
    return _planning_detail(db, planning)


@router.get("/{project_id}/plannings/{planning_id}", response_model=PlanningDetailRead)
def get_planning(
    project_id: int,
    planning_id: int,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningDetailRead:
    get_project_or_404(db, project_id, current_user.id)
    return _planning_detail(
        db, get_planning_or_404(db, project_id, planning_id), offset=offset, limit=limit
    )


@router.post("/{project_id}/plannings/{planning_id}/validate", response_model=PlanningRead)
def validate_planning(
    project_id: int,
    planning_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningRead:
    _, planning = get_mutable_draft_planning_with_locks(
        db, project_id, planning_id, current_user.id
    )
    planning.status = "validated"
    planning.validated_at = datetime.now(UTC)
    db.commit()
    db.refresh(planning)
    return _to_planning_read(planning)


@router.post("/{project_id}/plannings/{planning_id}/reference", response_model=ProjectRead)
def set_planning_reference(
    project_id: int,
    planning_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    project = get_mutable_project_lock(db, project_id, current_user.id)
    planning = (
        db.query(WfPlanning)
        .filter(WfPlanning.id == planning_id, WfPlanning.project_id == project_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if planning is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning not found")
    if planning.status != "validated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Planning must be validated",
        )
    previous = project.planning_reference_id
    if previous is not None and previous != planning.id:
        old = (
            db.query(WfPlanning)
            .filter(WfPlanning.id == previous, WfPlanning.project_id == project_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        if old is not None:
            old.status = "superseded"
    project.planning_reference_id = planning.id
    if project.displayed_planning_id is None:
        project.displayed_planning_id = planning.id
    db.commit()
    db.refresh(project)
    return to_project_read(project)


@router.post("/{project_id}/plannings/{planning_id}/display", response_model=ProjectRead)
def set_displayed_planning(
    project_id: int,
    planning_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    project = get_mutable_project_lock(db, project_id, current_user.id)
    planning = (
        db.query(WfPlanning)
        .filter(WfPlanning.id == planning_id, WfPlanning.project_id == project_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if planning is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning not found")
    project.displayed_planning_id = planning_id
    db.commit()
    db.refresh(project)
    return to_project_read(project)


@router.post("/{project_id}/planning-structure/reopen", response_model=ProjectRead)
def reopen_planning_structure(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    project, existing_draft = get_mutable_project_with_latest_draft_lock(
        db, project_id, current_user.id
    )
    if existing_draft is None and project.planning_reference_id is None:
        # No draft and no validated reference: the structure step was skipped
        # entirely, or its only draft was deleted/validated without ever being
        # set as the reference. Reopen simply means opening an empty draft.
        existing_draft = create_draft_planning(
            db, project_id=project_id, note="Structure reopened (empty planning)"
        )
    if existing_draft is not None:
        project.displayed_planning_id = existing_draft.id
        if project.status == "cree":
            validate_project_status_transition(db, project, "initialise")
            project.status = "initialise"
        db.commit()
        db.refresh(project)
        return to_project_read(project)
    # existing_draft is None here only when project.planning_reference_id is set
    # (handled above otherwise), so cloning from the validated reference below
    # always has a source to work from.
    source = (
        db.query(WfPlanning)
        .filter(
            WfPlanning.id == project.planning_reference_id,
            WfPlanning.project_id == project_id,
        )
        .populate_existing()
        .with_for_update()
        .first()
    )
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning not found")
    if source.status != "validated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PLANNING_STRUCTURE_REOPEN_REQUIRES_VALIDATION"},
        )
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
        note="Structure reopened",
        created_at=datetime.now(UTC),
    )
    db.add(planning)
    db.flush()
    source_tasks = (
        db.query(WfPlanningTaskSnapshot)
        .filter(WfPlanningTaskSnapshot.planning_id == source.id)
        .all()
    )
    cloned_tasks = [
        WfPlanningTaskSnapshot(
            planning_id=planning.id,
            uid=task.uid,
            structure_key=task.structure_key,
            structure_kind=task.structure_kind,
            parent_uid=None,
            position=task.position,
            name=task.name,
            task_type=task.task_type,
            outline_number=task.outline_number,
            outline_level=task.outline_level,
            wbs=task.wbs,
            start_at=task.start_at,
            finish_at=task.finish_at,
            duration_minutes=task.duration_minutes,
            duration_format=task.duration_format,
            work_minutes=task.work_minutes,
            percent_complete=task.percent_complete,
            is_summary=task.is_summary,
            is_milestone=task.is_milestone,
            is_manual=task.is_manual,
            notes=task.notes,
            calendar_uid=task.calendar_uid,
        )
        for task in source_tasks
    ]
    db.add_all(cloned_tasks)
    db.flush()
    parent_by_uid = {task.uid: task.parent_uid for task in source_tasks}
    for task in cloned_tasks:
        task.parent_uid = parent_by_uid[task.uid]
    db.flush()
    source_links = (
        db.query(WfPlanningLinkSnapshot)
        .filter(WfPlanningLinkSnapshot.planning_id == source.id)
        .all()
    )
    db.add_all(
        WfPlanningLinkSnapshot(
            planning_id=planning.id,
            task_uid=link.task_uid,
            predecessor_uid=link.predecessor_uid,
            link_type=link.link_type,
            lag_tenth_minute=link.lag_tenth_minute,
            lag_format=link.lag_format,
        )
        for link in source_links
    )
    project.displayed_planning_id = planning.id
    if project.status == "cree":
        validate_project_status_transition(db, project, "initialise")
        project.status = "initialise"
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PLANNING_STRUCTURE_REOPEN_INTEGRITY_CONFLICT"},
        ) from exc
    db.refresh(project)
    return to_project_read(project)


@router.post(
    "/{project_id}/planning-structure",
    response_model=PlanningStructureRead,
    status_code=status.HTTP_201_CREATED,
)
def create_planning_structure(
    project_id: int,
    payload: PlanningStructureCreate | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningStructureRead:
    """Generate the planning skeleton from a poste/lot/livrable structure.

    Additive/idempotent generation by ``structure_key``: tasks without a
    ``structure_key`` (import or manual entry) are always preserved, only
    tasks previously generated by the skeleton (with a ``structure_key``) are
    updated or removed when they no longer appear in the submitted structure.
    """
    try:
        project, planning = get_mutable_project_with_latest_draft_lock(
            db,
            project_id,
            current_user.id,
            create=True,
            note="Generated from planning structure",
        )
        assert planning is not None
        if payload is None:
            payload = load_planning_structure_draft(planning)
            if payload is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A saved planning structure draft is required",
                )
        snapshots = generate_planning_snapshot(db, project, payload, planning)
        if project.planning_reference_id is None:
            generate_planning_structure(db, project, payload)
        # Keep the persisted draft in sync with the structure actually generated so the
        # editor reopens on the latest content instead of a stale saved draft.
        save_planning_structure_draft(planning, payload)
        project.displayed_planning_id = planning.id
        if project.status == "cree":
            validate_project_status_transition(db, project, "initialise")
            project.status = "initialise"
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Planning structure conflicts with existing project data",
        ) from exc

    # Reorder depth-first before numbering rather than trusting generation order (E9-02,
    # #147): consistent with every other row_number call site, even though a freshly
    # generated structure is already expected to come out in that order.
    ordered_snapshots = order_snapshots_depth_first(snapshots)
    return PlanningStructureRead(
        tasks=[
            to_snapshot_task_read(snapshot, [], project_id, row_number=position)
            for position, snapshot in enumerate(ordered_snapshots, start=1)
        ]
    )


@router.post("/{project_id}/planning-structure/skip", response_model=ProjectRead)
def skip_planning_structure(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    """Leave the poste/lot/livrable step without generating a skeleton (issue #130).

    Creates or reuses an empty draft planning and transitions a project still
    in ``cree`` to ``initialise`` without requiring any structure. This is a
    shortcut for leaving the structure screen at project initialisation, not
    a generic way to reset the displayed planning: it is rejected once the
    project has left ``cree`` so it can never silently overwrite
    ``displayed_planning_id`` on a project that already has a validated
    reference. Distinct from saving a draft (which never changes the project
    status) and from generating the skeleton (which still requires at least
    one poste/lot/livrable).
    """
    project, planning = get_mutable_project_with_latest_draft_lock(
        db,
        project_id,
        current_user.id,
        create=True,
        note="Structure step skipped (empty planning)",
    )
    assert planning is not None
    has_tasks = (
        db.query(WfPlanningTaskSnapshot.id)
        .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
        .first()
        is not None
    )
    if (
        project.status != "cree"
        or project.planning_reference_id is not None
        or project.displayed_planning_id is not None
        or has_tasks
    ):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project already has a planning; skip is only valid before any planning exists",
        )
    project.displayed_planning_id = planning.id
    validate_project_status_transition(db, project, "initialise")
    project.status = "initialise"
    db.commit()
    db.refresh(project)
    return to_project_read(project)


@router.put(
    "/{project_id}/planning-structure/draft",
    response_model=PlanningStructureDraftRead,
)
def save_planning_structure_draft_route(
    project_id: int,
    payload: PlanningStructureCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningStructureDraftRead:
    try:
        _, planning = get_mutable_project_with_latest_draft_lock(
            db,
            project_id,
            current_user.id,
            create=True,
        )
        assert planning is not None
        save_planning_structure_draft(planning, payload)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Planning structure conflicts with existing project data",
        ) from exc

    return PlanningStructureDraftRead(planning_id=planning.id, structure=payload)


@router.get(
    "/{project_id}/planning-structure/draft",
    response_model=PlanningStructureDraftRead,
)
def get_planning_structure_draft_route(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningStructureDraftRead:
    project = get_project_or_404(db, project_id, current_user.id)
    planning = (
        db.query(WfPlanning)
        .filter(
            WfPlanning.project_id == project.id,
            WfPlanning.status == "draft",
            WfPlanning.structure_draft_json.isnot(None),
        )
        .order_by(WfPlanning.version_number.desc())
        .first()
    )
    if planning is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No planning structure draft found",
        )
    try:
        payload = load_planning_structure_draft(planning)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No planning structure draft found",
        )
    return PlanningStructureDraftRead(planning_id=planning.id, structure=payload)
