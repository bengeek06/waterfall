from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from waterfall.domain.revision import RevisionKind, RevisionStatus
from waterfall.models.ms_core import MsProject
from waterfall.models.planning import WfPlanningTaskSnapshot
from waterfall.models.revision import ProjectRevision, ProjectRevisionPointer

READ_ONLY_PROJECT_STATUSES = frozenset({"perdu", "termine", "abandonne"})

#: Which validated revision becomes the project's reference, most engaging first.
#:
#: A ``forecast_remaining`` is deliberately absent: a reste à engager is measured
#: *against* the reference budget and can never be it. Between the two that remain,
#: a signed contract outranks the initial estimate, which is what "budget de
#: référence" means -- and INV-22 guarantees at most one validated revision per
#: kind, so this order picks one row and never arbitrates between two.
#:
#: Spelled with the domain enumeration rather than with bare strings: the two
#: vocabularies -- what `ck_wf_revision_kind` allows and what
#: ``domain.RevisionKind`` names -- are one vocabulary, and a tuple of literals here
#: would let a rename of the enumeration pass without a single failing check while
#: quietly ceasing to match any row.
REFERENCE_REVISION_KINDS: tuple[RevisionKind, ...] = (
    RevisionKind.CONTRACT_REFERENCE,
    RevisionKind.INITIAL,
)


def ensure_project_mutable(project: MsProject) -> None:
    if project.status in READ_ONLY_PROJECT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project is read-only in its current status",
        )


def _referenced_planning_has_structure(db: Session, project: MsProject) -> bool:
    """Whether the project's currently referenced planning has any task.

    Scoped to ``project.planning_reference_id`` specifically (not "any
    planning the project ever had"), since that is the planning that will
    actually become active when the project reaches ``en_cours``.
    """
    if project.planning_reference_id is None:
        return False
    return (
        db.query(WfPlanningTaskSnapshot.id)
        .filter(WfPlanningTaskSnapshot.planning_id == project.planning_reference_id)
        .first()
        is not None
    )


def reference_revision_candidate(db: Session, project_id: int) -> ProjectRevision | None:
    """The validated revision a project entering ``en_cours`` would be run against.

    ``None`` when the project has none, which is not an error at this point of the
    EPIC: the legacy planning/devis references are still live and still the only
    thing most projects carry, so the transition falls back on them (see
    :func:`validate_project_status_transition`). E14-12 (#339) is where that fallback
    goes and this becomes the single answer.

    **Read under the caller's row lock.** This query is not locked itself, and it
    must not be reached without `ms_project` already held ``FOR UPDATE``: a
    concurrent ``POST .../validate`` supersedes the very row selected here, and the
    two composite foreign keys of `wf_project_revision_pointer` guarantee that a
    project points at a revision *of its own*, not that it points at a **validated**
    one. Every caller goes through :func:`enter_status`, and every route reaching
    :func:`enter_status` takes that lock (`project_access.get_mutable_project_lock`).
    """
    validated = {
        RevisionKind(row.kind): row
        for row in db.query(ProjectRevision)
        .filter(
            ProjectRevision.project_id == project_id,
            ProjectRevision.status == RevisionStatus.VALIDATED.value,
        )
        .order_by(ProjectRevision.id)
        .all()
    }
    for kind in REFERENCE_REVISION_KINDS:
        candidate = validated.get(kind)
        if candidate is not None:
            return candidate
    return None


def set_reference_revision(db: Session, project_id: int, revision_id: int) -> None:
    """Point the project at its reference revision -- **one column, one write**.

    What replaces "make ``planning_reference_id`` and ``reference_estimate_id``
    agree, and make the estimate's own ``planning_id`` agree with both". There is one
    revision carrying both facets, so there is one pointer, and the state where a
    reference planning and a reference devis designate different versions is not
    refused here: it has no shape to be written in (EPIC #326).

    ``wf_project_revision_pointer`` holds at most one row per project and is created
    on first use; ``fk_wf_project_revision_pointer_reference`` matches
    ``(project_id, revision_id)`` against ``wf_revision(project_id, id)``, so a
    revision of somebody else's project is refused by the database itself.
    """
    _pointer(db, project_id).reference_revision_id = revision_id


def set_displayed_revision(db: Session, project_id: int, revision_id: int) -> None:
    """Point the project at the revision being worked on.

    A ``NULL`` here means "show the reference": this column names the draft the user
    has open, never a second copy of the reference. Written when a draft is created
    from another revision, which is the moment the answer to "what am I looking at?"
    changes.
    """
    _pointer(db, project_id).displayed_revision_id = revision_id


