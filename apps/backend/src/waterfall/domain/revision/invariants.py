"""Invariant checker of the revision model (E14-02).

Evaluates the ``état``-scoped invariants of
``docs/revision-v0.1-specification.md`` on a revision state and names every one
that is violated by its identifier (``INV-04``, ``INV-14``, ...).

The three ``opération``-scoped invariants -- INV-02 (cascade delete), INV-03
(immutability of a validated revision) and INV-07 (copy of a revision) -- are
post-conditions comparing a before/after state and are deliberately *not*
evaluated here; they are asserted by the test bench around the operation itself.

The properties the specification explicitly refuses to turn into invariants
(summary dates, ``outline_level``/``outline_number``, derived amounts, numeric
column domains) are not evaluated either: the checker must not depend on the
calculation engine.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, fields, is_dataclass
from typing import Final, cast

from waterfall.domain.revision.entities import (
    BreakdownEntry,
    CalendarSource,
    CostFacet,
    CostNature,
    FrozenLine,
    Project,
    ProjectRevision,
    RevisionStatus,
    WorkItemKind,
)
from waterfall.domain.revision.structure import (
    bearing_work_item_id,
    children_of,
    is_cost_node,
    is_milestone_node,
    is_plan_node,
    node_by_work_item,
)

#: Scope of every invariant, as declared by the specification.
OPERATION_SCOPED_INVARIANTS: Final[frozenset[str]] = frozenset({"INV-02", "INV-03", "INV-07"})
STATE_SCOPED_INVARIANTS: Final[tuple[str, ...]] = (
    "INV-01",
    "INV-04",
    "INV-05",
    "INV-06",
    "INV-08",
    "INV-09",
    "INV-10",
    "INV-11",
    "INV-12",
    "INV-13",
    "INV-14",
    "INV-15",
    "INV-16",
    "INV-17",
    "INV-18",
    "INV-19",
    "INV-20",
    "INV-21",
    "INV-22",
    "INV-23",
    "INV-24",
    "INV-25",
    "INV-26",
    "INV-27",
)


@dataclass(frozen=True)
class InvariantViolation:
    """One violated invariant, named by its specification identifier."""

    invariant: str
    detail: str

    def __str__(self) -> str:
        """``INV-xx: detail``, the form the test bench puts in its assertion messages."""
        return f"{self.invariant}: {self.detail}"


def violated_invariant_ids(violations: list[InvariantViolation]) -> list[str]:
    """Sorted, de-duplicated identifiers of ``violations``."""
    return sorted({violation.invariant for violation in violations})


def _violation(invariant: str, detail: str) -> InvariantViolation:
    return InvariantViolation(invariant=invariant, detail=detail)


def _check_inv_01(revision: ProjectRevision) -> list[InvariantViolation]:
    """A memorised bearing task must equal the first strict planning ancestor."""
    violations: list[InvariantViolation] = []
    for line in revision.frozen_lines:
        node = node_by_work_item(revision, line.work_item_id)
        if node is None:
            continue
        expected = bearing_work_item_id(revision, node.id)
        if line.bearing_work_item_id != expected:
            violations.append(
                _violation(
                    "INV-01",
                    f"frozen line for work_item {line.work_item_id} memorises bearing "
                    f"{line.bearing_work_item_id}, but its first planning ancestor is {expected}",
                )
            )
    return violations


def _check_inv_04(revision: ProjectRevision) -> list[InvariantViolation]:
    """``node -> work_item_id`` is injective within a revision."""
    seen: dict[int, int] = {}
    violations: list[InvariantViolation] = []
    for node in sorted(revision.nodes.values(), key=lambda item: item.id):
        first = seen.get(node.work_item_id)
        if first is not None:
            violations.append(
                _violation(
                    "INV-04",
                    f"work_item {node.work_item_id} occupies nodes {first} and {node.id} "
                    f"of revision {revision.id}",
                )
            )
        else:
            seen[node.work_item_id] = node.id
    return violations


def _check_inv_05(revision: ProjectRevision) -> list[InvariantViolation]:
    """Sibling positions are exactly ``{1, ..., n}``, root siblings included."""
    parents: set[int | None] = {None}
    parents.update(node.parent_id for node in revision.nodes.values() if node.parent_id is not None)
    violations: list[InvariantViolation] = []
    for parent_id in sorted(parents, key=lambda value: (value is not None, value or 0)):
        if parent_id is not None and parent_id not in revision.nodes:
            continue
        siblings = children_of(revision, parent_id)
        positions = sorted(node.position for node in siblings)
        if positions != list(range(1, len(siblings) + 1)):
            violations.append(
                _violation(
                    "INV-05",
                    f"children of parent {parent_id} in revision {revision.id} have "
                    f"positions {positions} instead of {list(range(1, len(siblings) + 1))}",
                )
            )
    return violations


def _check_inv_06(revision: ProjectRevision) -> list[InvariantViolation]:
    """Walking ``parent_id`` upwards always reaches a root in finitely many steps."""
    violations: list[InvariantViolation] = []
    for node in sorted(revision.nodes.values(), key=lambda item: item.id):
        seen: set[int] = {node.id}
        current = node
        while current.parent_id is not None:
            parent = revision.nodes.get(current.parent_id)
            if parent is None:
                break  # dangling parent: reported by INV-09, not a cycle
            if parent.id in seen:
                violations.append(
                    _violation(
                        "INV-06",
                        f"node {node.id} of revision {revision.id} is its own ancestor "
                        f"through node {parent.id}",
                    )
                )
                break
            seen.add(parent.id)
            current = parent
    return violations


def _check_inv_08(revision: ProjectRevision) -> list[InvariantViolation]:
    """Both ends of a precedence link belong to this very revision."""
    violations: list[InvariantViolation] = []
    for link in revision.links:
        for label, node_id in (
            ("node", link.node_id),
            ("predecessor", link.predecessor_node_id),
        ):
            if node_id not in revision.nodes:
                violations.append(
                    _violation(
                        "INV-08",
                        f"precedence link {link.node_id}<-{link.predecessor_node_id} "
                        f"names a {label} node {node_id} absent from revision {revision.id}",
                    )
                )
    return violations


def _check_inv_09(revision: ProjectRevision) -> list[InvariantViolation]:
    """A node's parent belongs to the same revision."""
    return [
        _violation(
            "INV-09",
            f"node {node.id} of revision {revision.id} has parent {node.parent_id}, "
            "which is not a node of this revision",
        )
        for node in sorted(revision.nodes.values(), key=lambda item: item.id)
        if node.parent_id is not None and node.parent_id not in revision.nodes
    ]


