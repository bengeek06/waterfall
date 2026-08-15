from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_user
from waterfall.db.session import get_db
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.user import User
from waterfall.models.wf_core import WfTaskEnrichment
from waterfall.schemas.projects import ProjectRead, TaskDescriptionUpdate, TaskRead

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
def list_projects(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[ProjectRead]:
    projects = db.query(MsProject).order_by(MsProject.id.asc()).offset(offset).limit(limit).all()
    return [
        ProjectRead(
            id=project.id,
            name=project.name,
            source_version=project.source_version,
            save_version_out=project.save_version_out,
            schedule_from_start=project.schedule_from_start,
            start_date=project.start_date,
            finish_date=project.finish_date,
            currency_code=project.currency_code,
        )
        for project in projects
    ]


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ProjectRead:
    project = db.query(MsProject).filter(MsProject.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    return ProjectRead(
        id=project.id,
        name=project.name,
        source_version=project.source_version,
        save_version_out=project.save_version_out,
        schedule_from_start=project.schedule_from_start,
        start_date=project.start_date,
        finish_date=project.finish_date,
        currency_code=project.currency_code,
    )


@router.get("/{project_id}/tasks", response_model=list[TaskRead])
def list_project_tasks(
    project_id: int,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[TaskRead]:
    project_exists = db.query(MsProject.id).filter(MsProject.id == project_id).first()
    if project_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    tasks = (
        db.query(MsTask)
        .filter(MsTask.project_id == project_id)
        .order_by(MsTask.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    task_uids = [task.uid for task in tasks]
    descriptions_by_uid: dict[int, str | None] = {}
    if task_uids:
        enrichments = (
            db.query(WfTaskEnrichment)
            .filter(WfTaskEnrichment.project_id == project_id)
            .filter(WfTaskEnrichment.task_uid.in_(task_uids))
            .all()
        )
        descriptions_by_uid = {item.task_uid: item.description for item in enrichments}

    return [
        TaskRead(
            id=task.id,
            project_id=task.project_id,
            uid=task.uid,
            id_display=task.id_display,
            name=task.name,
            outline_number=task.outline_number,
            outline_level=task.outline_level,
            start_at=task.start_at,
            finish_at=task.finish_at,
            percent_complete=task.percent_complete,
            is_summary=task.is_summary,
            is_milestone=task.is_milestone,
            description=descriptions_by_uid.get(task.uid),
        )
        for task in tasks
    ]


@router.patch("/{project_id}/tasks/{task_uid}", response_model=TaskRead)
def update_task_description(
    project_id: int,
    task_uid: int,
    payload: TaskDescriptionUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TaskRead:
    task = (
        db.query(MsTask)
        .filter(MsTask.project_id == project_id)
        .filter(MsTask.uid == task_uid)
        .first()
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    enrichment = (
        db.query(WfTaskEnrichment)
        .filter(WfTaskEnrichment.project_id == project_id)
        .filter(WfTaskEnrichment.task_uid == task_uid)
        .first()
    )

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

    db.commit()

    return TaskRead(
        id=task.id,
        project_id=task.project_id,
        uid=task.uid,
        id_display=task.id_display,
        name=task.name,
        outline_number=task.outline_number,
        outline_level=task.outline_level,
        start_at=task.start_at,
        finish_at=task.finish_at,
        percent_complete=task.percent_complete,
        is_summary=task.is_summary,
        is_milestone=task.is_milestone,
        description=payload.description,
    )
