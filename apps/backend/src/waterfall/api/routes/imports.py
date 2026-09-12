from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, NoReturn, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from waterfall.api.dependencies import get_current_active_user
from waterfall.api.revision_errors import revision_operation
from waterfall.api.routes.project_access import get_mutable_project_lock
from waterfall.core.config import get_settings
from waterfall.core.object_storage import (
    ObjectStorageKeyNotFoundError,
    ObjectStorageUnavailableError,
    import_object_storage,
)
from waterfall.db.session import get_db
from waterfall.domain import revision as domain
from waterfall.models.ms_core import MsProject
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.models.user import User
from waterfall.models.wf_core import WfImportBatch
from waterfall.schemas.imports import (
    BatchStatus,
    ImportBatchCreateRequest,
    ImportBatchResponse,
    ImportBatchStatusResponse,
    ImportCostLoss,
    ImportCounters,
    ImportDiffItem,
    ImportDiffResponse,
    ImportErrorListResponse,
    ImportIssue,
    ImportMode,
    ImportRunAcceptedResponse,
    ImportRunRequest,
)
from waterfall.schemas.projects import FastAPIErrorResponse
from waterfall.services import revision_import
from waterfall.services.import_diff import build_import_diff
from waterfall.services.msproject_xml import (
    MsProjectValidationError,
    ParsedProject,
    parse_msproject_xml,
)
from waterfall.services.msproject_xml_import import import_tasks_and_links
from waterfall.services.project_lifecycle import ensure_project_mutable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/imports/v1/batches", tags=["imports-v1"])
UPLOAD_CHUNK_SIZE = 1024 * 1024
# Above this, the staging buffer spills from RAM to a temporary file. Keeps a handful of
# concurrent uploads of typical MS Project exports entirely in memory while still bounding
# what a single request can hold, whatever import_max_upload_bytes allows. Only holds
# because ObjectStorage.upload issues a single PUT straight from this buffer: s3transfer's
# multipart path would have copied every part back into RAM above 8 MiB.
UPLOAD_SPOOL_MAX_MEMORY_BYTES = 4 * 1024 * 1024
# Object keys, not filesystem paths: `source_storage_path` now names an object inside the
# Garage bucket (see core/object_storage.py).
_SOURCE_KEY_PREFIX = "imports/"
_STAGING_KEY_PREFIX = f"{_SOURCE_KEY_PREFIX}staging/"


def _source_key(batch_id: int) -> str:
    return f"{_SOURCE_KEY_PREFIX}batch-{batch_id}.xml"


def _staging_key(batch_id: int) -> str:
    # Unique per upload so two concurrent uploads for the same batch never write to the
    # same object before the final, lock-protected switchover.
    return f"{_STAGING_KEY_PREFIX}batch-{batch_id}.{uuid4().hex}.part"


def _storage_unavailable(exc: Exception) -> HTTPException:
    # The client only ever sees a generic 503 (main.py rewrites string details into
    # {"code": "GENERIC_ERROR"}), so this log line is the only thing that lets an operator
    # tell an unreachable endpoint from a missing bucket, a SignatureDoesNotMatch or an
    # AccessDenied. Same reasoning as the fail-closed login rate limiter (E13-01): carry
    # the underlying cause and its traceback, never the credentials.
    logger.error(
        "imports.object_storage_unavailable",
        extra={"error": str(exc.__cause__ or exc)},
        exc_info=exc,
    )
    # 503, like that rate limiter: the request failed because a backing service is down,
    # not because the caller or the batch is in a bad state, and retrying the exact same
    # call once storage is back is the right move.
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Import object storage is unavailable",
    )


async def _stage_source_xml(file: UploadFile, batch_id: int) -> tuple[str, int, str]:
    """Buffer the upload, hash it, and put it in the bucket under a staging key.

    Runs before the project lock is taken (see upload_xml), so neither the network
    round trip nor the hashing ever blocks writers serialized on that lock.
    """
    settings = get_settings()
    staging_key = _staging_key(batch_id)

    byte_count = 0
    digest = hashlib.sha256()
    # Spooled rather than a plain BytesIO: the size limit below is enforced *while*
    # reading, so an oversized upload is rejected mid-stream, but a file just under the
    # limit would still be a large in-memory blob. The spool caps resident memory and
    # deletes whatever it spilled to disk when the block exits, on success or failure --
    # nothing persistent, no volume.
    with tempfile.SpooledTemporaryFile(max_size=UPLOAD_SPOOL_MAX_MEMORY_BYTES) as buffer:
        while chunk := await file.read(UPLOAD_CHUNK_SIZE):
            byte_count += len(chunk)
            if byte_count > settings.import_max_upload_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="XML file exceeds the configured size limit",
                )
            digest.update(chunk)
            buffer.write(chunk)
        buffer.seek(0)
        try:
            # boto3 is synchronous: called inline it would block the event loop for as
            # long as the store takes to answer (up to connect+read timeouts x retries),
            # freezing every other request in the process, /health and /metrics included.
            await run_in_threadpool(import_object_storage.upload, staging_key, buffer)
        except ObjectStorageUnavailableError as exc:
            raise _storage_unavailable(exc) from exc

    return staging_key, byte_count, digest.hexdigest()