def _check_inv_10(project: Project, revision: ProjectRevision) -> list[InvariantViolation]:
    """A node's ``work_item`` belongs to the project owning the revision."""
    violations: list[InvariantViolation] = []
    for node in sorted(revision.nodes.values(), key=lambda item: item.id):
        work_item = project.work_items.get(node.work_item_id)
        if work_item is None:
            violations.append(
                _violation(
                    "INV-10",
                    f"node {node.id} names work_item {node.work_item_id}, unknown to "
                    f"project {project.id}",
                )
            )
        elif work_item.project_id != revision.project_id:
            violations.append(
                _violation(
                    "INV-10",
                    f"node {node.id} names work_item {work_item.id} of project "
                    f"{work_item.project_id}, but revision {revision.id} belongs to "
                    f"project {revision.project_id}",
                )
            )
    return violations


def _check_inv_11(revision: ProjectRevision) -> list[InvariantViolation]:
    """Exactly one facet per node: never both, never none."""
    violations: list[InvariantViolation] = []
    for node_id in sorted(revision.nodes):
        plan = is_plan_node(revision, node_id)
        cost = is_cost_node(revision, node_id)
        if plan and cost:
            violations.append(
                _violation("INV-11", f"node {node_id} carries both a plan and a cost facet")
            )
        elif not plan and not cost:
            violations.append(_violation("INV-11", f"node {node_id} carries no facet"))
    return violations


