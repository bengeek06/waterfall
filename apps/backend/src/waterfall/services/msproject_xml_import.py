from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.services.msproject_xml import (
    ParsedProject,
    ParsedTask,
    outline_parent_uids,
    parse_msproject_xml,
)
from waterfall.services.project_lifecycle import ensure_project_mutable


def _populate_parent_metadata(tasks: list[WfPlanningTaskSnapshot]) -> None:
    # outline_parent_uids (issue #176) is shared with the calendar-mismatch
    # import diagnostic in services/import_diff.py, which needs the exact same
    # outline-number-to-parent derivation over a raw ParsedTask list instead
    # of an already-persisted WfPlanningTaskSnapshot.
    parent_uids = outline_parent_uids((task.uid, task.outline_number) for task in tasks)
    for task in tasks:
        if task.uid not in parent_uids:
            continue
        assert task.outline_number is not None  # guaranteed by outline_parent_uids
        task.position = int(task.outline_number.split(".")[-1])
        task.parent_uid = parent_uids[task.uid]


def _apply_project_metadata(project: MsProject, parsed: ParsedProject) -> None:
    project.external_uid = parsed.external_uid
    project.source_version = parsed.source_version
    project.save_version_out = parsed.save_version
    project.schedule_from_start = parsed.schedule_from_start
    project.start_date = parsed.start_date
    project.finish_date = parsed.finish_date
    project.calendar_uid = parsed.calendar_uid
    project.minutes_per_day = parsed.minutes_per_day
    project.minutes_per_week = parsed.minutes_per_week
    project.days_per_month = parsed.days_per_month
    project.currency_code = parsed.currency_code


def _shared_task_fields(task: ParsedTask) -> dict[str, object]:
    """The columns carried identically by ``WfPlanningTaskSnapshot`` and ``MsTask``.

    Single source of truth for both writes of one imported task (issue #313):
    the snapshot row built by ``_task_kwargs`` and its canonical ``MsTask``
    twin upserted by ``_sync_ms_tasks``, so the two tables cannot drift apart
    field by field. Excludes ``notes`` (snapshot-only) and the owning key
    (``planning_id`` vs ``project_id``).
    """
    return {
        "name": task.name,
        "task_type": task.task_type,
        "outline_number": task.outline_number,
        "outline_level": task.outline_level,
        "wbs": task.wbs,
        "start_at": task.start_at,
        "finish_at": task.finish_at,
        "duration_minutes": task.duration_minutes,
        "duration_format": task.duration_format,
        "percent_complete": task.percent_complete,
        "is_summary": task.is_summary,
        "is_milestone": task.is_milestone,
        "is_manual": task.is_manual,
        "calendar_uid": task.calendar_uid,
    }


def _task_kwargs(task: ParsedTask, planning_id: int) -> dict[str, object]:
    return {
        "planning_id": planning_id,
        "uid": task.uid,
        "notes": task.notes,
        **_shared_task_fields(task),
    }


def _sync_ms_tasks(db: Session, project: MsProject, parsed: ParsedProject) -> None:
    """Upsert the canonical ``MsTask`` twin of every imported task (issue #313).

    ``MsTask`` is the table every estimate row points at -- ``EstimateTaskRow``,
    ``EstimateCostLine`` and ``EstimateRoleAssignment`` all carry a ``task_id``
    FK to ``ms_task.id`` -- so an import that only wrote the planning snapshots
    produced a project whose devis silently got ``task_id = NULL`` on every row
    and could not be priced per task at all. This mirrors what
    ``services.planning_structure.generate_planning_structure`` already does for
    the "Lotissement" flow, applying the convention settled by E6-06/#67: a task
    is written to both tables within the same transaction.

    The upsert key is ``(project_id, uid)`` (``uq_ms_task_project_uid``), the
    natural key of the table, so re-importing the same file updates the existing
    rows instead of creating a second set.

    Deliberately never deletes an ``MsTask``, even when its ``uid`` disappeared
    from the re-imported file: that row may still be referenced by an existing
    devis (``EstimateTaskRow``/``EstimateCostLine``/``EstimateRoleAssignment``),
    and removing it would both violate those FKs and destroy priced work.
    Reaping genuinely orphaned ``MsTask`` rows is a separate concern, tracked by
    issue #267. This is a deliberate asymmetry with the snapshot handling in
    ``import_tasks_and_links``, which does clear and rebuild a draft planning's
    snapshots -- only ``MsTask`` is upsert-without-delete.

    ``ms_task_link`` is deliberately *not* mirrored: the link snapshots remain
    the single source of truth for dependencies as long as the project has a
    displayed planning (which an import always leaves behind), and both
    ``/projects/{id}/export.xml`` and the planning routes read them from there.
    Only the task rows need a canonical twin, because only tasks are referenced
    by id from the devis tables.

    No backfill migration ships with this fix (deliberate, not an oversight):
    projects imported before it keep an empty ``ms_task`` and are repaired by
    simply re-importing the same file, which is preferable to a data migration
    over the devis tables right before E10 (#250).
    """
    existing_by_uid = {
        task.uid: task for task in db.query(MsTask).filter(MsTask.project_id == project.id).all()
    }
    tasks: list[MsTask] = []
    for parsed_task in parsed.tasks:
        task = existing_by_uid.get(parsed_task.uid)
        if task is None:
            task = MsTask(project_id=project.id, uid=parsed_task.uid)
            db.add(task)
        # structure_key/structure_kind identify rows owned by the "Lotissement"
        # flow (generate_planning_structure), which allocates its uids from 1 --
        # exactly the range an MS Project file uses -- so an import routinely
        # adopts rows that flow generated. Both columns are therefore cleared
        # here, on creation (an imported task has no structure identity; several
        # NULL structure_key rows coexist fine under
        # uq_ms_task_project_structure_key) *and* on adoption: an adopted row has
        # become an imported task, and leaving the key behind would let
        # generate_planning_structure still believe it owns the row -- silently
        # overwriting the imported name on the next structure save, or dropping
        # into its removal branch (deleting an imported task's twin, or raising
        # an unexplainable 409) as soon as the lot is renamed. This matches the
        # snapshot side, which already took ownership by deleting the draft's
        # snapshots and rebuilding them from the file without any structure_key.
        # A later structure regeneration simply recreates the missing node under
        # a fresh uid -- its documented additive/idempotent behaviour.
        task.structure_key = None
        task.structure_kind = None
        for field, value in _shared_task_fields(parsed_task).items():
            setattr(task, field, value)
        tasks.append(task)
    # parent_uid is a self-referential FK on (project_id, parent_uid) ->
    # (project_id, uid): every row must already exist before any of them points
    # at a parent, exactly like the snapshot pass in import_tasks_and_links.
    db.flush()
    _populate_ms_task_parent_metadata(tasks, parsed.tasks)
    db.flush()


