"""Reads and edits the legacy task tree of a project, for the tests that still observe it.

E14-05 (#331) removed ``GET /projects/{project_id}/tasks``: the planning is read on
the revision tree now (``GET /projects/{id}/revisions/{id}/nodes``). But the tables
that endpoint read -- `ms_task` and `wf_planning_task_snapshot` -- are still the
ones the MS Project import, the XML export, the skeleton generation and the devis
write, until E14-06 (#332) and E14-07 (#333) move them onto the revision node.

So the *behaviours* those suites pin are untouched by this issue, only the window
they looked through closed. This helper is that window, reopened at the service
layer: displayed planning first, `ms_task` as the fallback, depth-first order and
``row_number`` from the same two helpers the route used. E14-12 (#339) removes it
along with the tables it reads.

How faithful it is, precisely
-----------------------------

The route's two guards are :func:`~waterfall.api.routes.project_access.get_project_or_404`
(the project exists **and** the caller owns it) and
:func:`~waterfall.api.routes.project_access.get_planning_or_404` (the planning
belongs to that project). The planning scoping is reproduced unconditionally. The
ownership filter needs an owner, which these suites do not hold -- they authenticate
through headers and never learn the user id -- so it is applied when, and only when,
a caller passes ``owner_id``; ``test_projects_api`` does, which is what keeps the
check exercised on this path rather than merely claimed. Every other caller reads
back a project it created itself one line earlier, where ownership is not what is
under test.

Deliberately not named ``test_*.py`` (same reasoning as ``_postgres_support.py``):
pytest would otherwise collect it as a test module.
"""

from __future__ import annotations

from typing import Any

from waterfall.api.routes.planning_support import (
    _planning_detail,  # pyright: ignore[reportPrivateUsage]
    _to_task_reads,  # pyright: ignore[reportPrivateUsage]
)
from waterfall.api.routes.project_access import get_planning_or_404, get_project_or_404
from waterfall.db.session import get_session_factory
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanning
from waterfall.schemas.projects import (
    PlanningTaskCreate,
    PlanningTaskDelete,
    PlanningTaskMove,
    TaskRead,
)
from waterfall.services import create_planning_task, delete_planning_tasks, move_planning_tasks


def legacy_project_tasks(
    project_id: int, planning_id: int | None = None, *, owner_id: int | None = None
) -> list[dict[str, Any]]:
    """The task list the removed endpoint returned, as JSON-shaped dicts.

    ``planning_id`` selects a planning explicitly, exactly as the endpoint's query
    parameter did; left out, the project's displayed planning is used, and failing
    that the project's `ms_task` rows. ``owner_id`` runs the route's ownership
    filter -- see the module docstring on when it is supplied.
    """
    return [
        task.model_dump(mode="json")
        for task in legacy_project_task_reads(project_id, planning_id, owner_id=owner_id)
    ]


def legacy_project_task_reads(
    project_id: int, planning_id: int | None = None, *, owner_id: int | None = None
) -> list[TaskRead]:
    """:func:`legacy_project_tasks`, as the Pydantic objects rather than dicts.

    Raises the route's own :class:`fastapi.HTTPException` (404) when ``owner_id`` is
    given and does not own the project, or when the named planning is not this
    project's -- the two refusals the removed endpoint answered.
    """
    with get_session_factory()() as session:
        if owner_id is not None:
            project = get_project_or_404(session, project_id, owner_id)
        else:
            found = session.get(MsProject, project_id)
            assert found is not None, f"project {project_id} does not exist"
            project = found
        selected_id = planning_id or project.displayed_planning_id
        if selected_id is not None:
            planning = get_planning_or_404(session, project_id, selected_id)
            return _planning_detail(session, planning).tasks
        tasks = session.query(MsTask).filter(MsTask.project_id == project_id).all()
        return _to_task_reads(session, project_id, tasks)


def create_legacy_planning_task(
    project_id: int,
    planning_id: int,
    *,
    name: str,
    target_parent_uid: int | None = None,
    insert_after_uid: int | None = None,
) -> dict[str, Any]:
    """Add a task to a legacy draft planning, as ``POST .../plannings/{id}/tasks`` did.

    Same reason as :func:`legacy_project_tasks`, one layer down: the endpoint is
    gone (E14-05, #331) but ``services.create_planning_task`` is not -- it still
    serves the devis (``api/routes/estimates.py``) and is removed by E14-12 (#339).
    What the tests below still need it for is a *fixture* step, not the endpoint
    itself: proving that regenerating the skeleton preserves a task the skeleton
    did not generate needs such a task to exist first.

    Reproduces the route's own sequence, bumping the optimistic counter and
    returning the same ``PlanningDetailRead`` body.
    """
    with get_session_factory()() as session:
        planning = (
            session.query(WfPlanning)
            .filter(WfPlanning.id == planning_id, WfPlanning.project_id == project_id)
            .one()
        )
        create_planning_task(
            session,
            planning,
            PlanningTaskCreate(
                name=name,
                target_parent_uid=target_parent_uid,
                insert_after_uid=insert_after_uid,
                expected_revision=planning.revision,
            ),
        )
        planning.revision += 1
        detail = _planning_detail(session, planning)
        session.commit()
        return detail.model_dump(mode="json")


def move_legacy_planning_tasks(
    project_id: int,
    planning_id: int,
    task_uids: list[int],
    *,
    target_parent_uid: int | None = None,
    position: int = 1,
) -> None:
    """Move tasks in a legacy draft planning, as ``POST .../tasks/move`` did.

    Same reason as :func:`create_legacy_planning_task`: the endpoint is gone, the
    behaviour under test is not. What the devis suite needs it for is the *cause*
    of the behaviour it asserts -- "a task moved in the planning moves in the draft
    estimate" -- not the endpoint that used to trigger it.
    """
    with get_session_factory()() as session:
        planning = (
            session.query(WfPlanning)
            .filter(WfPlanning.id == planning_id, WfPlanning.project_id == project_id)
            .one()
        )
        move_planning_tasks(
            session,
            planning,
            PlanningTaskMove(
                task_uids=task_uids,
                target_parent_uid=target_parent_uid,
                position=position,
                expected_revision=planning.revision,
            ),
        )
        planning.revision += 1
        session.commit()


def delete_legacy_planning_tasks(
    project_id: int, planning_id: int, task_uids: list[int], *, confirm_cascade: bool = False
) -> None:
    """Delete tasks from a legacy draft planning, raising the service's own refusals.

    The route that used to translate ``PlanningTreeTaskReferencedError`` into a 409
    is gone; the guard it translated is not -- ``delete_planning_tasks`` still
    serves the devis reconciliation (``api/routes/estimates.py``). Tests that pin
    the guard therefore assert on the exception directly.
    """
    with get_session_factory()() as session:
        planning = (
            session.query(WfPlanning)
            .filter(WfPlanning.id == planning_id, WfPlanning.project_id == project_id)
            .one()
        )
        delete_planning_tasks(
            session,
            planning,
            PlanningTaskDelete(
                task_uids=task_uids,
                confirm_cascade=confirm_cascade,
                expected_revision=planning.revision,
            ),
        )
        planning.revision += 1
        session.commit()