def _check_inv_12(revision: ProjectRevision) -> list[InvariantViolation]:
    """No orphaned facet: every facet references an existing node of the revision."""
    violations: list[InvariantViolation] = []
    for kind, keys in (("plan", revision.plan_facets), ("cost", revision.cost_facets)):
        for node_id, facet in sorted(keys.items()):
            if node_id not in revision.nodes:
                violations.append(
                    _violation(
                        "INV-12",
                        f"{kind} facet references node {node_id}, absent from "
                        f"revision {revision.id}",
                    )
                )
            elif facet.node_id != node_id:
                violations.append(
                    _violation(
                        "INV-12",
                        f"{kind} facet stored under node {node_id} declares "
                        f"node_id {facet.node_id}",
                    )
                )
    return violations


def _check_inv_13(project: Project, revision: ProjectRevision) -> list[InvariantViolation]:
    """The facet carried by a node matches the ``kind`` of its ``work_item``."""
    violations: list[InvariantViolation] = []
    for node_id in sorted(revision.nodes):
        node = revision.nodes[node_id]
        work_item = project.work_items.get(node.work_item_id)
        if work_item is None:
            continue  # reported by INV-10
        expected = WorkItemKind.TASK if is_plan_node(revision, node_id) else WorkItemKind.COST
        if not is_plan_node(revision, node_id) and not is_cost_node(revision, node_id):
            continue  # reported by INV-11
        if work_item.kind is not expected:
            violations.append(
                _violation(
                    "INV-13",
                    f"node {node_id} carries a {expected.value} facet while its work_item "
                    f"{work_item.id} is of kind {work_item.kind.value}",
                )
            )
    return violations


def _check_inv_14(revision: ProjectRevision) -> list[InvariantViolation]:
    """The set of planning nodes is closed upwards: a task never sits under a cost line."""
    return [
        _violation(
            "INV-14",
            f"planning node {node.id} has cost node {node.parent_id} for parent",
        )
        for node in sorted(revision.nodes.values(), key=lambda item: item.id)
        if is_plan_node(revision, node.id)
        and node.parent_id is not None
        and is_cost_node(revision, node.parent_id)
    ]


def _check_inv_15(revision: ProjectRevision) -> list[InvariantViolation]:
    """A planning facet always carries a calendar and a valid calendar source."""
    violations: list[InvariantViolation] = []
    for node_id, facet in sorted(revision.plan_facets.items()):
        if facet.calendar_id is None:
            violations.append(_violation("INV-15", f"plan facet of node {node_id} has no calendar"))
        if not isinstance(facet.calendar_source, CalendarSource):
            violations.append(
                _violation(
                    "INV-15",
                    f"plan facet of node {node_id} has calendar_source {facet.calendar_source!r}",
                )
            )
    return violations


def _check_inv_16(revision: ProjectRevision) -> list[InvariantViolation]:
    """A node is never its own predecessor."""
    return [
        _violation("INV-16", f"node {link.node_id} is its own predecessor")
        for link in revision.links
        if link.node_id == link.predecessor_node_id
    ]


def _check_inv_17(revision: ProjectRevision) -> list[InvariantViolation]:
    """Both ends of a precedence link carry a planning facet."""
    violations: list[InvariantViolation] = []
    for link in revision.links:
        for label, node_id in (
            ("node", link.node_id),
            ("predecessor", link.predecessor_node_id),
        ):
            if node_id in revision.nodes and not is_plan_node(revision, node_id):
                violations.append(
                    _violation(
                        "INV-17",
                        f"precedence link {link.node_id}<-{link.predecessor_node_id} "
                        f"uses non-planning node {node_id} as {label}",
                    )
                )
    return violations


