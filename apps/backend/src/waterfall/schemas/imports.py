from datetime import datetime
from typing import Any, Literal

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
    confirm: bool = Field(default=True)


class ImportDiffItem(BaseModel):
    kind: Literal["added", "modified", "removed", "conflict"]
    uid: int
    message: str
    fields: list[str] = Field(default_factory=list)


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


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: dict[str, Any] | None = None
