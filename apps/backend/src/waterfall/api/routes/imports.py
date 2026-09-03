from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user
from waterfall.api.routes.project_access import get_mutable_project_lock
from waterfall.core.config import get_settings
from waterfall.db.session import get_db
from waterfall.models.ms_core import MsProject
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
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
from waterfall.services.msproject_xml import (
    MsProjectValidationError,
    ParsedProject,
    parse_msproject_xml,
)
from waterfall.services.project_lifecycle import ensure_project_mutable

router = APIRouter(prefix="/imports/v1/batches", tags=["imports-v1"])
UPLOAD_CHUNK_SIZE = 1024 * 1024


def _source_path(batch_id: int) -> Path:
    return Path(get_settings().import_storage_path) / f"batch-{batch_id}.xml"


async def _stage_source_xml(file: UploadFile, batch_id: int) -> tuple[Path, int, str]:
    settings = get_settings()
    final_path = _source_path(batch_id)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    # Unique staging name so concurrent uploads never write to the same file.
    staging_path = final_path.with_name(f"{final_path.name}.{uuid4().hex}.part")

    byte_count = 0
    digest = hashlib.sha256()
    try:
        with staging_path.open("wb") as destination:
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
        staging_path.unlink(missing_ok=True)
        raise

    return staging_path, byte_count, digest.hexdigest()


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


def _parse_issue_list(raw_items: object) -> list[ImportIssue]:
    if not isinstance(raw_items, list):
        return []
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
    return items


def _planning_counters(db: Session, planning_id: int) -> tuple[int, int]:
    task_count = (
        db.scalar(
            select(func.count())
            .select_from(WfPlanningTaskSnapshot)
            .where(WfPlanningTaskSnapshot.planning_id == planning_id)
        )
        or 0
    )
    link_count = (
        db.scalar(
            select(func.count())
            .select_from(WfPlanningLinkSnapshot)
            .where(WfPlanningLinkSnapshot.planning_id == planning_id)
        )
        or 0
    )
    return task_count, link_count


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
    ensure_project_mutable(project)

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
    if batch.project_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    # Stage the upload before locking so slow file I/O never blocks planning
    # writers serialized on the project row lock.
    staging_path, byte_count, source_sha256 = await _stage_source_xml(file, batch.id)
    final_path = _source_path(batch.id)
    try:
        get_mutable_project_lock(db, batch.project_id, current_user.id)
        db.refresh(batch)
        if batch.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Batch is no longer pending",
            )
        os.replace(staging_path, final_path)
    except BaseException:
        staging_path.unlink(missing_ok=True)
        raise

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
    batch.source_storage_path = str(final_path)
    batch.source_sha256 = source_sha256
    batch.status = "pending"
    batch.log_json = json.dumps(log_payload)
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return _to_batch_response(batch)


def _validate_run_request(batch: WfImportBatch, run_request: ImportRunRequest) -> dict[str, Any]:
    # Unlocked fast path: reject a batch that is already running/finished before
    # spending any time on file I/O or XML parsing. The authoritative recheck
    # under the project lock in `_relock_pending_batch` still guards races.
    if batch.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Batch is not pending")
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
        stored_payload = json.loads(batch.log_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Corrupted batch payload",
        ) from exc
    if not isinstance(stored_payload, dict):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Corrupted batch payload")
    return stored_payload


def _relock_pending_batch(
    db: Session,
    batch: WfImportBatch,
    project_id: int,
    owner_id: int,
    expected_sha256: str | None,
) -> MsProject:
    project = get_mutable_project_lock(db, project_id, owner_id)
    # Re-read under the project lock: a concurrent writer may have finished the
    # batch, or replaced its uploaded XML, while it was read/parsed unlocked.
    db.refresh(batch)
    if batch.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Batch is not pending")
    if batch.source_sha256 != expected_sha256:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Uploaded XML changed concurrently; re-run the batch",
        )
    return project