def _check_inv_18(revision: ProjectRevision) -> list[InvariantViolation]:
    """The precedence graph is acyclic."""
    successors: dict[int, list[int]] = {}
    for link in revision.links:
        successors.setdefault(link.predecessor_node_id, []).append(link.node_id)

    state: dict[int, int] = {}  # 1 = visiting, 2 = done
    cycles: list[int] = []

    def visit(node_id: int) -> None:
        marker = state.get(node_id, 0)
        if marker == 1:
            cycles.append(node_id)
            return
        if marker == 2:
            return
        state[node_id] = 1
        for successor in successors.get(node_id, []):
            visit(successor)
        state[node_id] = 2

    for start in sorted(successors):
        visit(start)
    return [
        _violation("INV-18", f"precedence graph of revision {revision.id} cycles on node {node_id}")
        for node_id in sorted(set(cycles))
    ]


def _check_labor_facet(node_id: int, facet: CostFacet) -> list[InvariantViolation]:
    """INV-19 on one facet.

    ``supply_status`` is listed among the forbidden attributes, and not only
    refused by :func:`~waterfall.domain.revision.facets.set_supply_status`:
    stating it on the invariant makes every write of a cost facet -- creation
    included, and whatever route the transport layer adds later -- inherit the
    refusal through :func:`check_cost_facet_shape`, instead of each one guarding
    it again.
    """
    missing = [name for name in ("role_id", "hours") if getattr(facet, name) is None]
    present = [
        name
        for name in ("cost_type_id", "cost_category_id", "unit_cost", "supply_status")
        if getattr(facet, name) is not None
    ]
    violations: list[InvariantViolation] = []
    if missing:
        violations.append(
            _violation("INV-19", f"labor cost facet of node {node_id} is missing {missing}")
        )
    if present:
        violations.append(
            _violation("INV-19", f"labor cost facet of node {node_id} carries {present}")
        )
    return violations


def _check_non_labor_facet(node_id: int, facet: CostFacet) -> list[InvariantViolation]:
    missing = [
        name
        for name in ("cost_type_id", "cost_category_id", "unit_cost")
        if getattr(facet, name) is None
    ]
    present = [name for name in ("role_id", "hours") if getattr(facet, name) is not None]
    violations: list[InvariantViolation] = []
    if missing:
        violations.append(
            _violation("INV-20", f"non-labor cost facet of node {node_id} is missing {missing}")
        )
    if present:
        violations.append(
            _violation("INV-20", f"non-labor cost facet of node {node_id} carries {present}")
        )
    return violations


def check_cost_facet_shape(node_id: int, facet: CostFacet) -> list[InvariantViolation]:
    """INV-19/INV-20 applied to a single cost facet.

    Public so the write operations can refuse an edit *before* applying it,
    rather than letting the checker report the resulting invalid state.
    """
    if facet.nature is CostNature.LABOR:
        return _check_labor_facet(node_id, facet)
    return _check_non_labor_facet(node_id, facet)


def _check_inv_19_and_20(revision: ProjectRevision) -> list[InvariantViolation]:
    """Labour and non-labour cost facets each carry their own attribute set."""
    violations: list[InvariantViolation] = []
    for node_id, facet in sorted(revision.cost_facets.items()):
        violations.extend(check_cost_facet_shape(node_id, facet))
    return violations


def _check_inv_21(project: Project) -> list[InvariantViolation]:
    """Version numbers are unique per project and strictly positive."""
    violations: list[InvariantViolation] = []
    seen: dict[int, int] = {}
    for revision in sorted(project.revisions.values(), key=lambda item: item.id):
        if revision.version_number <= 0:
            violations.append(
                _violation(
                    "INV-21",
                    f"revision {revision.id} has non-positive version_number "
                    f"{revision.version_number}",
                )
            )
        first = seen.get(revision.version_number)
        if first is not None:
            violations.append(
                _violation(
                    "INV-21",
                    f"revisions {first} and {revision.id} of project {project.id} share "
                    f"version_number {revision.version_number}",
                )
            )
        else:
            seen[revision.version_number] = revision.id
    return violations


