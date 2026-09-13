"""Lifecycle of a revision: creation, copy, validation.

Implements the state machine of the specification -- ``∅ -> draft``,
``draft -> validated``, ``validated -> superseded``, and ``validated ou
superseded -> draft`` *by copy only*. No transition ever brings a validated
revision back to draft: one only gets a copy of it (INV-03, INV-07).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from waterfall.domain.revision.entities import (
    CostFacet,
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
from waterfall.domain.revision.pricing import (
    BreakdownResolver,
    PricedYear,
    default_breakdown,
)
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


def _frozen_lines(
    project: Project,
    revision: ProjectRevision,
    node_id: int,
    breakdown_of: BreakdownResolver,
) -> list[FrozenLine]:
    """The frozen lines one cost facet produces: **one per year of its breakdown**.

    Why per year rather than one line per facet (E14-08, #334)
    ---------------------------------------------------------

    Because a frozen line carries ``year``, ``hourly_rate`` and
    ``inflation_coefficient`` side by side, and those three only mean anything
    together. A labour facet borne by a task spanning three years is priced at three
    different annual rates under three different inflation coefficients; a single
    line could only carry their weighted average, which is a number no rate table
    contains and which no reader could ever check against ``wf_cost_rate``. Règle 2
    asks that a frozen line stay *comparable* years later -- the RAE against the
    reference budget -- and a comparison per fiscal year is precisely what a
    weighted average destroys. Aggregating the years back into one figure is a
    ``GROUP BY``; splitting an average back into years is not.

    It is also the grain the document already had: ``wf_estimate_line``, the table
    this one replaces, carried one row per ``(line, year)`` too.

    A facet whose breakdown is **empty** still produces exactly one line, at a zero
    amount. The engine prices nothing for a labour facet whose bearing task has no
    dates -- there is no year to spread the hours over -- and dropping the facet
    from the document altogether would make a line *disappear* from a financial
    document rather than show up in it at zero, which is the one outcome a frozen
    document must not have.

    That zero line is for a facet with **nothing to price**, and only for one: a
    facet carrying hours the engine could put in no year never reaches here on a
    validation, the service refusing it outright since #334's review
    (:class:`~waterfall.services.revision_tree.RevisionUnpriceableFacetError`). What
    the domain keeps is the rule -- no facet goes unrepresented; what it never had is
    the authority to decide that a thousand euros of work may be recorded as zero.

    Every label a line carries is copied **here**, out of the :class:`Project`, and
    that includes ``cost_code``: an injected pricing engine hands over numbers, never
    the decision of what a frozen line says (Règle 2).
    """
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
    breakdown = tuple(breakdown_of(project, facet)) or (_unpriced_year(facet),)
    return [
        FrozenLine(
            revision_id=revision.id,
            work_item_id=node.work_item_id,
            bearing_work_item_id=None if bearing is None else bearing.work_item_id,
            label=facet.label,
            nature=facet.nature,
            bearing_task_name=None if bearing_facet is None else bearing_facet.name,
            role_name=None if role is None else role.name,
            accounting_code=None if role is None else role.accounting_code,
            category_code=category_code,
            # Copied as a *string* off the project, never kept as an id: the
            # ventilation by code d'imputation of a validated devis has to survive
            # the imputation tree being renamed, moved or pruned (INV-23, Règle 2).
            cost_code=(
                None if facet.cost_code_id is None else project.cost_codes.get(facet.cost_code_id)
            ),
            year=priced.year,
            quantity=facet.quantity,
            hours=priced.hours,
            # The two values #334 stopped leaving null: they come from the injected
            # breakdown, per year, because that is the only grain they exist at.
            hourly_rate=priced.hourly_rate,
            inflation_coefficient=priced.inflation_coefficient,
            amount=priced.amount,
        )
        for priced in breakdown
    ]


def _unpriced_year(facet: CostFacet) -> PricedYear:
    """The single zero line a facet the resolver priced nothing for still owes.

    Its ``year`` is the facet's own forecast cash-out date when it has one, and
    nothing otherwise: inventing a year on a line worth zero would be inventing the
    one attribute a reader would compare it by.
    """
    return PricedYear(
        amount=Decimal("0"),
        year=None if facet.planned_date is None else facet.planned_date.year,
        hours=facet.hours,
    )


def validate_revision(
    project: Project,
    revision: ProjectRevision,
    *,
    now: datetime,
    breakdown_of: BreakdownResolver = default_breakdown,
) -> ProjectRevision:
    """Validate a draft: produce its frozen lines and make it immutable.

    The previously validated revision **of the same kind** in the same project
    becomes ``superseded`` (INV-22); the other drafts are untouched. At least one
    frozen line is produced per cost facet existing at validation time, one per year
    of its breakdown (INV-24, see :func:`_frozen_lines`), and none of them references
    any mutable structure -- identities, labels and amounts only (INV-23, Rule 2).

    The frozen lines are built first, into a local, and only then is anything
    mutated: an injected ``breakdown_of`` that raises must not leave the project with
    its previous revision already superseded and no validated one to replace it.
    """
    require_draft(revision)
    frozen_lines = [
        line
        for node in depth_first(revision)
        if node.id in revision.cost_facets
        for line in _frozen_lines(project, revision, node.id, breakdown_of)
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
