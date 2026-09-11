"""The Prometheus exposition at `GET /metrics`.

Every assertion here reads the *endpoint's* text rather than the process registry: the
registry is global and shared by the whole session, so a test that trusted it would prove
the metric exists, not that a scrape can see it. For the same reason nothing below assumes
a counter starts at zero -- a value is either compared to the one read a moment earlier
(histograms, which only ever grow) or is a gauge this very test just set.
"""

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from prometheus_client import CollectorRegistry, Histogram
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy.orm import Session, sessionmaker

from waterfall.api.routes import health
from waterfall.api.routes.auth import LoginRateLimiter
from waterfall.core.config import get_settings
from waterfall.core.observability import track_duration
from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject
from waterfall.models.resources import Estimate
from waterfall.services.estimate_calculation import (
    calculate_estimate_aggregates,
    calculate_estimate_lines,
)

# Same rationale as test_health's constant: port 1 is privileged, so the connection is
# refused instantly instead of hanging on a timeout.
UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/0"


def _scrape() -> str:
    with TestClient(app) as client:
        response: Response = client.get("/metrics")
    assert response.status_code == 200
    return response.text


def _sample(metrics_text: str, name: str, labels: dict[str, str]) -> float | None:
    """The value of one exposed sample, or None if the series is absent.

    Parsed with prometheus_client's own parser rather than a substring match, so a test
    asserting on `dependency_up{dependency="redis"}` cannot accidentally be satisfied by
    a differently-labelled series that happens to share a prefix.
    """
    for family in text_string_to_metric_families(metrics_text):
        for sample in family.samples:
            if sample.name == name and sample.labels == labels:
                return sample.value
    return None


def _observation_count(metrics_text: str, function_name: str) -> float:
    return (
        _sample(
            metrics_text,
            "estimate_calculation_duration_seconds_count",
            {"function": function_name},
        )
        or 0.0
    )


def _seed_empty_estimate(session_factory: sessionmaker[Session]) -> int:
    """A project with one estimate and nothing in it.

    Enough for both calculation functions to run their real query path end to end -- the
    point here is that the instrumentation fires and the label is right, not what the
    engine computes; test_estimate_calculation.py owns the latter.
    """
    with session_factory() as session:
        project = MsProject(
            owner_id=None,
            external_uid=None,
            source_version=2016,
            save_version_out=16,
            name="Metrics Test",
            schedule_from_start=True,
            start_date=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
            finish_date=datetime(2026, 12, 31, 18, 0, tzinfo=UTC),
            calendar_uid=1,
            minutes_per_day=480,
            minutes_per_week=2400,
            days_per_month=20,
            currency_code="EUR",
        )
        session.add(project)
        session.flush()
        estimate = Estimate(
            project_id=project.id,
            version_number=1,
            kind="initial",
            status="draft",
            currency_code="EUR",
        )
        session.add(estimate)
        session.commit()
        return estimate.id


def test_metrics_endpoint() -> None:
    with TestClient(app) as client:
        _health: Response = client.get("/health")
        _project: Response = client.get("/projects/123456")
        metrics: Response = client.get("/metrics")

    assert metrics.status_code == 200
    assert "http_requests_total" in metrics.text
    assert "http_request_duration_seconds" in metrics.text
    assert 'path="/projects/{project_id}"' in metrics.text
    assert 'path="/projects/123456"' not in metrics.text


def test_http_metrics_keep_their_published_shape() -> None:
    """E13-04 adds series; it must not reshape the two that already existed.

    What is pinned is the *identity* of those series: name, metric type, and label set.
    Renaming one, changing its type, or adding a label silently breaks every alert and
    dashboard built on it, so it is asserted rather than left implicit.

    What is deliberately *not* pinned is the `le` bucket boundaries of
    `http_request_duration_seconds`. Re-bucketing does break a `histogram_quantile`, but
    freezing the boundaries here would put a future deliberate re-bucketing behind a test
    edit -- exactly the re-bucketing this same change makes on
    `estimate_calculation_duration_seconds`, whose buckets are likewise left unasserted.
    """
    with TestClient(app) as client:
        _health: Response = client.get("/health")

    metrics_text = _scrape()
    # Keyed by the *family* name the parser reports, which for a counter is the exposed
    # name minus its `_total` suffix ("http_requests"); the sample names below are the
    # ones a scraper actually ingests.
    families = {family.name: family for family in text_string_to_metric_families(metrics_text)}

    assert families["http_requests"].type == "counter"
    assert families["http_request_duration_seconds"].type == "histogram"
    assert "http_requests_total" in {sample.name for sample in families["http_requests"].samples}
    assert {
        label
        for sample in families["http_requests"].samples
        for label in sample.labels
        # The `_created` timestamps the scrape also carries are parsed as their own family
        # (`http_requests_created`, a gauge), so they are not in this iteration at all and
        # need no exclusion. They are intentionally left unasserted: that series can be
        # switched off with PROMETHEUS_DISABLE_CREATED_SERIES, and pinning it here would
        # tie this test to an environment variable.
    } == {"method", "path", "status_code"}
    assert {
        label
        for sample in families["http_request_duration_seconds"].samples
        for label in sample.labels
        if label != "le"  # the bucket boundary, part of the histogram encoding itself
    } == {"method", "path"}