def _check_inv_22(project: Project) -> list[InvariantViolation]:
    """At most one ``validated`` revision per ``(project, kind)``."""
    validated: dict[str, list[int]] = {}
    for revision in sorted(project.revisions.values(), key=lambda item: item.id):
        if revision.status is RevisionStatus.VALIDATED:
            validated.setdefault(revision.kind.value, []).append(revision.id)
    return [
        _violation(
            "INV-22",
            f"project {project.id} has {len(ids)} validated revisions of kind {kind}: {ids}",
        )
        for kind, ids in sorted(validated.items())
        if len(ids) > 1
    ]


#: Attribute name fragments that would make a frozen line point at mutable structure.
_MUTABLE_REFERENCE_HINTS: Final[tuple[str, ...]] = ("node_id", "facet", "line_id", "row_id")
_FROZEN_LINE_FIELDS: Final[frozenset[str]] = frozenset(field.name for field in fields(FrozenLine))


def _check_inv_23(revision: ProjectRevision) -> list[InvariantViolation]:
    """A frozen line references no mutable structure.

    Checked on the attributes actually carried by each line, not only on the
    declared ones: the canonical violation ("keep the id of the node it came
    from" on a frozen line) is reproduced by attaching such an attribute, and a
    declared field named after a node/facet would be caught by the same rule.
    """
    violations: list[InvariantViolation] = []
    for index, line in enumerate(revision.frozen_lines):
        for name in sorted(vars(line)):
            if any(hint in name for hint in _MUTABLE_REFERENCE_HINTS):
                violations.append(
                    _violation(
                        "INV-23",
                        f"frozen line #{index} of revision {revision.id} references "
                        f"mutable structure through {name!r}",
                    )
                )
            elif name not in _FROZEN_LINE_FIELDS:
                violations.append(
                    _violation(
                        "INV-23",
                        f"frozen line #{index} of revision {revision.id} carries the "
                        f"undeclared attribute {name!r}",
                    )
                )
    return violations


def _check_inv_24(revision: ProjectRevision) -> list[InvariantViolation]:
    """Frozen lines exist for validated/superseded revisions only, one per cost facet."""
    if revision.status is RevisionStatus.DRAFT:
        if revision.frozen_lines:
            return [
                _violation(
                    "INV-24",
                    f"draft revision {revision.id} carries {len(revision.frozen_lines)} "
                    "frozen lines",
                )
            ]
        return []

    expected = {
        revision.nodes[node_id].work_item_id
        for node_id in revision.cost_facets
        if node_id in revision.nodes
    }
    produced = [line.work_item_id for line in revision.frozen_lines]
    if sorted(produced) != sorted(expected):
        return [
            _violation(
                "INV-24",
                f"revision {revision.id} is {revision.status.value} with frozen lines for "
                f"work items {sorted(produced)} but cost facets for {sorted(expected)}",
            )
        ]
    return []


def _check_inv_25(project: Project) -> list[InvariantViolation]:
    """``external_uid`` is null on a cost work item and unique per project otherwise."""
    violations: list[InvariantViolation] = []
    seen: dict[int, int] = {}
    for work_item in sorted(project.work_items.values(), key=lambda item: item.id):
        if work_item.kind is WorkItemKind.COST and work_item.external_uid is not None:
            violations.append(
                _violation(
                    "INV-25",
                    f"cost work_item {work_item.id} carries external_uid {work_item.external_uid}",
                )
            )
        if work_item.external_uid is None:
            continue
        first = seen.get(work_item.external_uid)
        if first is not None:
            violations.append(
                _violation(
                    "INV-25",
                    f"work items {first} and {work_item.id} of project {project.id} share "
                    f"external_uid {work_item.external_uid}",
                )
            )
        else:
            seen[work_item.external_uid] = work_item.id
    return violations


