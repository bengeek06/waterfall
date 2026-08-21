from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject, MsTask, MsTaskLink
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.models.resources import EstimateCostLine, EstimateTaskRow, TaskRoleAssignment
from waterfall.models.wf_core import WfChargeLine, WfTaskEnrichment
from waterfall.schemas.projects import PlanningStructureCreate


@dataclass(frozen=True)
class _GeneratedNode:
    key: str
    kind: str
    name: str
    parent_key: str | None
    outline_number: str
    outline_level: int
    position: int
    is_summary: bool = False
    is_milestone: bool = False


def _build_nodes(payload: PlanningStructureCreate) -> list[_GeneratedNode]:
    nodes: list[_GeneratedNode] = []
    seen_keys: set[str] = set()

    def add(node: _GeneratedNode) -> None:
        if node.key in seen_keys:
            raise ValueError(f"Duplicate planning key: {node.key}")
        seen_keys.add(node.key)
        nodes.append(node)

    for post_position, post in enumerate(payload.posts, start=1):
        post_key = post.key
        add(
            _GeneratedNode(
                key=post_key,
                kind="poste",
                name=post.name,
                parent_key=None,
                outline_number=str(post_position),
                outline_level=1,
                position=post_position,
                is_summary=True,
            )
        )
        for lot_position, lot in enumerate(post.lots, start=1):
            lot_key = f"{post_key}/{lot.key}"
            add(
                _GeneratedNode(
                    key=lot_key,
                    kind="lot",
                    name=lot.name,
                    parent_key=post_key,
                    outline_number=f"{post_position}.{lot_position}",
                    outline_level=2,
                    position=lot_position,
                    is_summary=True,
                )
            )
            for deliverable_position, deliverable in enumerate(lot.deliverables, start=1):
                add(
                    _GeneratedNode(
                        key=f"{lot_key}/{deliverable.key}",
                        kind="livrable",
                        name=deliverable.name,
                        parent_key=lot_key,
                        outline_number=(f"{post_position}.{lot_position}.{deliverable_position}"),
                        outline_level=3,
                        position=deliverable_position,
                    )
                )
            add(
                _GeneratedNode(
                    key=f"{lot_key}/completion",
                    kind="milestone",
                    name=f"Fin {lot.name}",
                    parent_key=lot_key,
                    outline_number=f"{post_position}.{lot_position}.{len(lot.deliverables) + 1}",
                    outline_level=3,
                    position=len(lot.deliverables) + 1,
                    is_milestone=True,
                )
            )
    return nodes


def generate_planning_structure(
    db: Session,
    project: MsProject,
    payload: PlanningStructureCreate,
) -> list[MsTask]:
    nodes = _build_nodes(payload)
    keys = [node.key for node in nodes]
    existing = (
        db.query(MsTask)
        .filter(MsTask.project_id == project.id)
        .filter(MsTask.structure_key.is_not(None))
        .all()
    )
    existing_by_key = {task.structure_key: task for task in existing}
    incoming_keys = set(keys)
    removed_tasks = [task for key, task in existing_by_key.items() if key not in incoming_keys]
    for task in removed_tasks:
        task_referenced = (
            db.query(TaskRoleAssignment.id).filter(TaskRoleAssignment.task_id == task.id).first()
            or db.query(EstimateCostLine.id).filter(EstimateCostLine.task_id == task.id).first()
            or db.query(EstimateTaskRow.id).filter(EstimateTaskRow.task_id == task.id).first()
            or db.query(WfChargeLine.id)
            .filter(WfChargeLine.project_id == project.id)
            .filter(WfChargeLine.task_uid == task.uid)
            .first()
        )
        if task_referenced:
            raise ValueError(
                f"Planning task is referenced and cannot be removed: {task.structure_key}"
            )

    removed_uids = [task.uid for task in removed_tasks]
    if removed_uids:
        db.query(MsTask).filter(
            MsTask.project_id == project.id,
            MsTask.parent_uid.in_(removed_uids),
        ).update({MsTask.parent_uid: None}, synchronize_session=False)
    for task in removed_tasks:
        db.query(MsTaskLink).filter(
            (MsTaskLink.task_uid == task.uid) | (MsTaskLink.predecessor_uid == task.uid)
        ).filter(MsTaskLink.project_id == project.id).delete(synchronize_session=False)
        db.query(WfTaskEnrichment).filter(
            WfTaskEnrichment.project_id == project.id,
            WfTaskEnrichment.task_uid == task.uid,
        ).delete(synchronize_session=False)
        task.parent_uid = None
    db.flush()
    for task in sorted(removed_tasks, key=lambda item: item.outline_level or 0, reverse=True):
        db.delete(task)
    db.flush()

    max_uid = (
        db.query(MsTask.uid)
        .filter(MsTask.project_id == project.id)
        .order_by(MsTask.uid.desc())
        .first()
    )
    max_id = (
        db.query(MsTask.id_display)
        .filter(MsTask.project_id == project.id)
        .order_by(MsTask.id_display.desc())
        .first()
    )
    next_uid = (max_uid[0] if max_uid else 0) + 1
    next_id = (max_id[0] if max_id and max_id[0] is not None else 0) + 1
    uid_by_key: dict[str, int] = {}
    tasks: list[MsTask] = []

    for node in nodes:
        task = existing_by_key.get(node.key)
        if task is None:
            task = MsTask(
                project_id=project.id,
                uid=next_uid,
                id_display=next_id,
                structure_key=node.key,
                task_type=0,
            )
            db.add(task)
            next_uid += 1
            next_id += 1
        task.structure_kind = node.kind
        task.parent_uid = uid_by_key.get(node.parent_key) if node.parent_key else None
        task.position = node.position
        task.name = node.name
        task.outline_number = node.outline_number
        task.outline_level = node.outline_level
        task.is_summary = node.is_summary
        task.is_milestone = node.is_milestone
        tasks.append(task)
        uid_by_key[node.key] = task.uid

    db.flush()
    deliverables_by_lot_key = {
        f"{post.key}/{lot.key}": lot.deliverables for post in payload.posts for lot in post.lots
    }
    milestone_uids = [uid_by_key[node.key] for node in nodes if node.kind == "milestone"]
    if milestone_uids:
        db.query(MsTaskLink).filter(
            MsTaskLink.project_id == project.id,
            MsTaskLink.task_uid.in_(milestone_uids),
        ).delete(synchronize_session=False)
    for node in nodes:
        if node.kind != "milestone" or node.parent_key is None:
            continue
        for deliverable in deliverables_by_lot_key[node.parent_key]:
            db.add(
                MsTaskLink(
                    project_id=project.id,
                    task_uid=uid_by_key[node.key],
                    predecessor_uid=uid_by_key[f"{node.parent_key}/{deliverable.key}"],
                    link_type=1,
                    lag_tenth_minute=0,
                    lag_format=7,
                )
            )
    db.flush()
    return tasks


