from __future__ import annotations

import base64
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user
from waterfall.db.session import get_db
from waterfall.models.ms_core import MsProject, MsTask, MsTaskLink
from waterfall.models.user import User
from waterfall.models.wf_core import WfImportBatch
from waterfall.schemas.imports import (
    BatchStatus,
    ErrorResponse,
    ImportBatchCreateRequest,
    ImportBatchResponse,
    ImportBatchStatusResponse,
    ImportCounters,
    ImportErrorListResponse,
    ImportIssue,
    ImportMode,
    ImportRunAcceptedResponse,
    ImportRunRequest,
)

router = APIRouter(prefix="/imports/v1/batches", tags=["imports-v1"])
NS = {"ms": "http://schemas.microsoft.com/project"}


def _txt(node: ET.Element, path: str) -> str | None:
    found = node.find(path, NS)
    if found is None or found.text is None:
        return None
    value = found.text.strip()
    return value if value != "" else None


def _as_int(value: str | None) -> int | None:
    return int(value) if value is not None else None


def _as_bool(value: str | None) -> bool:
    return value == "1"


def _as_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _import_v1_tasks_and_links(
    db: Session,
    xml_bytes: bytes,
    project: MsProject,
) -> tuple[int, int]:
    root = ET.fromstring(xml_bytes)

    save_version = _as_int(_txt(root, "ms:SaveVersion")) or 16
    source_version_map = {14: 2010, 15: 2013, 16: 2016}
    source_version = source_version_map.get(save_version, 2016)

    if db.query(MsTask.id).filter(MsTask.project_id == project.id).first() is not None:
        raise ValueError("Project already contains tasks")

    project.external_uid = _txt(root, "ms:GUID")
    project.source_version = source_version
    project.save_version_out = save_version if save_version in (14, 15, 16) else 16
    project.schedule_from_start = _as_bool(_txt(root, "ms:ScheduleFromStart"))
    project.start_date = _as_dt(_txt(root, "ms:StartDate"))
    project.finish_date = _as_dt(_txt(root, "ms:FinishDate"))
    project.calendar_uid = _as_int(_txt(root, "ms:CalendarUID"))
    project.minutes_per_day = _as_int(_txt(root, "ms:MinutesPerDay")) or 480
    project.minutes_per_week = _as_int(_txt(root, "ms:MinutesPerWeek")) or 2400
    project.days_per_month = _as_int(_txt(root, "ms:DaysPerMonth")) or 20
    project.currency_code = _txt(root, "ms:CurrencyCode")
    db.add(project)
    db.flush()

    tasks: list[MsTask] = []
    links: list[MsTaskLink] = []

    for task_node in root.findall("ms:Tasks/ms:Task", NS):
        uid = _as_int(_txt(task_node, "ms:UID"))
        if uid is None:
            continue

        tasks.append(
            MsTask(
                project_id=project.id,
                uid=uid,
                id_display=_as_int(_txt(task_node, "ms:ID")),
                name=_txt(task_node, "ms:Name") or f"Task {uid}",
                task_type=_as_int(_txt(task_node, "ms:Type")),
                outline_number=_txt(task_node, "ms:OutlineNumber"),
                outline_level=_as_int(_txt(task_node, "ms:OutlineLevel")),
                wbs=_txt(task_node, "ms:WBS"),
                start_at=_as_dt(_txt(task_node, "ms:Start")),
                finish_at=_as_dt(_txt(task_node, "ms:Finish")),
                duration_format=_as_int(_txt(task_node, "ms:DurationFormat")),
                percent_complete=_as_int(_txt(task_node, "ms:PercentComplete")),
                is_summary=_as_bool(_txt(task_node, "ms:Summary")),
                is_milestone=_as_bool(_txt(task_node, "ms:Milestone")),
                calendar_uid=_as_int(_txt(task_node, "ms:CalendarUID")),
            )
        )

        for pred_node in task_node.findall("ms:PredecessorLink", NS):
            predecessor_uid = _as_int(_txt(pred_node, "ms:PredecessorUID"))
            if predecessor_uid is None:
                continue

            links.append(
                MsTaskLink(
                    project_id=project.id,
                    task_uid=uid,
                    predecessor_uid=predecessor_uid,
                    link_type=_as_int(_txt(pred_node, "ms:Type")) or 1,
                    lag_tenth_minute=_as_int(_txt(pred_node, "ms:LinkLag")),
                    lag_format=_as_int(_txt(pred_node, "ms:LagFormat")),
                )
            )

    db.add_all(tasks)
    db.flush()
    db.add_all(links)
    db.flush()

    return len(tasks), len(links)


def _to_batch_response(batch: WfImportBatch) -> ImportBatchResponse:
    error_message: str | None = None
    if batch.log_json:
        try:
            log_payload = json.loads(batch.log_json)
            if isinstance(log_payload, dict):
                error_value = log_payload.get("error")
                if isinstance(error_value, str):
                    error_message = error_value
        except json.JSONDecodeError:
            error_message = None

    return ImportBatchResponse(
        id=batch.id,
        importMode=cast(ImportMode, batch.import_mode),
        status=cast(BatchStatus, batch.status),
        sourceName=batch.source_filename,
        startedAt=batch.started_at,
        endedAt=batch.finished_at,
        errorMessage=error_message,
        createdAt=batch.started_at,
        updatedAt=batch.finished_at or batch.started_at,
    )