#: Field names of a lotissement entry: the key set an ``asdict`` rendering carries.
_BREAKDOWN_ENTRY_FIELDS: Final[frozenset[str]] = frozenset(
    field.name for field in fields(BreakdownEntry)
)
#: How deep the smuggling walk goes into what a revision carries. Four levels are
#: what it takes to reach a *string field of a dataclass held in a collection* --
#: ``revision.skeleton_fingerprint`` is one level nearer, ``revision.nodes`` one
#: level further -- which is where a serialised lotissement would be hidden.
_SMUGGLING_DEPTH: Final[int] = 4


def _text_holds_entry(text: str, entry: BreakdownEntry) -> bool:
    """Whether ``text`` looks like a *serialised* rendering of ``entry``. **Best effort.**

    Three marks are required together, and the quotes are the discriminating one:
    the serialisations a Python codebase produces by accident -- ``repr``,
    ``json.dumps`` -- quote the name, whereas the perfectly legitimate copy of a
    lot name onto a generated skeleton task is a bare label. Without that, a
    lotissement entry named ``"lot 1 - étude"`` would make the very task generated
    from it look like smuggled content.

    The price of that discriminant is stated rather than hidden: a rendering that
    does **not** quote its names -- CSV, pipe-separated, YAML block, a markdown
    table row, a human sentence, the bare labels -- goes unreported. Measured on
    eight renderings, this catches two. It is a **heuristic on the string shape**,
    not a decision procedure, and widening it would only move the boundary of what
    it misses. What INV-26 *guarantees* is the three structural shapes of
    :func:`_holds_breakdown_entry`.
    """
    quoted = f"'{entry.name}'" in text or f'"{entry.name}"' in text
    return quoted and entry.kind.value in text and str(entry.id) in text


def _row_holds_entry(items: list[object], entry: BreakdownEntry) -> bool:
    """Whether a sequence spells an entry out field by field: ``(1, None, 'lot', 'Lot A')``."""
    strings = {item for item in items if isinstance(item, str)}
    return entry.name in strings and entry.kind.value in strings


def _holds_breakdown_entry(
    value: object, entries: tuple[BreakdownEntry, ...], depth: int = _SMUGGLING_DEPTH
) -> bool:
    """Whether ``value`` carries a lotissement entry, in whatever shape.

    What this **guarantees** are the three *structural* shapes, each decided on
    the shape of the object and not on a guess: a ``BreakdownEntry`` instance, an
    ``id``/``kind``/``name`` mapping, and a field-by-field row. Carrying the
    lotissement as instances is only the most obvious smuggling; the other two are
    the same copy one ``asdict`` away, and a check that knew instances alone would
    declare clean a revision holding either.

    The fourth shape -- a serialised **string** -- is **best effort** and must not
    be read as more: :func:`_text_holds_entry` recognises the quoted renderings a
    Python codebase produces by accident, and misses the unquoted ones. A green
    INV-26 therefore reads as "no entry, mapping or row is carried, and no obvious
    serialisation of one", never as "nothing of the lotissement can possibly be in
    there".

    The three content-based shapes are matched against the lotissement of the
    project, so a revision holding a rendering of a lotissement the project no
    longer has goes unnoticed. That is a limitation of comparing to a content, not
    a hole to plug here: the canonical violation is the copy made *at generation
    time*, and the project holds the lotissement then.
    """
    if isinstance(value, BreakdownEntry):
        return True
    if depth <= 0:
        return False
    if isinstance(value, str):
        return any(_text_holds_entry(value, entry) for entry in entries)
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        if {key for key in mapping if isinstance(key, str)} >= _BREAKDOWN_ENTRY_FIELDS:
            return True
        return any(_holds_breakdown_entry(item, entries, depth - 1) for item in mapping.values())
    if isinstance(value, list | tuple | set | frozenset):
        items = list(cast(Iterable[object], value))
        if any(_row_holds_entry(items, entry) for entry in entries):
            return True
        return any(_holds_breakdown_entry(item, entries, depth - 1) for item in items)
    if is_dataclass(value) and not isinstance(value, type):
        return any(
            _holds_breakdown_entry(item, entries, depth - 1) for item in vars(value).values()
        )
    return False


