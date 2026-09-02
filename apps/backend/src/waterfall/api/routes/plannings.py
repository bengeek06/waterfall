# pyright: reportPrivateUsage=false

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user
from waterfall.api.routes.planning_support import (
    _planning_detail,
    _PlanningTaskBodyValidationRoute,
    _to_planning_read,
    _to_task_reads,
    get_mutable_project_with_latest_draft_lock,
    to_project_read,
    to_snapshot_task_read,
)
from waterfall.api.routes.project_access import (
    get_mutable_draft_planning_with_locks,
    get_mutable_project_lock,
    get_planning_or_404,
    get_project_or_404,
)
from waterfall.db.session import get_db
from waterfall.models.ms_core import MsTask, MsTaskLink
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.models.user import User
from waterfall.schemas.projects import (
    FastAPIErrorResponse,
    PlanningCreate,
    PlanningDetailRead,
    PlanningRead,
    PlanningStructureCreate,
    PlanningStructureDraftRead,
    PlanningStructureRead,
    PlanningTaskCreate,
    PlanningTaskDelete,
    PlanningTaskDeleteConflict,
    PlanningTaskMove,
    PlanningTaskScheduleUpdate,
    PlanningTaskTreeRead,
    PlanningTreeRead,
    ProjectRead,
    TaskLinksReplace,
)
from waterfall.services import (
    PlanningLinkError,
    PlanningLinkInvariantError,
    PlanningLinkNotFoundError,
    PlanningTaskScheduleError,
    PlanningTreeCascadeConfirmationRequiredError,
    PlanningTreeInvariantError,
    PlanningTreeMoveError,
    PlanningTreeMoveNotFoundError,
    PlanningTreeTaskReferencedError,
    create_planning_task,
    delete_planning_tasks,
    generate_planning_snapshot,
    generate_planning_structure,
    load_planning_structure_draft,
    move_planning_tasks,
    replace_task_predecessor_links,
    save_planning_structure_draft,
    update_planning_task_schedule,
)
from waterfall.services.project_lifecycle import validate_project_status_transition

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/{project_id}/plannings", response_model=list[PlanningRead])
def list_plannings(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[PlanningRead]:
    get_project_or_404(db, project_id, current_user.id)
    plannings = (
        db.query(WfPlanning)
        .filter(WfPlanning.project_id == project_id)
        .order_by(WfPlanning.version_number.asc())
        .all()
    )
    return [_to_planning_read(planning) for planning in plannings]


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
        db.add_all(
            [
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=task.uid,
                    id_display=task.id_display,
                    structure_key=task.structure_key,
                    structure_kind=task.structure_kind,
                    parent_uid=task.parent_uid,
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
        )
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
        db.add_all(
            [
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=task.uid,
                    id_display=task.id_display,
                    structure_key=task.structure_key,
                    structure_kind=task.structure_kind,
                    parent_uid=task.parent_uid,
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
                    calendar_uid=task.calendar_uid,
                )
                for task in tasks
            ]
        )
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


def move_planning_tasks_route(
    project_id: int,
    planning_id: int,
    payload: PlanningTaskMove,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningDetailRead:
    _, planning = get_mutable_draft_planning_with_locks(
        db, project_id, planning_id, current_user.id
    )
    try:
        move_planning_tasks(db, planning, payload)
        # Capture the response while the row locks are still held so a concurrent
        # writer cannot make us return a later transaction's state.
        detail = _planning_detail(db, planning)
        db.commit()
    except PlanningTreeMoveNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PlanningTreeInvariantError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PlanningTreeMoveError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Planning hierarchy conflicts with existing planning data",
        ) from exc
    return detail


router.add_api_route(
    "/{project_id}/plannings/{planning_id}/tasks/move",
    move_planning_tasks_route,
    methods=["POST"],
    response_model=PlanningDetailRead,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": FastAPIErrorResponse,
            "description": "Requete de deplacement invalide",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": FastAPIErrorResponse,
            "description": "Projet, planning ou tache introuvable pendant le deplacement",
        },
        status.HTTP_409_CONFLICT: {
            "model": FastAPIErrorResponse,
            "description": "Le deplacement entre en conflit avec le planning",
        },
    },
    route_class_override=_PlanningTaskBodyValidationRoute,
)


