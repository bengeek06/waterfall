"""The single translation of a revision failure into an HTTP response (E14-05, #331).

:mod:`waterfall.services.revision_tree` knows no HTTP status code, by design, and
:mod:`waterfall.domain.revision` knows even less. Somebody has to decide, and this
module is that somebody -- for the planning facet (#331) **and** for the cost facet
(#333), which reuses it verbatim rather than growing a second table that could
drift from this one.

Why one place and not one ``except`` chain per route
----------------------------------------------------

Three exception families reach a route, and one invariant crosses two of them:
INV-03 -- "a validated revision refuses every write" -- is raised as a
:class:`~waterfall.domain.revision.ImmutableRevisionError` by the domain guard and
by the tree service's own ``_claim_revision``, and as a
:class:`~waterfall.services.revision_store.FrozenRevisionError` by the store's
last-ditch refusal. The three messages differ; the refusal does not. A route
catching ``RevisionStoreError`` and answering "conflict" would fold INV-03 in with
refusals that have nothing to do with it (a node the tree cannot reach, a position
parked in the renumbering band), and a route catching only
``ImmutableRevisionError`` would miss a third of it. Both classes are listed
against the *same* code here, once, which is what makes the acceptance criterion of
#331 -- "a write on a validated revision is refused **with the same error** on
either facet" -- a property of the code rather than of two route authors agreeing.

The error codes are the contract
--------------------------------

Every response built here carries a structured ``detail`` with a machine-readable
``code``: :func:`waterfall.main._generic_http_exception_handler` rewrites a *string*
``detail`` into ``{"code": "GENERIC_ERROR"}`` precisely so that untranslated English
never reaches a client, so a code is the only thing a frontend can act on. No
free-text message is included for the same reason.

The table below is the contract, and
``test_revision_planning_api.test_every_emitted_error_code_is_documented_in_the_contract``
holds it to it: every code this module can emit -- plus the two the routes emit
about the *project* -- has to appear in the OpenAPI description of the response it
comes back on, and no description may cite a code nothing emits. A frontend builds
its translation table off those descriptions.

The table is itself asserted, by
``test_revision_planning_api.test_the_docstring_table_is_the_inventory_it_claims_to_be``:
it presents itself as the inventory of reference, so a code added to
``_TRANSLATIONS`` and to the OpenAPI description but not here would leave a
silently incomplete reference -- and #333 adds a great many codes.

======================================  ======  ==================================
Failure                                 Status  ``detail.code``
======================================  ======  ==================================
optimistic lock lost                    409     ``REVISION_LOCK_CONFLICT``
validated/superseded revision (INV-03)  409     ``REVISION_IMMUTABLE``
no such revision                        404     ``REVISION_NOT_FOUND``
no such node / work item / facet        404     ``REVISION_NODE_NOT_FOUND``
no default calendar to inherit          409     ``PROJECT_CALENDAR_MISSING``
work item already in the revision       409     ``REVISION_DUPLICATE_WORK_ITEM``
external uid already taken              409     ``REVISION_EXTERNAL_UID_CONFLICT``
lifecycle rule broken                   409     ``REVISION_LIFECYCLE_CONFLICT``
concurrency refusal of the tree service 409     ``REVISION_WRITE_REFUSED``
constraint this layer does not restate  409     ``REVISION_INTEGRITY_CONFLICT``
selection cannot be moved that way      400     ``REVISION_SELECTION_INVALID``
position outside the sibling range      400     ``REVISION_POSITION_INVALID``
move would create a cycle               400     ``REVISION_TREE_CYCLE``
task would land under a cost line       400     ``REVISION_FACET_PLACEMENT_INVALID``
node under a milestone (INV-27)         400     ``REVISION_MILESTONE_HAS_CHILDREN``
node of another revision                400     ``REVISION_CROSS_REVISION``
invalid precedence link                 400     ``REVISION_LINK_INVALID``
facet shape contract broken             400     ``REVISION_FACET_CONTRACT``
work item of another project            400     ``REVISION_PROJECT_MISMATCH``
lotissement / skeleton rule broken      400     ``REVISION_WORK_BREAKDOWN_INVALID``
unusable imported structure             400     ``REVISION_IMPORT_STRUCTURE_INVALID``
any other domain refusal                400     ``REVISION_REFUSED``
======================================  ======  ==================================

Two further codes are decided by :mod:`waterfall.api.routes.revisions` itself,
because they are about the *project* and not about the revision:
``PROJECT_NOT_FOUND`` (404) and ``PROJECT_READ_ONLY`` (409).

What is deliberately **absent** from the table: a bare
:class:`~waterfall.services.revision_store.RevisionStoreError`
--------------------------------------------------------------

The seven sites that raise one describe states a client can neither provoke nor
repair: a node no root reaches, an orphaned facet, a link whose endpoint is gone, a
``work_item`` whose ``kind`` changed under the revision. Answering 409 would tell a
client "conflict, re-read and replay", and replaying would fail forever -- a retry
loop on a permanent condition, and an incident nobody is paged for. So this module
rolls the transaction back (releasing the row lock, which is the part that must
happen whatever the failure) and lets the exception through as a 500. Its three
*specific* subclasses -- ``RevisionNotFoundError``, ``FrozenRevisionError``,
``MissingProjectCalendarError`` -- are genuine client-visible conditions and stay in
the table above. :class:`sqlalchemy.exc.DataError` is absent for the same reason and
handled the same way: a value the column cannot hold means a write payload lost the
bound it is supposed to carry, which is a bug of this repository rather than a
condition to publish -- so a 500, but a 500 with the lock let go. See
:data:`RevisionFailure`.

400 rather than 422 for the refusals in the lower half: it is what this repository
already answers on the very same refusals (an invalid move on a planning is a 400
today, see the route this issue replaces), and it leaves FastAPI's own 422 meaning
one thing only -- "the request body did not parse" -- which is why these routes need
none of the 422-to-400 route-class override the legacy planning routes carry.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from fastapi import HTTPException, status
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from waterfall.domain import revision as domain
from waterfall.services.revision_store import (
    FrozenRevisionError,
    MissingProjectCalendarError,
    RevisionNotFoundError,
    RevisionStoreError,
)
from waterfall.services.revision_tree import RevisionLockConflictError, RevisionTreeError

#: Stable code of INV-03, named once so #333 reuses the constant rather than the
#: string. Covers ``validated`` and ``superseded`` alike: neither accepts a write,
#: and a client's remedy is the same for both -- copy the revision.
REVISION_IMMUTABLE = "REVISION_IMMUTABLE"

#: ``(exception class, status, code)``, scanned **in order**, first match wins.
#:
#: The order is the whole content of this table, not incidental: several entries
#: are subclasses of later ones (``RevisionLockConflictError`` under
#: ``RevisionTreeError``, every domain error under ``RevisionDomainError``), so the
#: specific ones must come first or they would never be reached. The
#: ``RevisionDomainError`` catch-all is deliberate: a domain error added later gets
#: a defensible 400 instead of escaping as a 500, and shows up in a test as a
#: missing code rather than as an incident.
#:
#: The three store errors are listed **individually** and their base class is not
#: listed at all, so a refusal this table does not name escapes as a 500 -- see the
#: module docstring on why a corrupted stored state is not a 409.
_TRANSLATIONS: tuple[tuple[type[Exception], int, str], ...] = (
    (RevisionLockConflictError, status.HTTP_409_CONFLICT, "REVISION_LOCK_CONFLICT"),
    # INV-03, from the two classes it comes out under -- see the module docstring.
    (domain.ImmutableRevisionError, status.HTTP_409_CONFLICT, REVISION_IMMUTABLE),
    (FrozenRevisionError, status.HTTP_409_CONFLICT, REVISION_IMMUTABLE),
    (RevisionNotFoundError, status.HTTP_404_NOT_FOUND, "REVISION_NOT_FOUND"),
    (domain.NotFoundError, status.HTTP_404_NOT_FOUND, "REVISION_NODE_NOT_FOUND"),
    (MissingProjectCalendarError, status.HTTP_409_CONFLICT, "PROJECT_CALENDAR_MISSING"),
    (domain.DuplicateWorkItemError, status.HTTP_409_CONFLICT, "REVISION_DUPLICATE_WORK_ITEM"),
    (domain.ExternalUidError, status.HTTP_409_CONFLICT, "REVISION_EXTERNAL_UID_CONFLICT"),
    (domain.RevisionLifecycleError, status.HTTP_409_CONFLICT, "REVISION_LIFECYCLE_CONFLICT"),
    (domain.SelectionError, status.HTTP_400_BAD_REQUEST, "REVISION_SELECTION_INVALID"),
    (domain.PositionError, status.HTTP_400_BAD_REQUEST, "REVISION_POSITION_INVALID"),
    (domain.TreeCycleError, status.HTTP_400_BAD_REQUEST, "REVISION_TREE_CYCLE"),
    (
        domain.FacetPlacementError,
        status.HTTP_400_BAD_REQUEST,
        "REVISION_FACET_PLACEMENT_INVALID",
    ),
    (
        domain.MilestoneChildError,
        status.HTTP_400_BAD_REQUEST,
        "REVISION_MILESTONE_HAS_CHILDREN",
    ),
    (domain.CrossRevisionError, status.HTTP_400_BAD_REQUEST, "REVISION_CROSS_REVISION"),
    (domain.LinkError, status.HTTP_400_BAD_REQUEST, "REVISION_LINK_INVALID"),
    (domain.FacetContractError, status.HTTP_400_BAD_REQUEST, "REVISION_FACET_CONTRACT"),
    (domain.ProjectMismatchError, status.HTTP_400_BAD_REQUEST, "REVISION_PROJECT_MISMATCH"),
    (
        domain.WorkBreakdownError,
        status.HTTP_400_BAD_REQUEST,
        "REVISION_WORK_BREAKDOWN_INVALID",
    ),
    (
        domain.ImportStructureError,
        status.HTTP_400_BAD_REQUEST,
        "REVISION_IMPORT_STRUCTURE_INVALID",
    ),
    (domain.RevisionDomainError, status.HTTP_400_BAD_REQUEST, "REVISION_REFUSED"),
    (RevisionTreeError, status.HTTP_409_CONFLICT, "REVISION_WRITE_REFUSED"),
    # Last, and reached only by an ``IntegrityError``: a constraint this layer does
    # not restate refused the write, which is a conflict with stored data rather
    # than a malformed request -- the 409 the rest of this API already answers.
    (IntegrityError, status.HTTP_409_CONFLICT, "REVISION_INTEGRITY_CONFLICT"),
)

#: The exceptions :func:`revision_operation` rolls the session back for. Wider than
#: what :func:`revision_http_exception` translates, on purpose: a bare
#: ``RevisionStoreError`` is an incident and must reach the 500 handler, but it must
#: reach it with the row lock released all the same -- see the module docstring.
#:
#: ``DataError`` is here for that reason and no other (#331 review, B3). It is the one
#: failure the request layer is supposed to make unreachable -- every numeric field of
#: every write payload is bounded by the column it lands in, see
#: :mod:`waterfall.schemas.revisions` -- so listing it is not a translation (it has no
#: entry in ``_TRANSLATIONS`` and stays a 500, which is what an unreachable state
#: deserves) but the admission that a missed bound is a bug, and that a bug must not
#: also strand a ``FOR UPDATE`` lock on the way out. Narrower than its common parent
#: ``DatabaseError`` on purpose: an ``OperationalError`` is a connection that may not
#: survive the ``rollback()`` this would call on it.
RevisionFailure = (
    domain.RevisionDomainError,
    RevisionStoreError,
    RevisionTreeError,
    IntegrityError,
    DataError,
)


def revision_http_exception(exc: Exception) -> HTTPException:
    """Translate one revision failure into the response it deserves.

    Raises the exception back, unchanged, when nothing in :data:`_TRANSLATIONS`
    matches. There is no catch-all status here: dressing an unrecognised exception
    up as a 409 would publish "re-read and replay" for a condition replaying cannot
    fix, and would hide a bug behind a client error. ``IntegrityError`` is a listed
    entry rather than that catch-all, so its 409 is a decision and not a leftover.
    """
    if isinstance(exc, RevisionLockConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REVISION_LOCK_CONFLICT",
                "revision_id": exc.revision_id,
                "expected_lock_version": exc.expected_lock_version,
                "current_lock_version": exc.current_lock_version,
            },
        )
    for error_type, status_code, code in _TRANSLATIONS:
        if isinstance(exc, error_type):
            return HTTPException(status_code=status_code, detail={"code": code})
    raise exc


@contextmanager
def revision_operation(db: Session) -> Generator[None]:
    """Run a revision read or write, translating any refusal it raises.

    Rolls the session back before raising, which matters more here than it looks:
    :func:`~waterfall.services.revision_tree._claim_revision` takes a row lock that
    is held until the transaction ends, and
    :func:`~waterfall.services.revision_store.save_revision` flushes as it goes --
    so a refusal that left the transaction open would keep the lock *and* whatever
    the flush had already written. That is why the rollback covers failures this
    module does **not** translate: an untranslated one still has to let go of the
    lock on its way to the 500 handler.
    """
    try:
        yield
    except RevisionFailure as exc:
        db.rollback()
        raise revision_http_exception(exc) from exc