def test_estimate_calculations_are_observed_and_exposed() -> None:
    """A devis calculation must show up as an observation on the dedicated histogram."""
    estimate_id = _seed_empty_estimate(get_session_factory())

    before = _scrape()
    lines_before = _observation_count(before, "calculate_estimate_lines")
    aggregates_before = _observation_count(before, "calculate_estimate_aggregates")

    session_factory = get_session_factory()
    with session_factory() as session:
        assert calculate_estimate_lines(session, estimate_id) == []
        calculate_estimate_aggregates(session, estimate_id)

    after = _scrape()
    # A delta, never an absolute: the registry is process-wide and any earlier test in the
    # session may have gone through the same code path.
    assert _observation_count(after, "calculate_estimate_lines") == lines_before + 1
    assert _observation_count(after, "calculate_estimate_aggregates") == aggregates_before + 1
    assert 'estimate_calculation_duration_seconds_count{function="calculate_estimate_lines"}' in (
        after
    )


def test_estimate_calculation_labels_stay_a_closed_set() -> None:
    """Cardinality guard: the only label is a function name, from a fixed vocabulary.

    An estimate or project id leaking into this label would grow the series count with the
    data, which is the classic way a histogram takes a Prometheus down.

    The value set is asserted by equality, not inclusion: `track_duration` resolves its
    child at decoration time, so importing `estimate_calculation` is enough to create both
    series -- an empty set here would mean the instrumentation itself was dropped, which an
    inclusion assertion would have waved through.
    """
    estimate_id = _seed_empty_estimate(get_session_factory())
    with get_session_factory()() as session:
        calculate_estimate_aggregates(session, estimate_id)

    metrics_text = _scrape()
    samples = [
        sample
        for family in text_string_to_metric_families(metrics_text)
        if family.name == "estimate_calculation_duration_seconds"
        for sample in family.samples
    ]

    assert {frozenset(sample.labels) for sample in samples} == {
        frozenset({"function"}),
        frozenset({"function", "le"}),
    }
    assert {sample.labels["function"] for sample in samples} == {
        "calculate_estimate_lines",
        "calculate_estimate_aggregates",
    }


def test_track_duration_refuses_an_async_function() -> None:
    """The one case where this decorator would measure the wrong thing, made loud.

    Unlike the rest of this module it asserts on the decorator instead of the scrape: the
    point is that the failure happens at decoration, so nothing ever reaches /metrics.
    Wrapping an `async def` would time the creation of the coroutine object rather than its
    execution, so the histogram would fill with near-zero values and every percentile read
    from it would be wrong -- with no error anywhere to hint at it.

    The probe histogram lives in a throwaway registry: a regression here must fail this
    test only, not leak a stray `function="..."` series into the closed-set assertion above.
    """
    probe = Histogram(
        "probe_duration_seconds",
        "Throwaway histogram, never exposed",
        ["function"],
        registry=CollectorRegistry(),
    )

    async def async_calculation() -> None: ...  # pragma: no cover - never awaited

    # Applied by hand rather than with `@`, so the rejected function stays a named local
    # instead of a binding pyright reports as never accessed.
    with pytest.raises(TypeError, match="sync callables only"):
        track_duration(probe)(async_calculation)


def test_readiness_publishes_every_dependency_state() -> None:
    with TestClient(app) as client:
        ready: Response = client.get("/health/ready")
    assert ready.status_code == 200
    # The split the EPIC insists on: readiness answers orchestrators, /metrics answers
    # Prometheus, and no metric ever leaks into the readiness body.
    assert set(cast(dict[str, Any], ready.json())) == {"status", "checks", "timestamp"}

    metrics_text = _scrape()
    for dependency in health.Dependency:
        assert _sample(metrics_text, "dependency_up", {"dependency": dependency.value}) == 1.0


def test_readiness_publishes_a_down_dependency_as_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gauge has to track the current state, not just prove it can say "up"."""
    monkeypatch.setenv("REDIS_URL", UNREACHABLE_REDIS_URL)
    get_settings.cache_clear()
    try:
        # A throwaway limiter, as in test_health: it connects lazily, so it picks up the
        # unreachable URL, and the singleton the rest of the suite shares is untouched.
        monkeypatch.setattr(health, "login_rate_limiter", LoginRateLimiter())
        with TestClient(app) as client:
            ready: Response = client.get("/health/ready")
    finally:
        get_settings.cache_clear()

    assert ready.status_code == 503
    metrics_text = _scrape()
    assert _sample(metrics_text, "dependency_up", {"dependency": "redis"}) == 0.0
    assert _sample(metrics_text, "dependency_up", {"dependency": "database"}) == 1.0
    assert _sample(metrics_text, "dependency_up", {"dependency": "storage"}) == 1.0

    # And the outage stays out of the readiness body, exactly as E13-03 froze it.
    assert set(cast(dict[str, Any], ready.json())) == {"status", "checks", "timestamp"}


def test_scraping_metrics_never_probes_a_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    """A scrape reads the last published state; it must not go touch Redis or Garage.

    /metrics is cheap and frequently polled. Probing on scrape would hand every scraper
    three probe threads per poll -- the same threadpool exhaustion `check_dependencies`'s
    memo exists to prevent on /health/ready, reintroduced through the back door.
    """
    probes = 0

    def counted() -> None:
        nonlocal probes
        probes += 1

    monkeypatch.setattr(health, "_check_storage", counted)

    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 200
    assert probes == 1

    for _ in range(3):
        assert "dependency_up" in _scrape()
    assert probes == 1
