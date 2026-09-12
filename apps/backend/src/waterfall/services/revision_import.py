"""MS Project import, expressed as a diff applied to a draft revision (E14-06, #332).

The third step of the chain the EPIC settled: the **domain** owns every rule
(:mod:`waterfall.domain.revision.reimport`), the **store** owns the tables
(:mod:`waterfall.services.revision_store`), and this module is the thin seam
between them plus the one translation only it can do -- MSPDI's
:class:`~waterfall.services.msproject_xml.ParsedTask` into the domain's
:class:`~waterfall.domain.revision.ImportedTask`. It holds no tree logic, no diff
logic and no Rule 3: a rule missing from the domain is added *to the domain*.

The MS Project ``uid`` is an **external identifier** here and nowhere else
---------------------------------------------------------------------------

It enters through this module, lands on ``wf_work_item.external_uid``, and is read
back out by the export (:mod:`waterfall.services.msproject_xml_export`). No other
layer reads it: the domain hooks onto ``work_item`` identity, the API onto node
ids. That is what lets the same file be re-imported into two revisions of one
project and land on the very same work items (Rule 3, "Identité de projet, pas de
révision").

Which revision an import targets
--------------------------------

The **latest** revision of the project, by version number:

* none yet -> a draft is created (``initial``, version 1), which is how a project
  created from an XML file gets its first revision;
* a draft -> that draft is re-imported into, whatever it already holds. A draft
  allows everything, deletions included: that is the product rule this EPIC is
  built on, and the reason the 409 ``IMPORT_CONFLICT`` of #325 is gone rather than
  relaxed. **No reference guard is consulted** -- not
  :mod:`waterfall.services.task_references`, not anything else;
* ``validated`` or ``superseded`` -> refused with
  :class:`~waterfall.domain.revision.ImmutableRevisionError` (INV-03), which
  :mod:`waterfall.api.revision_errors` publishes as ``REVISION_IMMUTABLE``. The
  flow is to create a new draft first, and auto-creating one here would quietly
  bypass the lifecycle the responsable produit stated.

The calendar is Règle 1's, and only Règle 1's
---------------------------------------------

Every planning facet this module creates gets its calendar from the domain, which
initialises it to the project's and resynchronises it from the first MO facet in
depth-first order. The legacy import path resolves a task's calendar differently
-- it keeps the smallest ``role_id`` -- and the divergence used to be documented
and pinned. **On the revision path Règle 1 is the only truth**, assumed here
explicitly rather than inherited: ``resolve_task_calendar_ids`` is never called,
and the file's own per-task ``<CalendarUID>`` is *not* honoured either, being an
MS Project calendar identifier with no mapping onto `wf_calendar` (it stays
recorded on the legacy tables, which this import still writes).

Concurrency
-----------

Unlike :mod:`waterfall.services.revision_tree`, nothing here takes an
``expected_lock_version``: the import runs under the `ms_project` row lock the
batch already holds (``get_mutable_project_lock``), which is the same lock every
revision route takes, so the two are serialised against each other without a
second one. The counter is still *bumped* whenever the import changes anything, so
a client holding a stale version is refused on its next write -- which is the
intended outcome of "somebody re-imported the planning under you". By how much is
deliberately left unstated: every domain helper the apply step goes through calls
``touch`` itself, so the increment counts internal calls and nothing reads it as a
number. Only two things are contractual -- it moves when something changed, and it
does *not* move when the file described the revision exactly as it already was
(see :func:`_fingerprint`).

Nothing here commits: the caller owns the transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from waterfall.domain import revision as domain
from waterfall.models import revision as tables
from waterfall.services.msproject_xml import ParsedProject, outline_parent_uids
from waterfall.services.revision_store import (
    LoadedRevision,
    ensure_project_calendar,
    load_project,
    load_revision,
    save_revision,
)

#: Note carried by the revision an import creates from scratch.
IMPORT_NOTE = "Imported from MS Project"


@dataclass(frozen=True)
class RevisionImport:
    """What an import left behind, for the caller to report."""

    revision_id: int
    #: Whether the import created the revision rather than re-importing into one.
    created_revision: bool
    #: ``False`` when the file described the revision exactly as it already was.
    changed: bool
    lock_version: int
    task_count: int
    link_count: int
    diff: domain.ImportDiff


@dataclass(frozen=True)
class _Target:
    loaded: LoadedRevision
    created: bool


def _now() -> datetime:
    """The service may read a clock; the domain it drives may not."""
    return datetime.now(UTC)


# --------------------------------------------------------------------------------------
# MSPDI -> domain
# --------------------------------------------------------------------------------------


def imported_tasks(parsed: ParsedProject) -> list[domain.ImportedTask]:
    """Translate a parsed file into the domain's import shape, in file order.

    The parent is derived from the dotted ``outline_number`` through
    :func:`~waterfall.services.msproject_xml.outline_parent_uids`, the same
    derivation the legacy import and the calendar-mismatch diagnostic already
    share -- so the two paths read one tree out of one file. A uid the derivation
    cannot place ("parent unknown": missing or malformed outline number) comes back
    as a root, exactly as it does on the legacy side.

    ``work_minutes`` is left unset: MSPDI's ``<Work>`` is not parsed by
    :mod:`waterfall.services.msproject_xml` at all, and inventing a value from the
    duration would put a number in the facet that no file ever carried.
    """
    parents = outline_parent_uids((task.uid, task.outline_number) for task in parsed.tasks)
    return [
        domain.ImportedTask(
            external_uid=task.uid,
            name=task.name,
            parent_external_uid=parents.get(task.uid),
            duration_minutes=task.duration_minutes,
            duration_format=task.duration_format,
            is_milestone=task.is_milestone,
            start_at=task.start_at,
            finish_at=task.finish_at,
            percent_complete=task.percent_complete or 0,
            # ``None`` -- MS Project never wrote ``<Manual>`` -- is read as
            # automatic, the convention the rest of the repository already applies
            # to an undecided task.
            is_manual=bool(task.is_manual),
        )
        for task in parsed.tasks
    ]


def _imported_links(
    project: domain.Project, revision: domain.ProjectRevision, parsed: ParsedProject
) -> list[domain.NodeLink]:
    """The precedence graph the re-import leaves behind: the file's, plus the local one.

    The file is authoritative for the predecessors of **the tasks it lists** and
    says nothing about the others, so a link between two nodes created in Waterfall
    survives an import untouched -- the same reading of Rule 3 a that keeps a node
    without ``external_uid`` from being reported as removed. A link arriving at a
    task the file lists is replaced by what the file says, which is what makes a
    dropped dependency actually disappear.

    A link naming a uid no node carries is skipped rather than refused: the parser
    already reports it as ``ORPHAN_LINK`` and fails the whole import
    (:func:`~waterfall.services.msproject_xml.parse_msproject_xml`), so reaching
    this point means the file was accepted and the endpoint is a task the *domain*
    declined to place -- there is nothing left to hang the link on.
    """
    nodes = domain.planning_nodes_by_external_uid(project, revision)
    file_node_ids = {
        node.id for uid, node in nodes.items() if uid in {task.uid for task in parsed.tasks}
    }
    kept = [link for link in revision.links if link.node_id not in file_node_ids]
    incoming: list[domain.NodeLink] = []
    for link in parsed.links:
        node = nodes.get(link.task_uid)
        predecessor = nodes.get(link.predecessor_uid)
        if node is None or predecessor is None:
            continue
        incoming.append(
            domain.NodeLink(
                node_id=node.id,
                predecessor_node_id=predecessor.id,
                link_type=link.link_type,
                lag_tenth_minute=link.lag_tenth_minute or 0,
                lag_format=link.lag_format,
            )
        )
    return kept + incoming


# --------------------------------------------------------------------------------------
# Which revision, and is it writable
# --------------------------------------------------------------------------------------


def latest_revision_id(db: Session, project_id: int) -> int | None:
    """Id of the project's latest revision by version number, ``None`` if it has none."""
    row = (
        db.query(tables.ProjectRevision.id)
        .filter(tables.ProjectRevision.project_id == project_id)
        .order_by(tables.ProjectRevision.version_number.desc(), tables.ProjectRevision.id.desc())
        .first()
    )
    return None if row is None else row.id


