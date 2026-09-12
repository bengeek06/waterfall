from datetime import datetime
from decimal import Decimal
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

    kind: Literal["added", "modified", "removed", "calendar_mismatch"]
    uid: int
    message: str
    fields: list[str] = Field(default_factory=list)
    link_changes: list["ImportLinkChange"] = Field(default_factory=list, alias="linkChanges")
    calendar_mismatch: "ImportCalendarMismatch | None" = Field(
        default=None, alias="calendarMismatch"
    )
    cost_losses: list["ImportCostLoss"] = Field(default_factory=list, alias="costLosses")


class ImportCostLoss(BaseModel):
    """One cost facet a confirmed re-import would destroy (Règle 3, E14-06/#332).

    The mandatory safeguard of Règle 3: "la suppression ne doit jamais être
    silencieuse". Carried by the ``removed`` diff item of the vanished task whose
    disappearance takes it away -- with its label, its MO/non-MO nature, its
    current amount and the task it hangs under -- so a confirmation dialog can name
    the chiffrage it is about to lose instead of letting it go quietly. A removal
    that costs nothing carries an empty list and still shows as a plain ``removed``
    item, exactly as before.

    **The per-item lists are not summable.** A cost node doomed by two nested
    removals -- a summary and one of its children both dropped by the file -- is
    listed under each of them, because each disappearance really does take it away
    and each has to name it. Adding the amounts up across items therefore counts
    that chiffrage twice. The deduplicated project-wide total is
    :attr:`ImportDiffResponse.cost_losses` (#332 review, M1).

    One ``removed`` item in a hundred is **synthesised**. The losses are computed
    against the revision and the ``removed`` items against the displayed legacy
    planning, two sources a user can put out of step (display an older planning than
    the one the last import created). A loss whose uid the displayed planning never
    carried is then attached to a ``removed`` item built for it rather than dropped,
    because dropping it is the silent under-report Règle 3 forbids -- see
    :func:`waterfall.services.import_diff._unattributable_loss_uids`.

    It counts and sums like any other ``removed`` item, but it **has no matching row
    in the displayed planning** (#332 review, B-3), which is the whole reason it
    exists. ``ImportDiffItem`` carries no ``name``, so a client that labels a removal
    by joining ``uid`` against the planning it renders gets nothing back for this one
    -- by construction, not by accident. Its ``message`` is the only label available.
    """

    model_config = ConfigDict(populate_by_name=True)

    node_id: int = Field(alias="nodeId")
    work_item_id: int = Field(alias="workItemId")
    label: str
    nature: Literal["labor", "non_labor"]
    amount: Decimal
    bearing_task_name: str | None = Field(default=None, alias="bearingTaskName")


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
    """The preview of an import, with Règle 3's safeguard in both its shapes.

    ``cost_losses`` here is the project-wide **deduplicated** total the confirmed
    run would destroy; ``ImportDiffItem.cost_losses`` attributes the same chiffrage
    to the vanished task whose disappearance takes it away. A cost node doomed by
    two nested removals is listed under both items, so summing the per-item lists
    over-counts money: use this one for any total shown to a user (#332 review, M1).
    """

    model_config = ConfigDict(populate_by_name=True)

    batch_id: int = Field(alias="batchId")
    source_sha256: str | None = Field(default=None, alias="sourceSha256")
    identical_source: bool = Field(alias="identicalSource")
    items: list[ImportDiffItem]
    cost_losses: list["ImportCostLoss"] = Field(default_factory=list, alias="costLosses")


class ImportRunAcceptedResponse(BaseModel):
    """What a run left behind, including *where* it landed (E14-06/#332).

    ``revision_id``/``revision_created`` answer a question the request cannot ask:
    an import always targets the project's **latest** revision by version number,
    and the client neither chooses it nor -- until now -- learned which one it was.
    With several drafts open at once (a supported state: validating one leaves the
    others intact) a user could feed v3 while believing they were feeding v2, and
    nothing would say so, v2's ``lock_version`` not having moved either. Both are
    ``None`` on a dry run, which writes nothing and targets nothing.
    """

    model_config = ConfigDict(populate_by_name=True)

    batch_id: int = Field(alias="batchId")
    status: BatchStatus
    accepted_at: datetime = Field(alias="acceptedAt")
    revision_id: int | None = Field(default=None, alias="revisionId")
    revision_created: bool | None = Field(default=None, alias="revisionCreated")


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