def _discard_staged_object(staging_key: str) -> None:
    """Best-effort staging cleanup; never turns a successful upload into a failure.

    A leftover staging object is unreachable garbage (its key is never stored), so
    failing the request over it would trade a harmless leak for a lost import.
    """
    with contextlib.suppress(ObjectStorageUnavailableError):
        import_object_storage.delete(staging_key)


def _read_source_xml(batch: WfImportBatch) -> bytes:
    if not batch.source_storage_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No XML uploaded for this batch",
        )

    try:
        return import_object_storage.download(batch.source_storage_path)
    except ObjectStorageKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Uploaded XML is unavailable",
        ) from exc
    except ObjectStorageUnavailableError as exc:
        raise _storage_unavailable(exc) from exc


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
    responses={400: {"model": FastAPIErrorResponse}, 401: {"model": FastAPIErrorResponse}},
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
        400: {"model": FastAPIErrorResponse},
        401: {"model": FastAPIErrorResponse},
        404: {"model": FastAPIErrorResponse},
        503: {"model": FastAPIErrorResponse},
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
    # Stage the upload before locking so slow storage I/O never blocks planning
    # writers serialized on the project row lock.
    staging_key, byte_count, source_sha256 = await _stage_source_xml(file, batch.id)
    final_key = _source_key(batch.id)
    try:
        try:
            get_mutable_project_lock(db, batch.project_id, current_user.id)
            db.refresh(batch)
            if batch.status != "pending":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Batch is no longer pending",
                )
            # S3 has no rename: this server-side copy is the switchover that os.replace
            # used to be. Concurrent uploads each own a distinct staging key, so the only
            # contended write is this one, and it happens under the project lock.
            #
            # It is the only network call left inside the locked section, and it has to
            # stay there: it is what makes the switchover atomic with respect to the
            # `status != "pending"` re-check just above. So its timeout budget *is the
            # maximum time every other writer on this project is blocked* -- planning,
            # devis and task writers all serialize on the same `ms_project` row, and
            # `db/session.get_engine` sets no `lock_timeout`, so they wait indefinitely.
            # `ObjectStorage.copy` therefore runs on a dedicated fail-fast client
            # (`_SWITCHOVER_*` in core/object_storage.py: ~25s worst case, against the
            # ~105s the data-path timeouts would allow). Anything added inside this
            # section has to be accounted for the same way.
            try:
                await run_in_threadpool(import_object_storage.copy, staging_key, final_key)
            # A staging object that vanished between the two calls is a storage anomaly,
            # not a caller mistake, so it maps to the same 503 as an outright outage.
            except (ObjectStorageKeyNotFoundError, ObjectStorageUnavailableError) as exc:
                raise _storage_unavailable(exc) from exc

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
            batch.source_storage_path = final_key
            batch.source_sha256 = source_sha256
            batch.status = "pending"
            batch.log_json = json.dumps(log_payload)
            db.add(batch)
            # Releases the project row lock. Everything below runs unlocked.
            db.commit()
            db.refresh(batch)
        except Exception:
            # Same reason as the commit above: end the transaction, and with it the row
            # lock, before the staging cleanup in the `finally`. That cleanup is a network
            # call now, and the failure paths that reach here are precisely the ones where
            # the store is slow, so holding the lock across it would stall every planning,
            # devis and task writer on this project for the whole timeout budget.
            db.rollback()
            raise
    finally:
        # Always: after a successful copy the staging object is a duplicate, and after a
        # failure it is orphaned. Unlike os.replace, a copy leaves the source behind.
        await run_in_threadpool(_discard_staged_object, staging_key)

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