def _run_dry_validation(
    db: Session,
    batch: WfImportBatch,
    project_id: int,
    owner_id: int,
    expected_sha256: str | None,
    xml_bytes: bytes,
    accepted_at: datetime,
) -> ImportRunAcceptedResponse:
    validation_error: MsProjectValidationError | None = None
    try:
        parse_msproject_xml(xml_bytes)
    except MsProjectValidationError as exc:
        validation_error = exc

    _relock_pending_batch(db, batch, project_id, owner_id, expected_sha256)

    if validation_error is not None:
        batch.log_json = json.dumps(
            {"error": str(validation_error), "errors": validation_error.issues}
        )
        db.add(batch)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Import validation failed",
        ) from validation_error

    return ImportRunAcceptedResponse(batchId=batch.id, status="pending", acceptedAt=accepted_at)


def _reject_diff_conflicts(
    db: Session, project: MsProject, parsed_project: ParsedProject | None
) -> None:
    # Reject referenced tasks that the diff preview flagged as conflicts before
    # mutating any state, keeping the batch reusable (still pending).
    if parsed_project is None:
        return
    conflicting_uids = [
        item["uid"]
        for item in build_import_diff(db, project, parsed_project)
        if item.get("kind") == "conflict"
    ]
    if conflicting_uids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "IMPORT_CONFLICT", "conflicts": conflicting_uids},
        )


def _mark_batch_running(db: Session, batch: WfImportBatch, accepted_at: datetime) -> None:
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


def _mark_batch_failed(
    db: Session, batch_id: int, owner_id: int, error: str, issues: list[dict[str, Any]]
) -> None:
    failed_batch = _get_batch_or_404(db, batch_id, owner_id)
    failed_batch.status = "failed"
    failed_batch.finished_at = datetime.now(UTC)
    failed_batch.log_json = json.dumps({"error": error, "errors": issues})
    db.add(failed_batch)
    db.commit()


def _apply_confirmed_import(
    db: Session,
    batch: WfImportBatch,
    batch_id: int,
    project_id: int,
    owner_id: int,
    xml_bytes: bytes,
    parsed_project: ParsedProject | None,
    parse_error: MsProjectValidationError | None,
    stored_payload: dict[str, Any],
) -> None:
    try:
        # The status commit above released the project row lock; re-acquire it
        # immediately before mutating snapshots so a concurrent writer cannot
        # change displayed_planning_id/status between the two transactions.
        project = get_mutable_project_lock(db, project_id, owner_id)
        if parse_error is not None:
            # Already parsed unlocked; re-raise instead of letting
            # import_tasks_and_links parse the same invalid XML again.
            raise parse_error
        identical_source = (
            db.query(WfImportBatch.id)
            .filter(WfImportBatch.project_id == project_id)
            .filter(WfImportBatch.status == "success")
            .filter(WfImportBatch.source_sha256 == batch.source_sha256)
            .filter(WfImportBatch.id != batch.id)
            .first()
            is not None
        )
        task_count, link_count, import_warnings = import_tasks_and_links(
            db, xml_bytes, project, parsed_project
        )
        batch.status = "success"
        batch.finished_at = datetime.now(UTC)
        stored_payload["counters"] = {"tasks": task_count, "links": link_count}
        stored_payload["errors"] = []
        stored_payload["warnings"] = list(import_warnings)
        stored_payload["dry_run"] = False
        if identical_source:
            stored_payload["identical_source"] = True
        batch.log_json = json.dumps(stored_payload)
        db.add(batch)
        db.commit()
    except HTTPException as exc:
        # Preserve the precise status/detail (e.g. project became read-only
        # concurrently) instead of masking it as a generic import failure.
        db.rollback()
        _mark_batch_failed(
            db,
            batch_id,
            owner_id,
            str(exc.detail),
            [{"code": "IMPORT_FAILED", "message": str(exc.detail)}],
        )
        raise
    except Exception as exc:
        db.rollback()
        issues = (
            exc.issues
            if isinstance(exc, MsProjectValidationError)
            else [{"code": "IMPORT_FAILED", "message": str(exc)}]
        )
        _mark_batch_failed(db, batch_id, owner_id, str(exc), issues)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Import failed",
        ) from exc


