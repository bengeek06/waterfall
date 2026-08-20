from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject, MsTask, MsTaskLink
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
        .filter(MsTask.structure_key.in_(keys))
        .all()
    )
    if existing:
        existing_by_key = {task.structure_key: task for task in existing}
        if set(existing_by_key) != set(keys):
            raise ValueError("Project contains an incomplete planning structure")
        return [existing_by_key[node.key] for node in nodes]

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
        task = MsTask(
            project_id=project.id,
            uid=next_uid,
            id_display=next_id,
            structure_key=node.key,
            structure_kind=node.kind,
            parent_uid=uid_by_key.get(node.parent_key) if node.parent_key else None,
            position=node.position,
            name=node.name,
            outline_number=node.outline_number,
            outline_level=node.outline_level,
            task_type=0,
            is_summary=node.is_summary,
            is_milestone=node.is_milestone,
        )
        db.add(task)
        tasks.append(task)
        uid_by_key[node.key] = next_uid
        next_uid += 1
        next_id += 1

    db.flush()
    deliverables_by_lot_key = {
        f"{post.key}/{lot.key}": lot.deliverables for post in payload.posts for lot in post.lots
    }
    for node in nodes:
        if node.kind != "milestone":
            continue
        milestone_uid = uid_by_key[node.key]
        lot_key = node.parent_key
        if lot_key is None:
            continue
        for deliverable in deliverables_by_lot_key[lot_key]:
            deliverable_key = f"{lot_key}/{deliverable.key}"
            db.add(
                MsTaskLink(
                    project_id=project.id,
                    task_uid=milestone_uid,
                    predecessor_uid=uid_by_key[deliverable_key],
                    link_type=1,
                    lag_tenth_minute=0,
                    lag_format=7,
                )
            )
    db.flush()
    return tasks