def generate_planning_snapshot(
    db: Session,
    project: MsProject,
    payload: PlanningStructureCreate,
    planning: WfPlanning,
) -> list[WfPlanningTaskSnapshot]:
    nodes = _build_nodes(payload)
    existing = (
        db.query(WfPlanningTaskSnapshot)
        .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
        .all()
    )
    existing_by_key = {task.structure_key: task for task in existing}
    source = None
    if not existing and project.displayed_planning_id not in (None, planning.id):
        source = (
            db.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == project.displayed_planning_id)
            .all()
        )
        existing_by_key.update({task.structure_key: task for task in source})

    max_uid = (
        db.query(func.max(WfPlanningTaskSnapshot.uid))
        .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
        .scalar()
        or 0
    )
    if source:
        max_uid = max(max_uid, max(task.uid for task in source))
    uid_by_key: dict[str, int] = {}
    snapshots: list[WfPlanningTaskSnapshot] = []
    incoming_keys = {node.key for node in nodes}
    links = (
        db.query(WfPlanningLinkSnapshot)
        .filter(WfPlanningLinkSnapshot.planning_id == planning.id)
        .all()
    )
    existing_uids = {task.uid for task in existing if task.structure_key in incoming_keys}
    for link in links:
        if link.task_uid not in existing_uids or link.predecessor_uid not in existing_uids:
            db.delete(link)
    removed_ids = [task.id for task in existing if task.structure_key not in incoming_keys]
    db.query(WfPlanningTaskSnapshot).filter(
        WfPlanningTaskSnapshot.planning_id == planning.id
    ).update({WfPlanningTaskSnapshot.parent_uid: None}, synchronize_session=False)
    db.flush()
    if removed_ids:
        db.query(WfPlanningTaskSnapshot).filter(WfPlanningTaskSnapshot.id.in_(removed_ids)).delete(
            synchronize_session=False
        )
    db.flush()

    for node in nodes:
        task = existing_by_key.get(node.key)
        if task is None or task.planning_id != planning.id:
            max_uid += 1
            task = WfPlanningTaskSnapshot(
                planning_id=planning.id,
                uid=max_uid,
                id_display=max_uid,
                structure_key=node.key,
            )
            db.add(task)
        task.structure_kind = node.kind
        task.parent_uid = uid_by_key.get(node.parent_key) if node.parent_key else None
        task.position = node.position
        task.name = node.name
        task.task_type = 0
        task.outline_number = node.outline_number
        task.outline_level = node.outline_level
        task.is_summary = node.is_summary
        task.is_milestone = node.is_milestone
        snapshots.append(task)
        uid_by_key[node.key] = task.uid

    db.flush()
    milestone_uids = [task.uid for task in snapshots if task.is_milestone]
    if milestone_uids:
        db.query(WfPlanningLinkSnapshot).filter(
            WfPlanningLinkSnapshot.planning_id == planning.id,
            WfPlanningLinkSnapshot.task_uid.in_(milestone_uids),
        ).delete(synchronize_session=False)
    deliverables_by_lot_key = {
        f"{post.key}/{lot.key}": lot.deliverables for post in payload.posts for lot in post.lots
    }
    for node in nodes:
        if node.kind != "milestone" or node.parent_key is None:
            continue
        for deliverable in deliverables_by_lot_key[node.parent_key]:
            db.add(
                WfPlanningLinkSnapshot(
                    planning_id=planning.id,
                    task_uid=uid_by_key[node.key],
                    predecessor_uid=uid_by_key[f"{node.parent_key}/{deliverable.key}"],
                    link_type=1,
                    lag_tenth_minute=0,
                    lag_format=7,
                )
            )
    db.flush()
    return snapshots