def create_planning_task_route(
    project_id: int,
    planning_id: int,
    payload: PlanningTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningDetailRead:
    _, planning = get_mutable_draft_planning_with_locks(
        db, project_id, planning_id, current_user.id
    )
    try:
        create_planning_task(db, planning, payload)
        # Capture the response while the row locks are still held so a concurrent
        # writer cannot make us return a later transaction's state.
        detail = _planning_detail(db, planning)
        db.commit()
    except PlanningTreeMoveNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PlanningTreeInvariantError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PlanningTreeMoveError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Planning hierarchy conflicts with existing planning data",
        ) from exc
    return detail


router.add_api_route(
    "/{project_id}/plannings/{planning_id}/tasks",
    create_planning_task_route,
    methods=["POST"],
    response_model=PlanningDetailRead,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": FastAPIErrorResponse,
            "description": "Requete de creation invalide",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": FastAPIErrorResponse,
            "description": "Projet, planning ou tache parent introuvable",
        },
        status.HTTP_409_CONFLICT: {
            "model": FastAPIErrorResponse,
            "description": "La creation entre en conflit avec le planning",
        },
    },
    route_class_override=_PlanningTaskBodyValidationRoute,
)


def delete_planning_tasks_route(
    project_id: int,
    planning_id: int,
    payload: PlanningTaskDelete,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningDetailRead:
    _, planning = get_mutable_draft_planning_with_locks(
        db, project_id, planning_id, current_user.id
    )
    try:
        delete_planning_tasks(db, planning, payload)
        # Capture the response while the row locks are still held so a concurrent
        # writer cannot make us return a later transaction's state.
        detail = _planning_detail(db, planning)
        db.commit()
    except PlanningTreeCascadeConfirmationRequiredError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CASCADE_CONFIRMATION_REQUIRED",
                "descendant_uids": exc.descendant_uids,
            },
        ) from exc
    except PlanningTreeTaskReferencedError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "TASK_REFERENCED", "task_uids": exc.task_uids},
        ) from exc
    except PlanningTreeMoveNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PlanningTreeInvariantError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PlanningTreeMoveError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Planning hierarchy conflicts with existing planning data",
        ) from exc
    return detail


router.add_api_route(
    "/{project_id}/plannings/{planning_id}/tasks/delete",
    delete_planning_tasks_route,
    methods=["POST"],
    response_model=PlanningDetailRead,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": FastAPIErrorResponse,
            "description": "Requete de suppression invalide",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": FastAPIErrorResponse,
            "description": "Projet, planning ou tache introuvable pendant la suppression",
        },
        status.HTTP_409_CONFLICT: {
            "model": PlanningTaskDeleteConflict,
            "description": (
                "Suppression en cascade non confirmee (detail.code="
                "CASCADE_CONFIRMATION_REQUIRED, avec detail.descendant_uids), "
                "ou tache referencee par un devis, une affectation ou une "
                "charge (detail.code=TASK_REFERENCED, avec detail.task_uids)"
            ),
        },
    },
    route_class_override=_PlanningTaskBodyValidationRoute,
)


def update_planning_task_schedule_route(
    project_id: int,
    planning_id: int,
    task_uid: int,
    payload: PlanningTaskScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningDetailRead:
    _, planning = get_mutable_draft_planning_with_locks(
        db, project_id, planning_id, current_user.id
    )
    try:
        update_planning_task_schedule(db, planning, task_uid, payload)
        # Capture the response while the row locks are still held so a concurrent
        # writer cannot make us return a later transaction's state.
        detail = _planning_detail(db, planning)
        db.commit()
    except PlanningTreeMoveNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PlanningTaskScheduleError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task schedule conflicts with existing planning data",
        ) from exc
    return detail


