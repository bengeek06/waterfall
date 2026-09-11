"""Response models for the readiness probe.

Only readiness is modelled here: liveness (`GET /health`) answers a fixed
`{"status": "ok"}` literal and must stay that way (E13-03 explicitly keeps it free of
any dependency check), so giving it a schema would suggest a variability it does not
have.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# Two states, never an error message: /health/ready is unauthenticated (`security: []`),
# so the body must not tell an anonymous caller *why* a backend is down -- a hostname, a
# bucket name or a botocore error string is reconnaissance. The diagnosis lives in the
# API logs, where it is already written.
DependencyState = Literal["ok", "unavailable"]


class ReadinessChecks(BaseModel):
    """Per-dependency outcome. Explicit fields, not a free-form mapping: these three keys
    are part of the published contract, and a `dict[str, str]` would generate a TS client
    type that cannot tell a caller which keys it may read."""

    database: DependencyState
    redis: DependencyState
    storage: DependencyState


class ReadinessStatus(BaseModel):
    status: Literal["ready", "unavailable"]
    checks: ReadinessChecks
    timestamp: datetime