def _run_confirmed_import(
    db: Session,
    batch: WfImportBatch,
    batch_id: int,
    project_id: int,
    owner_id: int,
    expected_sha256: str | None,
    xml_bytes: bytes,
    parsed_project: ParsedProject | None,
    parse_error: MsProjectValidationError | None,
    stored_payload: dict[str, Any],
    accepted_at: datetime,
) -> ImportRunAcceptedResponse:
    project = _relock_pending_batch(db, batch, project_id, owner_id, expected_sha256)
    _reject_diff_conflicts(db, project, parsed_project)
    _mark_batch_running(db, batch, accepted_at)
    _apply_confirmed_import(
        db,
        batch,
        batch_id,
        project_id,
        owner_id,
        xml_bytes,
        parsed_project,
        parse_error,
        stored_payload,
    )

    return ImportRunAcceptedResponse(batchId=batch.id, status="success", acceptedAt=accepted_at)


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
    payload: ImportRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ImportRunAcceptedResponse:
    batch = _get_batch_or_404(db, batch_id, current_user.id)
    if batch.project_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    stored_payload = _validate_run_request(batch, payload)
    project_id = batch.project_id
    expected_sha256 = batch.source_sha256

    # Read and parse the uploaded XML before acquiring the project lock so slow
    # file I/O and XML parsing never block other writers serialized on it.
    xml_bytes = _read_source_xml(batch)
    accepted_at = datetime.now(UTC)

    if payload.dry_run:
        return _run_dry_validation(
            db, batch, project_id, current_user.id, expected_sha256, xml_bytes, accepted_at
        )

    # Parse once, unlocked, and reuse the result for both conflict detection and
    # the import itself so neither re-parses while holding the project lock.
    parse_error: MsProjectValidationError | None = None
    try:
        parsed_project = parse_msproject_xml(xml_bytes)
    except MsProjectValidationError as exc:
        parsed_project = None
        parse_error = exc

    return _run_confirmed_import(
        db,
        batch,
        batch_id,
        project_id,
        current_user.id,
        expected_sha256,
        xml_bytes,
        parsed_project,
        parse_error,
        stored_payload,
        accepted_at,
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

    saved_counters = log_payload.get("counters")
    if isinstance(saved_counters, dict):
        task_value = saved_counters.get("tasks")
        link_value = saved_counters.get("links")
        task_count = task_value if isinstance(task_value, int) else 0
        link_count = link_value if isinstance(link_value, int) else 0
    elif batch.status == "success" and batch.project_id is not None:
        planning = (
            db.query(WfPlanning)
            .join(MsProject, WfPlanning.project_id == MsProject.id)
            .filter(WfPlanning.project_id == batch.project_id)
            .filter(WfPlanning.id == MsProject.displayed_planning_id)
            .one_or_none()
        )
        if planning is not None:
            task_count, link_count = _planning_counters(db, planning.id)

    return ImportBatchStatusResponse(
        **batch_response.model_dump(by_alias=True),
        projectId=batch.project_id,
        counters=ImportCounters(tasks=task_count, links=link_count),
        warnings=_parse_issue_list(log_payload.get("warnings")),
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

    log_payload: dict[str, object] = {}
    try:
        loaded_payload = json.loads(batch.log_json)
        if isinstance(loaded_payload, dict):
            log_payload = loaded_payload
    except json.JSONDecodeError:
        return ImportErrorListResponse(items=[])

    return ImportErrorListResponse(items=_parse_issue_list(log_payload.get("errors")))
