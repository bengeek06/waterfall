"""Shared helper for tests that seed `EstimateCostLine`/`EstimateRoleAssignment`
rows directly via the ORM (bypassing the create routes -- typically to construct
a pre-existing/legacy row an endpoint itself cannot produce). Issue #289
(E12-07) made every such row require its own `EstimateGridNode` (`node_id`, a
NOT NULL unique FK) -- this factors that one-off allocation out instead of
duplicating it at every call site.

Deliberately not named `test_*.py` (see `_postgres_support.py`'s own docstring
for the same reasoning): pytest would otherwise try to import it as a test
module.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from waterfall.models.resources import EstimateGridNode
from waterfall.services.estimate_grid import next_estimate_grid_node_uid


def seed_root_grid_node(session: Session, estimate_id: int, kind: str) -> int:
    """Insert one root-level `EstimateGridNode` for `estimate_id` and return its id.

    `kind` is `"cost_line"` or `"labor"`, matching `EstimateGridNode.kind`. Safe
    to call more than once for the same `estimate_id` within one test -- each
    call allocates its own `uid` (via the same `next_estimate_grid_node_uid`
    the production create routes use) and appends after any existing root node.
    """
    existing_root_count = (
        session.query(EstimateGridNode)
        .filter(
            EstimateGridNode.estimate_id == estimate_id,
            EstimateGridNode.parent_uid.is_(None),
        )
        .count()
    )
    node = EstimateGridNode(
        estimate_id=estimate_id,
        uid=next_estimate_grid_node_uid(session, estimate_id),
        parent_uid=None,
        position=existing_root_count + 1,
        kind=kind,
    )
    session.add(node)
    session.flush()
    return node.id
