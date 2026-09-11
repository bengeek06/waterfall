"""Write guards shared by every mutating operation of the revision domain."""

from __future__ import annotations

from waterfall.domain.revision.entities import ProjectRevision, RevisionStatus
from waterfall.domain.revision.errors import ImmutableRevisionError


def require_draft(revision: ProjectRevision) -> None:
    """Refuse any write on a ``validated`` or ``superseded`` revision (INV-03).

    Raised with the *same* error whatever the facet being written -- tree,
    planning, cost, precedence links or frozen lines -- and always before any
    mutation, so the revision (``lock_version`` included) is left rigorously
    unchanged by a refused attempt.
    """
    if revision.status is not RevisionStatus.DRAFT:
        raise ImmutableRevisionError(
            f"Revision {revision.id} is {revision.status.value} and refuses every write; "
            "create a draft copy of it to make any change"
        )


def touch(revision: ProjectRevision) -> None:
    """Bump the optimistic lock counter after a successful write."""
    revision.lock_version += 1