def _check_inv_26(project: Project, revision: ProjectRevision) -> list[InvariantViolation]:
    """The lotissement is project data: no revision carries any part of it.

    Checked on the attributes each revision actually carries, like INV-23, and not
    only on the declared fields: the canonical violation is to copy the
    lotissement onto the revision at generation time, which is exactly what would
    make a validated revision freeze it. What a revision may carry is the
    **empreinte** of the skeleton generated from the lotissement, and an empreinte
    only -- hence a non-reversible digest of it, which none of the shapes below
    matches.

    Reported with certainty: an entry instance, an ``id``/``kind``/``name``
    mapping, a field-by-field row. Reported best effort: a serialised string, of
    which :func:`_text_holds_entry` recognises the quoted renderings only. A green
    INV-26 is not a proof that no rendering of the lotissement is carried.
    """
    return [
        _violation(
            "INV-26",
            f"revision {revision.id} carries lotissement entries through {name!r}: the "
            "lotissement is project data, which a validated revision must not freeze",
        )
        for name in sorted(vars(revision))
        if _holds_breakdown_entry(vars(revision)[name], project.work_breakdown)
    ]


def _check_inv_27(revision: ProjectRevision) -> list[InvariantViolation]:
    """A task marked as a milestone carries no child, of either facet."""
    return [
        _violation(
            "INV-27",
            f"milestone node {node.parent_id} has child node {node.id}",
        )
        for node in sorted(revision.nodes.values(), key=lambda item: item.id)
        if node.parent_id is not None and is_milestone_node(revision, node.parent_id)
    ]


def check_project_scope(project: Project) -> list[InvariantViolation]:
    """Invariants asserted on the project as a whole (INV-21, INV-22, INV-25)."""
    return [*_check_inv_21(project), *_check_inv_22(project), *_check_inv_25(project)]


def check_revision_scope(project: Project, revision: ProjectRevision) -> list[InvariantViolation]:
    """Invariants asserted on one revision state."""
    return [
        *_check_inv_01(revision),
        *_check_inv_04(revision),
        *_check_inv_05(revision),
        *_check_inv_06(revision),
        *_check_inv_08(revision),
        *_check_inv_09(revision),
        *_check_inv_10(project, revision),
        *_check_inv_11(revision),
        *_check_inv_12(revision),
        *_check_inv_13(project, revision),
        *_check_inv_14(revision),
        *_check_inv_15(revision),
        *_check_inv_16(revision),
        *_check_inv_17(revision),
        *_check_inv_18(revision),
        *_check_inv_19_and_20(revision),
        *_check_inv_23(revision),
        *_check_inv_24(revision),
        *_check_inv_26(project, revision),
        *_check_inv_27(revision),
    ]


def check_invariants(project: Project, revision: ProjectRevision) -> list[InvariantViolation]:
    """Every ``état``-scoped invariant violated by ``revision`` inside ``project``.

    Returns an empty list on a sound state. The project-scoped invariants
    (INV-21, INV-22, INV-25) are included because they constrain the very
    project this revision belongs to.
    """
    return [*check_project_scope(project), *check_revision_scope(project, revision)]


def check_all_invariants(project: Project) -> list[InvariantViolation]:
    """Every ``état``-scoped invariant violated anywhere in ``project``."""
    violations = check_project_scope(project)
    for revision in sorted(project.revisions.values(), key=lambda item: item.id):
        violations.extend(check_revision_scope(project, revision))
    return violations
