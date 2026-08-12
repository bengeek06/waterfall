from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_user
from waterfall.db.session import get_db
from waterfall.models.ms_core import MsTask, MsTaskLink
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


def _get_batch_or_404(db: Session, batch_id: int) -> WfImportBatch:
    batch = db.query(WfImportBatch).filter(WfImportBatch.id == batch_id).first()
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
    _: User = Depends(get_current_user),
) -> ImportBatchResponse:
    now = datetime.now(UTC)
    source_name = payload.source_name or "pending.xml"

    batch = WfImportBatch(
        project_id=None,
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
    _: User = Depends(get_current_user),
) -> ImportBatchResponse:
    filename = file.filename or "upload.xml"
    if not filename.lower().endswith(".xml"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .xml files are accepted",
        )

    batch = _get_batch_or_404(db, batch_id)
    content = await file.read()
    source_sha256 = hashlib.sha256(content).hexdigest()
    batch.source_filename = filename
    batch.source_sha256 = source_sha256
    batch.status = "pending"
    batch.log_json = json.dumps({"uploaded_bytes": len(content)})
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
    __: User = Depends(get_current_user),
) -> ImportRunAcceptedResponse:
    batch = _get_batch_or_404(db, batch_id)
    if batch.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Batch is already running")

    accepted_at = datetime.now(UTC)
    batch.status = "running"
    batch.started_at = accepted_at
    batch.finished_at = None
    db.add(batch)
    db.commit()
    db.refresh(batch)

    return ImportRunAcceptedResponse(
        batchId=batch.id,
        status=cast(BatchStatus, batch.status),
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
    _: User = Depends(get_current_user),
) -> ImportBatchStatusResponse:
    batch = _get_batch_or_404(db, batch_id)
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
    _: User = Depends(get_current_user),
) -> ImportErrorListResponse:
    batch = _get_batch_or_404(db, batch_id)
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