def ensure_importable(db: Session, project_id: int) -> None:
    """Refuse an import the target revision would not accept, reading two columns.

    Two refusals, both of the same family -- "fix the configuration, then replay
    the very same file" -- and that is why they are asked *here*: the transport
    layer calls this **before** it marks its batch as running, so a refused import
    leaves the batch pending and reusable instead of failed and re-uploadable only.

    * **No default calendar** (``PROJECT_CALENDAR_MISSING``). Règle 1 gives every
      planning facet a stored calendar, and an import creates planning facets, so a
      load cannot even build the project (INV-15). The #332 review (H2) caught the
      asymmetry: this refusal reached the user *after* ``_mark_batch_running``, via
      :func:`~waterfall.services.revision_store.ensure_project_calendar` deep inside
      the write, and burned the batch for a condition the product already knows how
      to report (``ProjectSetupWarningCode.no_default_calendar``) and the user fixes
      in one click.
    * **A frozen target revision** (INV-03, ``REVISION_IMMUTABLE``), raised here
      rather than left to the domain's own ``require_draft`` because the refusal
      names the flow: the remedy is a new draft, not a retry. Silent for a project
      with no revision at all -- the import creates one.
    """
    ensure_project_calendar(db)
    revision_id = latest_revision_id(db, project_id)
    if revision_id is None:
        return
    stored_status = (
        db.query(tables.ProjectRevision.status)
        .filter(tables.ProjectRevision.id == revision_id)
        .scalar()
    )
    if stored_status != domain.RevisionStatus.DRAFT.value:
        raise domain.ImmutableRevisionError(
            f"Revision {revision_id} is {stored_status} and refuses every write (INV-03); "
            "create a new draft revision of the project before importing a planning into it"
        )


