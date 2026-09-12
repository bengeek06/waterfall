"""Domain exceptions of the revision model (E14-02).

Every failure raised by this package is one of these types: no ``HTTPException``,
no HTTP status code, no SQLAlchemy error. The transport layer (E14-04 onwards) is
responsible for mapping them onto 400/404/409/422 responses.

Each exception documents the invariant of ``docs/revision-v0.1-specification.md``
it protects. Operations refuse an edit that *would* violate an invariant rather
than producing an invalid state for
:func:`waterfall.domain.revision.invariants.check_invariants` to report after the
fact.
"""

from __future__ import annotations


class RevisionDomainError(Exception):
    """Base class for every error raised by the revision domain."""


class NotFoundError(RevisionDomainError):
    """An entity addressed by an operation does not exist in the given state."""


class ImmutableRevisionError(RevisionDomainError):
    """A write was attempted on a ``validated`` or ``superseded`` revision (INV-03)."""


class DuplicateWorkItemError(RevisionDomainError):
    """A ``work_item`` would appear twice in the same revision (INV-04)."""


class PositionError(RevisionDomainError):
    """A requested position falls outside the target sibling range (INV-05)."""


class TreeCycleError(RevisionDomainError):
    """A move would make a node its own ancestor (INV-06)."""


class SelectionError(RevisionDomainError):
    """A selection cannot be moved the way the command asks.

    Not an invariant violation by itself -- an empty selection, a selection
    spanning several parents for an indent/outdent, a first sibling with nothing
    to indent under, a root node with nothing to outdent to.
    """


class CrossRevisionError(RevisionDomainError):
    """An edge would cross a revision boundary (INV-08, INV-09)."""


class ProjectMismatchError(RevisionDomainError):
    """A ``work_item`` of another project was used in this revision (INV-10)."""


class FacetContractError(RevisionDomainError):
    """A facet does not satisfy its own shape contract.

    Covers INV-11 (exactly one facet per node), INV-13 (facet nature matches the
    ``work_item`` kind), INV-15 (a plan facet always carries a calendar), INV-19
    and INV-20 (labor vs non-labor attribute sets).
    """


class FacetPlacementError(RevisionDomainError):
    """A plan node would end up under a cost node (INV-14)."""


class MilestoneChildError(RevisionDomainError):
    """A node would end up under a task marked as a milestone (INV-27).

    Raised whatever the facet of the child -- a jalon carries *no* child, neither
    a sub-task nor a cost line -- and whatever the way the child would get there:
    an insertion, a move, an indentation, a re-import, or marking a task that
    already has children as a milestone.
    """


class LinkError(RevisionDomainError):
    """A precedence link is invalid (INV-16, INV-17, INV-18)."""


class RevisionLifecycleError(RevisionDomainError):
    """A revision lifecycle rule was broken (INV-21, INV-22, INV-24)."""


class ExternalUidError(RevisionDomainError):
    """An ``external_uid`` rule was broken (INV-25)."""


class WorkBreakdownError(RevisionDomainError):
    """A lotissement or skeleton rule was broken (INV-26, Règle 4).

    A lotissement that cannot be read as a tree, a skeleton asked for on a
    revision that already holds nodes, or a regeneration asked for on a tree that
    was touched since it was generated. Never raised for "the revision is
    validated": that one stays an :class:`ImmutableRevisionError` (INV-03).
    """


class ImportStructureError(RevisionDomainError):
    """The structure of an imported file is not usable as a tree.

    Raised by :func:`~waterfall.domain.revision.reimport.plan_reimport` on a file
    whose parent links the revision cannot follow, although every uid involved is
    known:

    * the file names as a parent a task it does not itself list -- applying it
      would reparent a surviving task under a node the same import destroys, and
      would therefore silently take away chiffrage the confirmed diff never
      announced (Rule 3's safeguard);
    * the file lists a child *before* its parent, which a depth-first MSPDI export
      never does and which is not reordered silently.

    A parent no one knows at all is a :class:`NotFoundError` instead: the
    distinction is what lets the transport layer answer 422 on a malformed file
    and 404 only on a genuinely missing entity.
    """