def clear_displayed_revision(db: Session, project_id: int, revision_id: int) -> None:
    """Stop displaying ``revision_id``, if that is what the project was displaying.

    Called when a revision is validated: :attr:`displayed_revision_id` names *the
    draft being worked on*, and a validated revision is not one -- every write on it
    now answers ``REVISION_IMMUTABLE``. Leaving it there would have the project point
    at a revision the only possible next action on is ``POST .../copy``, and ``NULL``
    already has the meaning wanted ("show the reference").

    Creates **no** row, unlike :func:`_pointer`: a project that never displayed
    anything has nothing to stop displaying, and writing an all-null pointer row to
    record that would be recording an absence.

    Scoped to the revision the caller names, so that validating revision 4 while
    revision 5 is the one on screen leaves the screen alone.
    """
    pointer = db.get(ProjectRevisionPointer, project_id)
    if pointer is None or pointer.displayed_revision_id != revision_id:
        return
    pointer.displayed_revision_id = None


def _pointer(db: Session, project_id: int) -> ProjectRevisionPointer:
    """The project's pointer row, created empty on first use and flushed.

    ``updated_at`` is not touched here: the column carries ``onupdate`` and the ORM
    maintains it on every flush that changes the row, which is what keeps the three
    functions above from each having to remember (see
    :class:`~waterfall.models.revision.ProjectRevisionPointer`).
    """
    pointer = db.get(ProjectRevisionPointer, project_id)
    if pointer is None:
        pointer = ProjectRevisionPointer(project_id=project_id)
        db.add(pointer)
        db.flush()
    return pointer


def validate_project_status_transition(
    db: Session,
    project: MsProject,
    new_status: str,
) -> ProjectRevision | None:
    """Refuse an illegal transition, and answer the reference it would fix on.

    Returns the validated revision the project would be run against -- ``None`` for
    every transition other than the one into ``en_cours``, and ``None`` there too for
    a project still riding the legacy planning/devis pair. Returning it rather than
    discarding it is what lets :func:`enter_status` fix the pointer without asking
    the database the *same question twice* per transition, which is what it did
    before (#334 review, B5). Callers that only want the refusal ignore the value,
    as the legacy planning routes do.
    """
    if new_status == project.status:
        return None
    if project.status in READ_ONLY_PROJECT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived project statuses cannot transition",
        )
    allowed = {
        "cree": {"initialise", "perdu", "abandonne"},
        "initialise": {"en_reponse_appel_offre", "perdu", "abandonne"},
        "en_reponse_appel_offre": {"en_cours", "perdu", "abandonne"},
        "en_cours": {"termine", "abandonne"},
    }
    if new_status not in allowed.get(project.status, set()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid project status transition: {project.status} -> {new_status}",
        )
    if new_status != "en_cours":
        return None
    return _require_something_to_reference(db, project)


def _require_something_to_reference(db: Session, project: MsProject) -> ProjectRevision | None:
    """A project only runs against a reference, and there are two shapes of one here.

    A **validated revision** is the one this EPIC installs, and it is checked first:
    a project built on the node model carries no `wf_planning` and no `wf_estimate`
    at all, so the legacy conditions below could never be met by it.

    The legacy pair -- a reference planning with a structure *and* a reference devis
    -- stays in force for every project that has no validated revision, because at
    this point of the EPIC the old socle is still live and still the only thing those
    projects have. That is exactly the fallback E14-12 (#339) removes, along with the
    three columns it reads.
    """
    candidate = reference_revision_candidate(db, project.id)
    if candidate is not None:
        return candidate
    if project.planning_reference_id is None or project.reference_estimate_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project requires planning and estimate references before en_cours",
        )
    if not _referenced_planning_has_structure(db, project):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project requires a planning structure before en_cours",
        )
    return None


def enter_status(db: Session, project: MsProject, new_status: str) -> None:
    """Move ``project`` to ``new_status``, fixing its reference revision on the way in.

    The single place a project is *moved* to a status, so that "entering ``en_cours``
    fixes the reference revision" holds whichever route was called -- ``PATCH
    /projects/{id}`` and ``PATCH /projects/{id}/status`` both land here, and a third
    one would too. The pointer is set in the same unit of work as the status, on the
    same transaction: there is no window in which a project is ``en_cours`` with
    nothing to run against.

    A status a project already has is not a transition and is left alone entirely,
    reference included -- see the body.

    The legacy planning routes still call :func:`validate_project_status_transition`
    on their own and assign ``status`` themselves, which is sound: the only
    transition they make is ``cree -> initialise``, where there is no reference to
    fix. They go with those routes, in E14-12 (#339).
    """
    reference = validate_project_status_transition(db, project, new_status)
    if new_status == project.status:
        # Not a transition, so not an entry: re-sending the status a project already
        # has must not re-fix its reference. A project that entered `en_cours` on
        # revision 2 and has validated revision 3 since would otherwise see its
        # reference *move* -- silently, on a request that changes nothing else.
        return
    project.status = new_status
    # The single revision the check above already resolved, under the caller's row
    # lock and in the same transaction: asking again would be a second query, and a
    # second query is a second answer.
    if reference is not None:
        set_reference_revision(db, project.id, reference.id)