def _get_batch_or_404(db: Session, batch_id: int, owner_id: int) -> WfImportBatch:
    batch = (
        db.query(WfImportBatch)
        .join(MsProject, WfImportBatch.project_id == MsProject.id)
        .filter(WfImportBatch.id == batch_id)
        .filter(MsProject.owner_id == owner_id)
        .first()
    )
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    return batch


@router.post(
    "",
    response_model=ImportBatchResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
def create_batch(
    payload: ImportBatchCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ImportBatchResponse:
    now = datetime.now(UTC)
    source_name = payload.source_name or "pending.xml"

    project = (
        db.query(MsProject)
        .filter(MsProject.id == payload.project_id)
        .filter(MsProject.owner_id == current_user.id)
        .first()
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    batch = WfImportBatch(
        project_id=project.id,
        import_mode=payload.import_mode,
        source_filename=source_name,
        source_sha256=None,
        started_at=now,
        finished_at=None,
        status="pending",
        log_json=None,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return _to_batch_response(batch)


@router.post(
    "/{batch_id}/xml",
    response_model=ImportBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def upload_xml(
    batch_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ImportBatchResponse:
    filename = file.filename or "upload.xml"
    if not filename.lower().endswith(".xml"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .xml files are accepted",
        )

    batch = _get_batch_or_404(db, batch_id, current_user.id)
    content = await file.read()
    source_sha256 = hashlib.sha256(content).hexdigest()

    log_payload: dict[str, object]
    if batch.log_json:
        try:
            loaded = json.loads(batch.log_json)
            log_payload = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            log_payload = {}
    else:
        log_payload = {}

    log_payload["uploaded_bytes"] = len(content)
    log_payload["xml_b64"] = base64.b64encode(content).decode("ascii")

    batch.source_filename = filename
    batch.source_sha256 = source_sha256
    batch.status = "pending"
    batch.log_json = json.dumps(log_payload)
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return _to_batch_response(batch)


@router.post(
    "/{batch_id}/run",
    response_model=ImportRunAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def run_batch(
    batch_id: int,
    _: ImportRunRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ImportRunAcceptedResponse:
    batch = _get_batch_or_404(db, batch_id, current_user.id)
    if batch.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Batch is already running")

    if not batch.log_json:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No XML uploaded for this batch",
        )

    try:
        payload = json.loads(batch.log_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Corrupted batch payload",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Corrupted batch payload")

    xml_b64 = payload.get("xml_b64")
    if not isinstance(xml_b64, str):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No XML uploaded for this batch",
        )

    try:
        xml_bytes = base64.b64decode(xml_b64)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Corrupted XML payload",
        ) from exc

    accepted_at = datetime.now(UTC)
    batch.status = "running"
    batch.started_at = accepted_at
    batch.finished_at = None
    db.add(batch)
    db.commit()
    db.refresh(batch)

    try:
        project = db.query(MsProject).filter(MsProject.id == batch.project_id).one()
        task_count, link_count = _import_v1_tasks_and_links(
            db,
            xml_bytes,
            project,
        )
        batch.status = "success"
        batch.finished_at = datetime.now(UTC)
        payload["counters"] = {"tasks": task_count, "links": link_count}
        payload["errors"] = []
        batch.log_json = json.dumps(payload)
        db.add(batch)
        db.commit()
    except Exception as exc:
        db.rollback()
        failed_batch = _get_batch_or_404(db, batch_id, current_user.id)
        failed_batch.status = "failed"
        failed_batch.finished_at = datetime.now(UTC)
        failed_batch.log_json = json.dumps(
            {
                "error": str(exc),
                "errors": [{"code": "IMPORT_FAILED", "message": str(exc)}],
            }
        )
        db.add(failed_batch)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Import failed",
        ) from exc

    return ImportRunAcceptedResponse(
        batchId=batch.id,
        status="running",
        acceptedAt=accepted_at,
    )


@router.get(
    "/{batch_id}",
    response_model=ImportBatchStatusResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ImportBatchStatusResponse:
    batch = _get_batch_or_404(db, batch_id, current_user.id)
    batch_response = _to_batch_response(batch)

    task_count = 0
    link_count = 0
    if batch.project_id is not None:
        task_count = (
            db.scalar(
                select(func.count())
                .select_from(MsTask)
                .where(MsTask.project_id == batch.project_id)
            )
            or 0
        )
        link_count = (
            db.scalar(
                select(func.count())
                .select_from(MsTaskLink)
                .where(MsTaskLink.project_id == batch.project_id)
            )
            or 0
        )

    return ImportBatchStatusResponse(
        **batch_response.model_dump(by_alias=True),
        projectId=batch.project_id,
        counters=ImportCounters(tasks=task_count, links=link_count),
        warnings=[],
    )


@router.get(
    "/{batch_id}/errors",
    response_model=ImportErrorListResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def list_batch_errors(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ImportErrorListResponse:
    batch = _get_batch_or_404(db, batch_id, current_user.id)
    if not batch.log_json:
        return ImportErrorListResponse(items=[])

    try:
        payload = json.loads(batch.log_json)
    except json.JSONDecodeError:
        return ImportErrorListResponse(items=[])

    raw_items = payload.get("errors") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        return ImportErrorListResponse(items=[])

    items: list[ImportIssue] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        message = item.get("message")
        if isinstance(code, str) and isinstance(message, str):
            task_uid = item.get("taskUid")
            predecessor_uid = item.get("predecessorUid")
            items.append(
                ImportIssue(
                    code=code,
                    message=message,
                    taskUid=task_uid if isinstance(task_uid, int) else None,
                    predecessorUid=predecessor_uid if isinstance(predecessor_uid, int) else None,
                )
            )
    return ImportErrorListResponse(items=items)