def _target(db: Session, project_id: int) -> _Target:
    ensure_importable(db, project_id)
    revision_id = latest_revision_id(db, project_id)
    if revision_id is None:
        project = load_project(db, project_id)
        stubs = tuple(project.revisions.values())
        draft = domain.create_revision(
            project, kind=domain.RevisionKind.INITIAL, note=IMPORT_NOTE, now=_now()
        )
        return _Target(LoadedRevision(project=project, revision=draft, stubs=stubs), created=True)
    return _Target(load_revision(db, revision_id), created=False)


# --------------------------------------------------------------------------------------
# The diff, and the import
# --------------------------------------------------------------------------------------


def plan_import(db: Session, project_id: int, parsed: ParsedProject) -> domain.ImportDiff | None:
    """The diff an import would apply, changing nothing. ``None`` before the first one.

    Read-only, and deliberately **not** refused on a frozen revision: showing what
    a file would change is harmless, and refusing the preview would hide the reason
    the run is about to be refused. The structural refusals of Rule 3 c do fire
    here, which is the point -- an inapplicable file is named before the user
    confirms it rather than after.
    """
    revision_id = latest_revision_id(db, project_id)
    if revision_id is None:
        return None
    loaded = load_revision(db, revision_id)
    return domain.plan_reimport(loaded.project, loaded.revision, imported_tasks(parsed))


def _fingerprint(project: domain.Project, revision: domain.ProjectRevision) -> str:
    """Everything an import can change about a revision, as one comparable value.

    What makes "re-importing an unchanged file changes nothing, ``lock_version``
    included" a *proven* property rather than a guessed one. It cannot be decided
    from the diff: an empty diff still lets the apply step reorder a sibling set
    (the file's tasks come before the local ones and before the cost lines) and
    resynchronise a calendar from it, which Règle 1 requires it to do
    unconditionally. So the import is applied in memory, compared, and simply not
    written when it turned out to be a no-op.

    Links are sorted, because replacing the graph rebuilds the list in another
    order without changing the set.
    """
    nodes = [
        repr((node.id, node.parent_id, node.position, node.work_item_id))
        for node in sorted(revision.nodes.values(), key=lambda entry: entry.id)
    ]
    plans = [repr(revision.plan_facets[node_id]) for node_id in sorted(revision.plan_facets)]
    costs = [repr(revision.cost_facets[node_id]) for node_id in sorted(revision.cost_facets)]
    links = sorted(
        repr(
            (
                link.node_id,
                link.predecessor_node_id,
                link.link_type,
                link.lag_tenth_minute,
                link.lag_format,
            )
        )
        for link in revision.links
    )
    items = [
        repr((item.id, item.kind.value, item.external_uid, item.description))
        for item in sorted(project.work_items.values(), key=lambda entry: entry.id)
    ]
    return "\n".join([*nodes, *plans, *costs, *links, *items])


def apply_import(db: Session, project_id: int, parsed: ParsedProject) -> RevisionImport:
    """Import ``parsed`` into the project's draft revision, creating it if there is none.

    Three domain calls, in this order and no other:

    1. :func:`~waterfall.domain.revision.apply_reimport` -- the whole of Rule 3,
       including the removals, validated in full before the first mutation;
    2. :func:`~waterfall.domain.revision.replace_links` -- the precedence graph the
       file states, merged with the links the file knows nothing about, refused as
       a whole if it closes a cycle (INV-18);
    3. the write back, skipped when the two above turned out to change nothing.

    Atomicity is the caller's transaction: a refusal from anywhere in here leaves
    the database untouched provided the caller rolls back, which
    :func:`waterfall.api.revision_errors.revision_operation` does.
    """
    target = _target(db, project_id)
    project = target.loaded.project
    revision = target.loaded.revision
    before = None if target.created else _fingerprint(project, revision)
    lock_version = revision.lock_version

    diff = domain.apply_reimport(project, revision, imported_tasks(parsed), now=_now())
    domain.replace_links(revision, _imported_links(project, revision, parsed))

    task_count = len(revision.plan_facets)
    link_count = len(revision.links)
    if before is not None and _fingerprint(project, revision) == before:
        revision.lock_version = lock_version
        return RevisionImport(
            revision_id=revision.id,
            created_revision=False,
            changed=False,
            lock_version=lock_version,
            task_count=task_count,
            link_count=link_count,
            diff=diff,
        )
    outcome = save_revision(db, target.loaded)
    return RevisionImport(
        revision_id=outcome.revision_id,
        created_revision=target.created,
        changed=True,
        lock_version=revision.lock_version,
        task_count=task_count,
        link_count=link_count,
        diff=diff,
    )