router.add_api_route(
    "/{project_id}/plannings/{planning_id}/tasks/{task_uid}",
    update_planning_task_schedule_route,
    methods=["PATCH"],
    response_model=PlanningDetailRead,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": FastAPIErrorResponse,
            "description": "Combinaison mode/dates/duree invalide",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": FastAPIErrorResponse,
            "description": "Projet, planning ou tache introuvable",
        },
        status.HTTP_409_CONFLICT: {
            "model": FastAPIErrorResponse,
            "description": "La mise a jour du planning entre en conflit avec les donnees",
        },
    },
    route_class_override=_PlanningTaskBodyValidationRoute,
)


def replace_task_predecessor_links_route(
    project_id: int,
    planning_id: int,
    task_uid: int,
    payload: TaskLinksReplace,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningDetailRead:
    _, planning = get_mutable_draft_planning_with_locks(
        db, project_id, planning_id, current_user.id
    )
    try:
        replace_task_predecessor_links(db, planning, task_uid, payload.links)
        # Capture the response while the row locks are still held so a concurrent
        # writer cannot make us return a later transaction's state.
        detail = _planning_detail(db, planning)
        db.commit()
    except PlanningLinkNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PlanningLinkInvariantError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PlanningLinkError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Planning links conflict with existing planning data",
        ) from exc
    return detail


router.add_api_route(
    "/{project_id}/plannings/{planning_id}/tasks/{task_uid}/links",
    replace_task_predecessor_links_route,
    methods=["PUT"],
    response_model=PlanningDetailRead,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": FastAPIErrorResponse,
            "description": "Requete de mise a jour des liens invalide",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": FastAPIErrorResponse,
            "description": "Projet, planning ou tache introuvable pendant la mise a jour des liens",
        },
        status.HTTP_409_CONFLICT: {
            "model": FastAPIErrorResponse,
            "description": "La mise a jour des liens entre en conflit avec le planning",
        },
    },
    route_class_override=_PlanningTaskBodyValidationRoute,
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
    if existing_draft is not None:
        project.displayed_planning_id = existing_draft.id
        if project.status == "cree":
            validate_project_status_transition(db, project, "initialise")
            project.status = "initialise"
        db.commit()
        db.refresh(project)
        return to_project_read(project)
    if project.planning_reference_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A validated planning is required to reopen the structure",
        )
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
            detail="Planning reference must be validated",
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
            id_display=task.id_display,
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
            status_code=status.HTTP_409_CONFLICT, detail="Planning reopen conflict"
        ) from exc
    db.refresh(project)
    return to_project_read(project)


@router.get("/{project_id}/planning-tree", response_model=PlanningTreeRead)
def get_planning_tree(
    project_id: int,
    planning_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PlanningTreeRead:
    project = get_project_or_404(db, project_id, current_user.id)
    selected_id = planning_id or project.displayed_planning_id
    if selected_id is not None:
        detail = _planning_detail(db, get_planning_or_404(db, project_id, selected_id))
        tasks = detail.tasks
    else:
        stored_tasks = (
            db.query(MsTask)
            .filter(MsTask.project_id == project_id)
            .order_by(MsTask.outline_number.asc().nulls_last(), MsTask.id.asc())
            .all()
        )
        tasks = _to_task_reads(db, project_id, stored_tasks)
    tree_by_uid = {task.uid: PlanningTaskTreeRead(**task.model_dump()) for task in tasks}
    roots: list[PlanningTaskTreeRead] = []
    for task in tree_by_uid.values():
        if task.parent_uid is not None and task.parent_uid in tree_by_uid:
            tree_by_uid[task.parent_uid].children.append(task)
        else:
            roots.append(task)
    return PlanningTreeRead(tasks=roots)


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

    return PlanningStructureRead(
        tasks=[to_snapshot_task_read(snapshot, [], project_id) for snapshot in snapshots]
    )


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
