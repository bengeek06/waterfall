import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session
from waterfall.api.dependencies import get_current_user
from waterfall.db.session import get_db
from waterfall.models.ms_core import MsProject, MsTask, MsTaskLink
from waterfall.models.user import User
from waterfall.models.wf_core import WfTaskEnrichment
from waterfall.schemas.projects import ProjectRead, TaskDescriptionUpdate, TaskRead

router = APIRouter(prefix="/projects", tags=["projects"])
MSP_NS = "http://schemas.microsoft.com/project"


def _bool_to_msp_flag(value: bool) -> str:
    return "1" if value else "0"


def _dt_to_msp_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    return value.isoformat(timespec="seconds")


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


@router.get("/{project_id}/export.xml")
def export_project_xml(
    project_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    project = db.query(MsProject).filter(MsProject.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    tasks = db.query(MsTask).filter(MsTask.project_id == project_id).order_by(MsTask.id.asc()).all()
    links = (
        db.query(MsTaskLink)
        .filter(MsTaskLink.project_id == project_id)
        .order_by(MsTaskLink.id.asc())
        .all()
    )
    enrichments = db.query(WfTaskEnrichment).filter(WfTaskEnrichment.project_id == project_id).all()

    descriptions_by_uid = {
        enrichment.task_uid: enrichment.description for enrichment in enrichments
    }
    links_by_task_uid: dict[int, list[MsTaskLink]] = {}
    for link in links:
        links_by_task_uid.setdefault(link.task_uid, []).append(link)

    ET.register_namespace("", MSP_NS)
    root = ET.Element(f"{{{MSP_NS}}}Project")

    ET.SubElement(root, f"{{{MSP_NS}}}SaveVersion").text = str(project.save_version_out)
    ET.SubElement(root, f"{{{MSP_NS}}}Name").text = project.name
    ET.SubElement(root, f"{{{MSP_NS}}}ScheduleFromStart").text = _bool_to_msp_flag(
        project.schedule_from_start
    )

    start_date = _dt_to_msp_text(project.start_date)
    if start_date is not None:
        ET.SubElement(root, f"{{{MSP_NS}}}StartDate").text = start_date

    finish_date = _dt_to_msp_text(project.finish_date)
    if finish_date is not None:
        ET.SubElement(root, f"{{{MSP_NS}}}FinishDate").text = finish_date

    ET.SubElement(root, f"{{{MSP_NS}}}MinutesPerDay").text = str(project.minutes_per_day)
    ET.SubElement(root, f"{{{MSP_NS}}}MinutesPerWeek").text = str(project.minutes_per_week)
    ET.SubElement(root, f"{{{MSP_NS}}}DaysPerMonth").text = str(project.days_per_month)

    if project.currency_code is not None:
        ET.SubElement(root, f"{{{MSP_NS}}}CurrencyCode").text = project.currency_code

    tasks_node = ET.SubElement(root, f"{{{MSP_NS}}}Tasks")
    for task in tasks:
        task_node = ET.SubElement(tasks_node, f"{{{MSP_NS}}}Task")
        ET.SubElement(task_node, f"{{{MSP_NS}}}UID").text = str(task.uid)

        if task.id_display is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}ID").text = str(task.id_display)

        ET.SubElement(task_node, f"{{{MSP_NS}}}Name").text = task.name

        if task.task_type is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}Type").text = str(task.task_type)

        if task.outline_number is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}OutlineNumber").text = task.outline_number

        if task.outline_level is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}OutlineLevel").text = str(task.outline_level)

        start_at = _dt_to_msp_text(task.start_at)
        if start_at is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}Start").text = start_at

        finish_at = _dt_to_msp_text(task.finish_at)
        if finish_at is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}Finish").text = finish_at

        if task.percent_complete is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}PercentComplete").text = str(
                task.percent_complete
            )

        ET.SubElement(task_node, f"{{{MSP_NS}}}Summary").text = _bool_to_msp_flag(task.is_summary)
        ET.SubElement(task_node, f"{{{MSP_NS}}}Milestone").text = _bool_to_msp_flag(
            task.is_milestone
        )

        description = descriptions_by_uid.get(task.uid)
        if description:
            ET.SubElement(task_node, f"{{{MSP_NS}}}Notes").text = description

        for link in links_by_task_uid.get(task.uid, []):
            predecessor_link_node = ET.SubElement(task_node, f"{{{MSP_NS}}}PredecessorLink")
            ET.SubElement(predecessor_link_node, f"{{{MSP_NS}}}PredecessorUID").text = str(
                link.predecessor_uid
            )
            ET.SubElement(predecessor_link_node, f"{{{MSP_NS}}}Type").text = str(link.link_type)
            if link.lag_tenth_minute is not None:
                ET.SubElement(predecessor_link_node, f"{{{MSP_NS}}}LinkLag").text = str(
                    link.lag_tenth_minute
                )
            if link.lag_format is not None:
                ET.SubElement(predecessor_link_node, f"{{{MSP_NS}}}LagFormat").text = str(
                    link.lag_format
                )

    xml_content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(content=xml_content, media_type="application/xml")
