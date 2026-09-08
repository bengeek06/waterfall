from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ImportMode = Literal["standard", "full"]
BatchStatus = Literal["pending", "running", "success", "failed"]


class ImportBatchCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_id: int = Field(alias="projectId", gt=0)
    import_mode: ImportMode = Field(alias="importMode")
    source_name: str | None = Field(default=None, alias="sourceName", max_length=255)


class ImportBatchResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    import_mode: ImportMode = Field(alias="importMode")
    status: BatchStatus
    source_name: str | None = Field(default=None, alias="sourceName")
    started_at: datetime = Field(alias="startedAt")
    ended_at: datetime | None = Field(default=None, alias="endedAt")
    error_message: str | None = Field(default=None, alias="errorMessage")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class ImportRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    dry_run: bool = Field(default=False, alias="dryRun")
    confirm: bool = Field(default=False)


class ImportDiffItem(BaseModel):
    # populate_by_name is required for build_import_diff (services/import_diff.py)
    # to actually populate link_changes/calendar_mismatch: it builds plain
    # dicts keyed by the Python field name (e.g. "link_changes"), not the
    # camelCase alias, and without this a Pydantic v2 model with an aliased
    # field silently ignores an unaliased key instead of raising, so the
    # field was previously constructed as an always-empty default.
    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["added", "modified", "removed", "conflict", "calendar_mismatch"]
    uid: int
    message: str
    fields: list[str] = Field(default_factory=list)
    link_changes: list["ImportLinkChange"] = Field(default_factory=list, alias="linkChanges")
    calendar_mismatch: "ImportCalendarMismatch | None" = Field(
        default=None, alias="calendarMismatch"
    )


class ImportLinkChange(BaseModel):
    action: Literal["added", "removed"]
    task_uid: int = Field(alias="taskUid")
    predecessor_uid: int = Field(alias="predecessorUid")
    link_type: int = Field(alias="linkType")
    lag_tenth_minute: int | None = Field(default=None, alias="lagTenthMinute")
    lag_format: int | None = Field(default=None, alias="lagFormat")


class ImportCalendarMismatch(BaseModel):
    """Structured payload for a ``calendar_mismatch`` diff item (issue #176):
    the duration recorded in the imported file versus the duration
    Waterfall's own calendar engine would compute for the same task."""

    model_config = ConfigDict(populate_by_name=True)

    task_uid: int = Field(alias="taskUid", ge=1)
    file_duration_minutes: int = Field(alias="fileDurationMinutes", ge=0)
    expected_duration_minutes: int = Field(alias="expectedDurationMinutes", ge=0)


class ImportDiffResponse(BaseModel):
    batch_id: int = Field(alias="batchId")
    source_sha256: str | None = Field(default=None, alias="sourceSha256")
    identical_source: bool = Field(alias="identicalSource")
    items: list[ImportDiffItem]


class ImportRunAcceptedResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    batch_id: int = Field(alias="batchId")
    status: BatchStatus
    accepted_at: datetime = Field(alias="acceptedAt")


class ImportIssue(BaseModel):
    code: str
    message: str
    task_uid: int | None = Field(default=None, alias="taskUid")
    predecessor_uid: int | None = Field(default=None, alias="predecessorUid")


class ImportErrorListResponse(BaseModel):
    items: list[ImportIssue]


class ImportCounters(BaseModel):
    tasks: int
    links: int


class ImportBatchStatusResponse(ImportBatchResponse):
    project_id: int | None = Field(default=None, alias="projectId")
    counters: ImportCounters
    warnings: list[ImportIssue]
