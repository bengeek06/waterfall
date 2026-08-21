from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user
from waterfall.core.config import get_settings
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
    ImportDiffItem,
    ImportDiffResponse,
    ImportErrorListResponse,
    ImportIssue,
    ImportMode,
    ImportRunAcceptedResponse,
    ImportRunRequest,
)
from waterfall.services.import_diff import build_import_diff
from waterfall.services.import_v1 import import_tasks_and_links
from waterfall.services.msproject_xml import MsProjectValidationError, parse_msproject_xml

router = APIRouter(prefix="/imports/v1/batches", tags=["imports-v1"])
UPLOAD_CHUNK_SIZE = 1024 * 1024


def _source_path(batch_id: int) -> Path:
    return Path(get_settings().import_storage_path) / f"batch-{batch_id}.xml"


async def _save_source_xml(file: UploadFile, batch_id: int) -> tuple[Path, int, str]:
    settings = get_settings()
    storage_path = _source_path(batch_id)
    storage_path.parent.mkdir(parents=True, exist_ok=True)

    byte_count = 0
    digest = hashlib.sha256()
    try:
        with storage_path.open("wb") as destination:
            while chunk := await file.read(UPLOAD_CHUNK_SIZE):
                byte_count += len(chunk)
                if byte_count > settings.import_max_upload_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="XML file exceeds the configured size limit",
                    )
                digest.update(chunk)
                destination.write(chunk)
    except Exception:
        storage_path.unlink(missing_ok=True)
        raise

    return storage_path, byte_count, digest.hexdigest()


def _read_source_xml(batch: WfImportBatch) -> bytes:
    if not batch.source_storage_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No XML uploaded for this batch",
        )

    source_path = Path(batch.source_storage_path)
    if not source_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Uploaded XML is unavailable",
        )
    return source_path.read_bytes()


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
    if batch.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Batch is no longer pending",
        )
    storage_path, byte_count, source_sha256 = await _save_source_xml(file, batch.id)

    log_payload: dict[str, object]
    if batch.log_json:
        try:
            loaded = json.loads(batch.log_json)
            log_payload = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            log_payload = {}
    else:
        log_payload = {}

    log_payload["uploaded_bytes"] = byte_count

    batch.source_filename = filename
    batch.source_storage_path = str(storage_path)
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
    payload: ImportRunRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ImportRunAcceptedResponse:
    batch = _get_batch_or_404(db, batch_id, current_user.id)
    if batch.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Batch is not pending")

    run_request = payload or ImportRunRequest()
    if not run_request.dry_run and not run_request.confirm:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Import requires explicit confirmation",
        )

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

    xml_bytes = _read_source_xml(batch)

    accepted_at = datetime.now(UTC)
    if run_request.dry_run:
        try:
            parse_msproject_xml(xml_bytes)
        except MsProjectValidationError as exc:
            batch.log_json = json.dumps({"error": str(exc), "errors": exc.issues})
            db.add(batch)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Import validation failed",
            ) from exc
        return ImportRunAcceptedResponse(
            batchId=batch.id,
            status="pending",
            acceptedAt=accepted_at,
        )

    updated = (
        db.query(WfImportBatch)
        .filter(WfImportBatch.id == batch.id)
        .filter(WfImportBatch.status == "pending")
        .update(
            {
                WfImportBatch.status: "running",
                WfImportBatch.started_at: accepted_at,
                WfImportBatch.finished_at: None,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    if updated != 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Batch is not pending")
    db.refresh(batch)

    try:
        project = (
            db.query(MsProject).filter(MsProject.id == batch.project_id).with_for_update().one()
        )
        identical_source = (
            db.query(WfImportBatch.id)
            .filter(WfImportBatch.project_id == batch.project_id)
            .filter(WfImportBatch.status == "success")
            .filter(WfImportBatch.source_sha256 == batch.source_sha256)
            .filter(WfImportBatch.id != batch.id)
            .first()
            is not None
        )
        if identical_source:
            task_count = db.query(MsTask.id).filter(MsTask.project_id == project.id).count()
            link_count = db.query(MsTaskLink.id).filter(MsTaskLink.project_id == project.id).count()
            batch.status = "success"
            batch.finished_at = datetime.now(UTC)
            payload["counters"] = {"tasks": task_count, "links": link_count}
            payload["errors"] = []
            payload["dry_run"] = run_request.dry_run
            payload["identical_source"] = True
            batch.log_json = json.dumps(payload)
            db.add(batch)
            db.commit()
            return ImportRunAcceptedResponse(
                batchId=batch.id,
                status="success",
                acceptedAt=accepted_at,
            )
        task_count, link_count = import_tasks_and_links(db, xml_bytes, project)
        batch.status = "success"
        batch.finished_at = datetime.now(UTC)
        payload["counters"] = {"tasks": task_count, "links": link_count}
        payload["errors"] = []
        payload["dry_run"] = False
        batch.log_json = json.dumps(payload)
        db.add(batch)
        db.commit()
    except Exception as exc:
        db.rollback()
        failed_batch = _get_batch_or_404(db, batch_id, current_user.id)
        failed_batch.status = "failed"
        failed_batch.finished_at = datetime.now(UTC)
        issues = (
            exc.issues
            if isinstance(exc, MsProjectValidationError)
            else [{"code": "IMPORT_FAILED", "message": str(exc)}]
        )
        failed_batch.log_json = json.dumps({"error": str(exc), "errors": issues})
        db.add(failed_batch)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Import failed",
        ) from exc

    return ImportRunAcceptedResponse(
        batchId=batch.id,
        status="success",
        acceptedAt=accepted_at,
    )


@router.get("/{batch_id}/diff", response_model=ImportDiffResponse)
def get_batch_diff(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ImportDiffResponse:
    batch = _get_batch_or_404(db, batch_id, current_user.id)
    xml_bytes = _read_source_xml(batch)
    try:
        parsed = parse_msproject_xml(xml_bytes)
    except MsProjectValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "IMPORT_VALIDATION_FAILED", "issues": exc.issues},
        ) from exc
    project = db.query(MsProject).filter(MsProject.id == batch.project_id).one()
    previous = (
        db.query(WfImportBatch)
        .filter(WfImportBatch.project_id == batch.project_id)
        .filter(WfImportBatch.status == "success")
        .filter(WfImportBatch.source_sha256 == batch.source_sha256)
        .filter(WfImportBatch.id != batch.id)
        .first()
    )
    items = [
        ImportDiffItem(**cast(dict[str, Any], item))
        for item in build_import_diff(db, project, parsed)
    ]
    return ImportDiffResponse(
        batchId=batch.id,
        sourceSha256=batch.source_sha256,
        identicalSource=previous is not None,
        items=items,
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
    log_payload: dict[str, object] = {}
    if batch.log_json:
        try:
            loaded_payload = json.loads(batch.log_json)
            if isinstance(loaded_payload, dict):
                log_payload = loaded_payload
        except json.JSONDecodeError:
            pass

    is_dry_run = log_payload.get("dry_run") is True
    saved_counters = log_payload.get("counters")
    if is_dry_run and isinstance(saved_counters, dict):
        task_value = saved_counters.get("tasks")
        link_value = saved_counters.get("links")
        task_count = task_value if isinstance(task_value, int) else 0
        link_count = link_value if isinstance(link_value, int) else 0
    elif batch.project_id is not None:
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