def _loss_payload(loss: domain.CostLoss) -> dict[str, object]:
    return {
        "node_id": loss.node_id,
        "work_item_id": loss.work_item_id,
        "label": loss.label,
        "nature": loss.nature.value,
        "amount": loss.amount,
        "bearing_task_name": loss.bearing_task_name,
    }


@dataclass(frozen=True)
class _RevisionCostLosses:
    """Règle 3's safeguard for the diff preview, in the two shapes it has.

    ``per_uid`` is what a confirmation dialog shows *next to* each vanished task,
    so a cost node doomed by two nested removals appears under both -- both
    disappearances are real, and the lists are therefore **not summable**.
    ``total`` is the project-wide, deduplicated amount at stake, which is the only
    figure a "you are about to lose X" headline may use.
    """

    per_uid: dict[int, list[dict[str, object]]]
    total: list[dict[str, object]]


def _revision_cost_losses(
    db: Session, project_id: int, parsed: ParsedProject
) -> _RevisionCostLosses:
    """Read straight off the revision the confirmed run would write into.

    So what the user confirms is what gets applied. Empty for a project that has no
    revision yet -- nothing can be lost from a planning that does not exist.
    """
    diff = revision_import.plan_import(db, project_id, parsed)
    if diff is None:
        return _RevisionCostLosses(per_uid={}, total=[])
    return _RevisionCostLosses(
        per_uid={
            item.external_uid: [_loss_payload(loss) for loss in item.cost_losses]
            for item in diff.removed
            if item.cost_losses
        },
        total=[_loss_payload(loss) for loss in diff.cost_losses],
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
    parsed_project: ParsedProject,
    stored_payload: dict[str, Any],
) -> revision_import.RevisionImport:
    try:
        # The status commit above released the project row lock; re-acquire it
        # immediately before mutating snapshots so a concurrent writer cannot
        # change displayed_planning_id/status between the two transactions.
        project = get_mutable_project_lock(db, project_id, owner_id)
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
        # The revision path, in the *same* transaction as the legacy tables above
        # (E14-06, #332). Both are written until #333 migrates the devis stack off
        # `ms_task`: dropping the legacy write now would make every newly imported
        # project unchiffrable, which is #313 reintroduced backwards. A refusal here
        # -- a validated revision (REVISION_IMMUTABLE), an inapplicable file
        # structure -- rolls the legacy write back with it, so **no write can
        # succeed on one side and fail on the other**.
        #
        # That is the whole of the guarantee, and the #332 review (B1) was right to
        # strike the stronger claim this comment used to make: the two tables *can*
        # hold different uids. The legacy upsert never deletes, so a re-import that
        # drops uid 2 leaves `ms_task` carrying it while the revision no longer
        # does. Both behaviours are intended; only the sentence was wrong.
        with revision_operation(db):
            outcome = revision_import.apply_import(db, project.id, parsed_project)
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
        return outcome
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


