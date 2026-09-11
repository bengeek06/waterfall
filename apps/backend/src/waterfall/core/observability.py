import inspect
from collections.abc import Awaitable, Callable
from functools import wraps
from time import perf_counter
from typing import ParamSpec, TypeVar
from uuid import uuid4

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import PlainTextResponse

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)

# Business-side counterpart to REQUEST_DURATION (E13-04): the HTTP histogram says a devis
# endpoint got slow, this one says whether the calculation engine is what got slow, or
# whether the time went somewhere else in the request.
#
# The `function` label is filled from `__name__` by `track_duration`, so its value set is
# closed by construction -- today the two functions E13-04 names,
# `calculate_estimate_lines` and `calculate_estimate_aggregates`. It must never carry
# anything derived from a request (an estimate or project id), which would make the series
# count grow with the data.
#
# Call sites, because they set what the numbers mean:
#   - `calculate_estimate_lines` runs once per devis validation, from
#     `POST /projects/{project_id}/estimates/{estimate_id}/validate`
#     (`api/routes/estimates.py`), *while the handler holds the `ms_project` row lock* taken
#     just above it by `get_mutable_project_lock`. Its duration is therefore exactly the
#     window during which every other writer on that project is blocked -- which is the
#     thing this histogram makes visible, and the reason it is worth a metric of its own.
#   - `calculate_estimate_aggregates` runs on `GET .../estimates/{estimate_id}/aggregates`
#     (interactive) and inside the Excel export (`services/estimate_export.py`).
# Neither is on the devis *grid* render path: that grid is built by `services/estimate_grid`,
# which does not go through this engine at all.
#
# Buckets: the prometheus_client defaults with their top end extended
# (5ms -> 10s, then 30s/60s/120s). The low end is kept boundary-for-boundary identical to
# `http_request_duration_seconds` so the interactive aggregates call can be read against the
# HTTP histogram on a single axis. The high end exists for the bulk write under the project
# lock: with the stock buckets, everything past 10s collapses into `+Inf`, making "the
# validation took 11s" indistinguishable from "the validation held the project locked for
# four minutes" -- precisely the incident this metric is meant to surface. Re-bucketing
# invalidates recorded history, which is why it is done now, before this series has ever
# been scraped in production, rather than later.
ESTIMATE_CALCULATION_DURATION = Histogram(
    "estimate_calculation_duration_seconds",
    "Estimate calculation duration in seconds",
    ["function"],
    buckets=Histogram.DEFAULT_BUCKETS[:-1] + (30.0, 60.0, 120.0, float("inf")),
)

# Reachability of each backing service, as last observed by `GET /health/ready`.
#
# Written by that handler from the result it already has (see
# `api/routes/health.check_dependencies`, memoised for a few seconds), never by a scrape:
# probing on scrape would hand any Prometheus -- or anyone who can reach /metrics -- the
# ability to spawn three probe threads per scrape, which is exactly the back-pressure the
# memo exists to provide. A consequence worth knowing when reading a dashboard: this gauge
# is only as fresh as the last readiness call, and is absent entirely until the first one.
DEPENDENCY_UP = Gauge(
    "dependency_up",
    "Backing service reachability as last seen by GET /health/ready (1 = up, 0 = down)",
    ["dependency"],
)

_P = ParamSpec("_P")
_R = TypeVar("_R")


def track_duration(histogram: Histogram) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Observe the wrapped function's wall-clock duration, labelled by its own name.

    The child metric is resolved once, at decoration time, so that nothing on the measured
    path pays for a `labels()` lookup (it takes the parent's lock plus a dict lookup on
    every call). What is left is one `perf_counter` pair and one `observe` -- O(1) in the
    input size, and silent (no logging, no formatting). `observe` itself still takes the
    child's own mutex, which is a handful of microseconds next to the database round trips
    the instrumented functions make.

    A call that raises is observed too, like `prometheus_client`'s own `.time()`: the time
    a failing calculation burned is time the caller burned.

    Sync callables only, enforced at decoration: on an `async def` the wrapper would time
    the *creation* of the coroutine (microseconds) rather than its execution, filling the
    histogram with near-zero values and quietly making every percentile read on it a lie.

    Stacking caveat: the label comes from `func.__name__`, so this must stay the innermost
    decorator unless every decorator below it uses `functools.wraps` -- otherwise the label
    becomes `"wrapper"` and several instrumented functions silently merge into one series.
    """

    def decorate(func: Callable[_P, _R]) -> Callable[_P, _R]:
        if inspect.iscoroutinefunction(func):
            raise TypeError(
                "track_duration wraps sync callables only: on an async def it would time "
                "coroutine creation, not execution"
            )
        child = histogram.labels(func.__name__)

        @wraps(func)
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            start = perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                child.observe(perf_counter() - start)

        return wrapper

    return decorate


def set_dependency_up(dependency: str, is_up: bool) -> None:
    """Publish one dependency's state on `DEPENDENCY_UP`.

    Takes the state as an argument rather than looking it up: the caller is the readiness
    handler, which already holds a (memoised) answer, and this function must never be the
    thing that triggers a probe.
    """
    DEPENDENCY_UP.labels(dependency).set(1.0 if is_up else 0.0)


def _metric_path(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return route_path if isinstance(route_path, str) else "<unmatched>"


async def request_metrics_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    start = perf_counter()
    request_id = request.headers.get("x-request-id") or str(uuid4())

    response = await call_next(request)

    duration = perf_counter() - start
    path = _metric_path(request)
    REQUEST_COUNT.labels(request.method, path, str(response.status_code)).inc()
    REQUEST_DURATION.labels(request.method, path).observe(duration)
    response.headers["x-request-id"] = request_id
    return response


def metrics_response() -> PlainTextResponse:
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)