def _populate_ms_task_parent_metadata(
    tasks: list[MsTask], parsed_tasks: tuple[ParsedTask, ...]
) -> None:
    """Derive ``parent_uid``/``position`` for ``MsTask`` exactly like
    ``_populate_parent_metadata`` does for the snapshots, from the same
    ``outline_parent_uids`` mapping, so both tables describe the same tree.

    Unlike the snapshots (rebuilt from scratch on every import), an ``MsTask``
    here may be a pre-existing row, so a uid absent from the mapping ("parent
    unknown": missing or malformed outline number) is actively reset to
    ``None``/``None`` rather than merely skipped -- otherwise a re-import would
    leave a stale parent behind while its snapshot twin has none.
    """
    parent_uids = outline_parent_uids((task.uid, task.outline_number) for task in parsed_tasks)
    for task in tasks:
        if task.uid not in parent_uids:
            task.parent_uid = None
            task.position = None
            continue
        assert task.outline_number is not None  # guaranteed by outline_parent_uids
        task.position = int(task.outline_number.split(".")[-1])
        task.parent_uid = parent_uids[task.uid]


def import_tasks_and_links(
    db: Session,
    xml_bytes: bytes,
    project: MsProject,
    parsed_project: ParsedProject | None = None,
) -> tuple[int, int, tuple[dict[str, object], ...]]:
    ensure_project_mutable(project)
    parsed = parsed_project if parsed_project is not None else parse_msproject_xml(xml_bytes)
    _apply_project_metadata(project, parsed)
    db.add(project)
    db.flush()
    now = datetime.now(UTC)
    displayed = (
        db.query(WfPlanning)
        .filter(WfPlanning.id == project.displayed_planning_id)
        .populate_existing()
        .with_for_update()
        .first()
        if project.displayed_planning_id is not None
        else None
    )
    if displayed is not None and displayed.status == "draft":
        planning = displayed
        db.query(WfPlanningLinkSnapshot).filter(
            WfPlanningLinkSnapshot.planning_id == planning.id
        ).delete(synchronize_session=False)
        db.query(WfPlanningTaskSnapshot).filter(
            WfPlanningTaskSnapshot.planning_id == planning.id
        ).update({WfPlanningTaskSnapshot.parent_uid: None}, synchronize_session=False)
        db.query(WfPlanningTaskSnapshot).filter(
            WfPlanningTaskSnapshot.planning_id == planning.id
        ).delete(synchronize_session=False)
    else:
        version_number = (
            db.query(func.max(WfPlanning.version_number))
            .filter(WfPlanning.project_id == project.id)
            .scalar()
            or 0
        ) + 1
        planning = WfPlanning(
            project_id=project.id,
            version_number=version_number,
            status="draft",
            note="Imported from MS Project",
            created_at=now,
        )
        db.add(planning)
        db.flush()

    tasks = [
        WfPlanningTaskSnapshot(**_task_kwargs(parsed_task, planning.id))
        for parsed_task in parsed.tasks
    ]
    db.add_all(tasks)
    db.flush()
    _populate_parent_metadata(tasks)
    db.add_all(
        WfPlanningLinkSnapshot(
            planning_id=planning.id,
            task_uid=link.task_uid,
            predecessor_uid=link.predecessor_uid,
            link_type=link.link_type,
            lag_tenth_minute=link.lag_tenth_minute,
            lag_format=link.lag_format,
        )
        for link in parsed.links
    )
    # Explicit, so that an IntegrityError on a link surfaces from here rather
    # than from inside _sync_ms_tasks, whose first query would otherwise be the
    # autoflush trigger for these very inserts.
    db.flush()
    # Same transaction as the snapshots above, on purpose (E6-06/#67): an
    # imported task must exist in both tables or the project's devis is not
    # chiffrable per task (issue #313).
    _sync_ms_tasks(db, project, parsed)
    project.displayed_planning_id = planning.id
    db.flush()
    return len(parsed.tasks), len(parsed.links), parsed.warnings