def _reject_unreadable_source(
    db: Session,
    batch_id: int,
    owner_id: int,
    parse_error: MsProjectValidationError | None,
) -> NoReturn:
    """Fail a batch whose XML never parsed, and answer the 400 that says so.

    The file was parsed once, unlocked, by ``run_batch``; this is where that result
    is acted on. The batch is marked ``failed`` rather than left pending because
    replaying it would parse the very same bytes to the very same error -- nothing
    the operator can repair on this side -- and its ``issues`` are recorded in
    ``log_json`` so ``GET /imports/v1/batches/{id}/errors`` can list them, which is
    where a client reads them from -- and not ``GET /imports/v1/batches/{id}``, which
    returns ``warnings`` only and would show an empty list for this batch.

    ``parse_error`` is ``None`` only if ``run_batch`` produced neither a result nor
    an error, which it cannot; the fallback exists so this function narrows
    ``parsed_project`` for the caller instead of asserting.
    """
    error = parse_error or MsProjectValidationError(
        [{"code": "IMPORT_FAILED", "message": "The uploaded XML was never parsed"}]
    )
    db.rollback()
    _mark_batch_failed(db, batch_id, owner_id, str(error), error.issues)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Import failed") from error


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
    _relock_pending_batch(db, batch, project_id, owner_id, expected_sha256)
    # First refusal of all, and deliberately ahead of ``ensure_importable`` (#332
    # review, B7). E14-06 inserted that pre-flight in front of the parse result and
    # silently changed which complaint a user hears: a malformed MSPDI dropped on a
    # project whose latest revision is validated -- or which has no default calendar
    # -- answered 409, the user repaired the *configuration*, replayed, and only then
    # learned the file itself was broken. Two round trips to hear the fault that was
    # true from the start. The file is unusable whatever the target's state, so it is
    # judged first, which is also the precedence that held before this issue.
    if parsed_project is None:
        _reject_unreadable_source(db, batch_id, owner_id, parse_error)
    # Asked before the batch is marked running, so a refusal leaves it reusable --
    # the one thing worth keeping from the ``IMPORT_CONFLICT`` pre-flight this
    # replaces. What is *not* kept is the refusal itself: a re-import into a draft
    # removes whatever the file dropped, referenced or not (#325). Two refusals are
    # asked here and both are of the "fix the configuration, then replay this very
    # file" family: a validated target revision (INV-03) and a missing default
    # calendar (Règle 1/INV-15) -- see ``revision_import.ensure_importable``.
    with revision_operation(db):
        revision_import.ensure_importable(db, project_id)
    _mark_batch_running(db, batch, accepted_at)
    outcome = _apply_confirmed_import(
        db,
        batch,
        batch_id,
        project_id,
        owner_id,
        xml_bytes,
        parsed_project,
        stored_payload,
    )

    return ImportRunAcceptedResponse(
        batchId=batch.id,
        status="success",
        acceptedAt=accepted_at,
        # Which revision the file actually landed in, and whether the import had to
        # create it. The import targets the *latest* revision by version number and
        # the client cannot name one (#332 review, M2), so without this a user who
        # meant to feed draft v2 but had since opened v3 would be told nothing at
        # all -- v2's ``lock_version`` would not even move to raise a 409 later.
        revisionId=outcome.revision_id,
        revisionCreated=outcome.created_revision,
    )


@router.post(
    "/{batch_id}/run",
    response_model=ImportRunAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": FastAPIErrorResponse},
        401: {"model": FastAPIErrorResponse},
        404: {"model": FastAPIErrorResponse},
        409: {"model": FastAPIErrorResponse},
        503: {"model": FastAPIErrorResponse},
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


@router.get(
    "/{batch_id}/diff",
    response_model=ImportDiffResponse,
    responses={
        400: {"model": FastAPIErrorResponse},
        401: {"model": FastAPIErrorResponse},
        404: {"model": FastAPIErrorResponse},
        409: {"model": FastAPIErrorResponse},
        503: {"model": FastAPIErrorResponse},
    },
)
def get_batch_diff(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ImportDiffResponse:
    """Preview what confirming this batch would change, writing nothing.

    Refuses the whole file -- 400 ``REVISION_IMPORT_STRUCTURE_INVALID``, raised by
    ``plan_import`` through ``revision_operation`` -- when its structure is
    inapplicable to the target revision. The #332 review (M3) asked for that call
    to be made explicitly, degrading gracefully being the alternative: render the
    legacy diff with ``cost_losses = {}``.

    It is refused, for two reasons. An empty ``costLosses`` on a ``removed`` item
    is indistinguishable from "this removal costs nothing" -- the preview would
    *understate money*, which is the one thing Règle 3's safeguard exists to rule
    out, and it would do so on the very screen where the user is asked to confirm.
    And the fault is not one the diff helps with: the file lists a child before its
    parent, so the remedy is to re-export it from MS Project, not to review the
    tasks one by one. ``REVISION_IMPORT_STRUCTURE_INVALID`` names that family, and
    ``POST .../run`` refuses the same file identically (both go through
    ``plan_reimport``), so nothing is lost but the preview of an import that could
    never complete.
    """
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
    with revision_operation(db):
        cost_losses = _revision_cost_losses(db, project.id, parsed)
    items = [
        ImportDiffItem(**cast(dict[str, Any], item))
        for item in build_import_diff(db, project, parsed, cost_losses=cost_losses.per_uid)
    ]
    return ImportDiffResponse(
        batchId=batch.id,
        sourceSha256=batch.source_sha256,
        identicalSource=previous is not None,
        items=items,
        costLosses=[ImportCostLoss(**cast(dict[str, Any], loss)) for loss in cost_losses.total],
    )


@router.get(
    "/{batch_id}",
    response_model=ImportBatchStatusResponse,
    responses={401: {"model": FastAPIErrorResponse}, 404: {"model": FastAPIErrorResponse}},
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
    responses={401: {"model": FastAPIErrorResponse}, 404: {"model": FastAPIErrorResponse}},
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
