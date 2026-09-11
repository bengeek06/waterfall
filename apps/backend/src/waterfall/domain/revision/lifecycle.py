"""Lifecycle of a revision: creation, copy, validation.

Implements the state machine of the specification -- ``∅ -> draft``,
``draft -> validated``, ``validated -> superseded``, and ``validated ou
superseded -> draft`` *by copy only*. No transition ever brings a validated
revision back to draft: one only gets a copy of it (INV-03, INV-07).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from waterfall.domain.revision.entities import (
    CostNature,
    FrozenLine,
    NodeLink,
    Project,
    ProjectRevision,
    RevisionKind,
    RevisionNode,
    RevisionStatus,
)
from waterfall.domain.revision.errors import RevisionLifecycleError
from waterfall.domain.revision.guards import require_draft, touch
from waterfall.domain.revision.pricing import AmountResolver, default_amount
from waterfall.domain.revision.structure import depth_first, resolve_bearing_task


def _next_version_number(project: Project) -> int:
    used = [revision.version_number for revision in project.revisions.values()]
    return max(used, default=0) + 1


def _validate_version_number(project: Project, version_number: int) -> None:
    if version_number <= 0:
        raise RevisionLifecycleError(f"version_number {version_number} must be positive (INV-21)")
    clashing = [
        revision.id
        for revision in project.revisions.values()
        if revision.version_number == version_number
    ]
    if clashing:
        raise RevisionLifecycleError(
            f"version_number {version_number} is already used by revision {clashing[0]} "
            f"of project {project.id} (INV-21)"
        )


def create_revision(
    project: Project,
    *,
    kind: RevisionKind = RevisionKind.INITIAL,
    version_number: int | None = None,
    currency_code: str = "EUR",
    note: str | None = None,
    source_revision_id: int | None = None,
    now: datetime | None = None,
) -> ProjectRevision:
    """Create an empty draft revision in ``project``."""
    number = _next_version_number(project) if version_number is None else version_number
    _validate_version_number(project, number)
    revision = ProjectRevision(
        id=project.next_revision_id,
        project_id=project.id,
        version_number=number,
        kind=kind,
        status=RevisionStatus.DRAFT,
        source_revision_id=source_revision_id,
        currency_code=currency_code,
        note=note,
        created_at=now,
    )
    project.next_revision_id += 1
    project.revisions[revision.id] = revision
    return revision


def copy_revision(
    project: Project,
    source: ProjectRevision,
    *,
    kind: RevisionKind | None = None,
    version_number: int | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> ProjectRevision:
    """Create a new draft revision reproducing ``source`` (INV-07).

    Same number of nodes, same depth-first order, same facet values, and each new
    node designates the **same** ``work_item`` as its counterpart. No node
    identity is shared with the source, its precedence links are retranslated
    onto the copy's own nodes (INV-08), and its frozen lines are *not* copied --
    a draft carries none (INV-24). Whatever the source's status: copying is
    precisely how one edits a validated revision.

    The skeleton fingerprint follows the copy, because the copy reproduces the
    source's tree exactly: a skeleton nobody touched is still untouched once
    copied, and the copy is the only place a regeneration can write when the
    source is validated (Règle 4, INV-03).
    """
    copy = create_revision(
        project,
        kind=source.kind if kind is None else kind,
        version_number=version_number,
        currency_code=source.currency_code,
        note=note,
        source_revision_id=source.id,
        now=now,
    )
    copy.skeleton_fingerprint = source.skeleton_fingerprint

    node_ids: dict[int, int] = {}
    for node in depth_first(source):
        new_node = RevisionNode(
            id=project.next_node_id,
            revision_id=copy.id,
            work_item_id=node.work_item_id,
            parent_id=None if node.parent_id is None else node_ids[node.parent_id],
            position=node.position,
        )
        project.next_node_id += 1
        node_ids[node.id] = new_node.id
        copy.nodes[new_node.id] = new_node
        plan = source.plan_facets.get(node.id)
        if plan is not None:
            copy.plan_facets[new_node.id] = replace(plan, node_id=new_node.id)
        cost = source.cost_facets.get(node.id)
        if cost is not None:
            copy.cost_facets[new_node.id] = replace(cost, node_id=new_node.id)

    copy.links = [
        NodeLink(
            node_id=node_ids[link.node_id],
            predecessor_node_id=node_ids[link.predecessor_node_id],
            link_type=link.link_type,
            lag_tenth_minute=link.lag_tenth_minute,
            lag_format=link.lag_format,
        )
        for link in source.links
        if link.node_id in node_ids and link.predecessor_node_id in node_ids
    ]
    return copy


def _frozen_line(
    project: Project,
    revision: ProjectRevision,
    node_id: int,
    amount_of: AmountResolver,
) -> FrozenLine:
    facet = revision.cost_facets[node_id]
    node = revision.nodes[node_id]
    bearing = resolve_bearing_task(revision, node_id)
    bearing_facet = None if bearing is None else revision.plan_facets.get(bearing.id)
    role = None if facet.role_id is None else project.roles.get(facet.role_id)
    is_labor = facet.nature is CostNature.LABOR
    if is_labor and role is not None:
        category_code = role.category_code
    elif facet.cost_category_id is None:
        category_code = None
    else:
        category_code = project.cost_categories.get(facet.cost_category_id)
    return FrozenLine(
        revision_id=revision.id,
        work_item_id=node.work_item_id,
        bearing_work_item_id=None if bearing is None else bearing.work_item_id,
        label=facet.label,
        bearing_task_name=None if bearing_facet is None else bearing_facet.name,
        role_name=None if role is None else role.name,
        accounting_code=None if role is None else role.accounting_code,
        category_code=category_code,
        year=None if facet.planned_date is None else facet.planned_date.year,
        quantity=facet.quantity,
        hours=facet.hours,
        hourly_rate=None if role is None else role.hourly_rate,
        # Left null on purpose: inflation is the calculation engine's business,
        # which E14-07 (#333) plugs in as an :data:`AmountResolver`. The domain
        # never invents a coefficient it has no rate table to compute.
        inflation_coefficient=None,
        amount=amount_of(project, facet),
    )


def validate_revision(
    project: Project,
    revision: ProjectRevision,
    *,
    now: datetime,
    amount_of: AmountResolver = default_amount,
) -> ProjectRevision:
    """Validate a draft: produce its frozen lines and make it immutable.

    The previously validated revision **of the same kind** in the same project
    becomes ``superseded`` (INV-22); the other drafts are untouched. One frozen
    line is produced per cost facet existing at validation time (INV-24), and it
    references no mutable structure -- identities, labels and amounts only
    (INV-23, Rule 2).

    The frozen lines are built first, into a local, and only then is anything
    mutated: an injected ``amount_of`` that raises must not leave the project with
    its previous revision already superseded and no validated one to replace it.
    """
    require_draft(revision)
    frozen_lines = [
        _frozen_line(project, revision, node.id, amount_of)
        for node in depth_first(revision)
        if node.id in revision.cost_facets
    ]
    superseded = [
        previous
        for previous in project.revisions.values()
        if previous.id != revision.id
        and previous.kind is revision.kind
        and previous.status is RevisionStatus.VALIDATED
    ]

    for previous in superseded:
        previous.status = RevisionStatus.SUPERSEDED
    revision.frozen_lines = frozen_lines
    revision.status = RevisionStatus.VALIDATED
    revision.validated_at = now
    touch(revision)
    return revision
