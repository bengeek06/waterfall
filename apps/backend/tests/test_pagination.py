"""Unit tests for the EPIC E7 pagination foundation (E7-02, #113).

Deliberately independent of any real endpoint (none is migrated yet, see
#114/#115): `apply_pagination` is exercised directly against a real
database session using `CostType`, a simple existing model, and
`list_params` is exercised through a throwaway FastAPI route mounted only
in this test module -- not one of the application's 17 list endpoints --
so its request-level validation (bounds, offset-requires-limit) is
covered at the same layer it actually runs in.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from waterfall.api.pagination import ListParams, list_params
from waterfall.db.session import get_session_factory
from waterfall.models.resources import CostType
from waterfall.services.pagination import apply_pagination


@pytest.fixture
def session() -> Generator[Session]:
    session_factory = get_session_factory()
    with session_factory() as db_session:
        yield db_session


def _make_cost_type(session: Session, code: str, name: str, *, kind: str = "other") -> CostType:
    cost_type = CostType(code=code, name=name, kind=kind)
    session.add(cost_type)
    session.flush()
    return cost_type


def test_total_reflects_the_full_filtered_set_not_the_page(session: Session) -> None:
    prefix = "e7-total-"
    for index in range(5):
        _make_cost_type(session, f"{prefix}{index}", f"Type {index}")
    session.commit()

    query = session.query(CostType).filter(CostType.code.like(f"{prefix}%"))
    result = apply_pagination(
        query,
        ListParams(limit=2, offset=0, sort=None, q=None),
        sortable={"code": CostType.code},
        tiebreaker=CostType.id,
    )

    assert result.total == 5
    assert len(result.rows) == 2
    assert result.limit == 2
    assert result.offset == 0


def test_absent_limit_returns_every_row(session: Session) -> None:
    prefix = "e7-all-"
    for index in range(7):
        _make_cost_type(session, f"{prefix}{index}", f"Type {index}")
    session.commit()

    query = session.query(CostType).filter(CostType.code.like(f"{prefix}%"))
    result = apply_pagination(
        query,
        ListParams(limit=None, offset=0, sort=None, q=None),
        sortable={"code": CostType.code},
        tiebreaker=CostType.id,
    )

    assert result.limit is None
    assert result.total == 7
    assert len(result.rows) == 7


def test_sort_ascending_and_descending(session: Session) -> None:
    prefix = "e7-sort-"
    _make_cost_type(session, f"{prefix}b", "B")
    _make_cost_type(session, f"{prefix}a", "A")
    _make_cost_type(session, f"{prefix}c", "C")
    session.commit()

    query = session.query(CostType).filter(CostType.code.like(f"{prefix}%"))
    ascending = apply_pagination(
        query,
        ListParams(limit=None, offset=0, sort="name", q=None),
        sortable={"name": CostType.name},
        tiebreaker=CostType.id,
    )
    assert [row.name for row in ascending.rows] == ["A", "B", "C"]

    descending = apply_pagination(
        query,
        ListParams(limit=None, offset=0, sort="-name", q=None),
        sortable={"name": CostType.name},
        tiebreaker=CostType.id,
    )
    assert [row.name for row in descending.rows] == ["C", "B", "A"]


def test_unknown_sort_column_is_rejected_not_interpolated(session: Session) -> None:
    query = session.query(CostType)
    with pytest.raises(HTTPException) as exc_info:
        apply_pagination(
            query,
            ListParams(limit=None, offset=0, sort="id; DROP TABLE wf_cost_type", q=None),
            sortable={"name": CostType.name},
            tiebreaker=CostType.id,
        )
    assert exc_info.value.status_code == 400


def test_empty_sort_value_is_rejected_like_any_unknown_column(session: Session) -> None:
    # `?sort=` (explicitly empty, distinct from omitting the parameter entirely) must
    # not silently bypass the allowlist and fall back to the default order: an empty
    # name is not a declared sortable column any more than a garbage one is.
    query = session.query(CostType)
    with pytest.raises(HTTPException) as exc_info:
        apply_pagination(
            query,
            ListParams(limit=None, offset=0, sort="", q=None),
            sortable={"name": CostType.name},
            tiebreaker=CostType.id,
            default_sort=CostType.id,
        )
    assert exc_info.value.status_code == 400


def test_search_filters_on_declared_columns(session: Session) -> None:
    prefix = "e7-search-"
    _make_cost_type(session, f"{prefix}1", "Findable widget")
    _make_cost_type(session, f"{prefix}2", "Other thing")
    session.commit()

    query = session.query(CostType).filter(CostType.code.like(f"{prefix}%"))
    result = apply_pagination(
        query,
        ListParams(limit=None, offset=0, sort=None, q="findable"),
        sortable={"name": CostType.name},
        tiebreaker=CostType.id,
        searchable=[CostType.name],
    )

    assert result.total == 1
    assert result.rows[0].name == "Findable widget"


def test_search_escapes_like_wildcard_characters(session: Session) -> None:
    # `%` and `_` are SQL LIKE wildcards: unescaped, `q="%"` would match every
    # non-null value in the searched columns instead of rows containing a literal
    # percent sign, and `q="1_1"` would match "1a1", "1b1", etc. as well as "1_1".
    prefix = "e7-escape-"
    _make_cost_type(session, f"{prefix}1", "Contains % literally")
    _make_cost_type(session, f"{prefix}2", "Contains 1_1 literally")
    _make_cost_type(session, f"{prefix}3", "No special characters here")
    session.commit()

    query = session.query(CostType).filter(CostType.code.like(f"{prefix}%"))

    percent_result = apply_pagination(
        query,
        ListParams(limit=None, offset=0, sort=None, q="%"),
        sortable={"name": CostType.name},
        tiebreaker=CostType.id,
        searchable=[CostType.name],
    )
    assert [row.name for row in percent_result.rows] == ["Contains % literally"]

    underscore_result = apply_pagination(
        query,
        ListParams(limit=None, offset=0, sort=None, q="1_1"),
        sortable={"name": CostType.name},
        tiebreaker=CostType.id,
        searchable=[CostType.name],
    )
    assert [row.name for row in underscore_result.rows] == ["Contains 1_1 literally"]


def test_q_without_any_searchable_column_is_rejected_not_ignored(session: Session) -> None:
    # A resource that declares no `searchable` columns (e.g. rates/inflation, keyed
    # only by year) must not silently accept and ignore `q`: a caller who thinks
    # they filtered the list would get every row back with no error to say so.
    query = session.query(CostType)
    with pytest.raises(HTTPException) as exc_info:
        apply_pagination(
            query,
            ListParams(limit=None, offset=0, sort=None, q="anything"),
            sortable={"name": CostType.name},
            tiebreaker=CostType.id,
        )
    assert exc_info.value.status_code == 400


def test_pagination_replaces_a_pre_existing_order_by_instead_of_appending(
    session: Session,
) -> None:
    # SQLAlchemy's Query.order_by() appends on each call rather than replacing the
    # previous ordering. A caller-supplied query that already carries an ORDER BY (its
    # own default, or a prior .order_by() call) must not leave that clause primary:
    # apply_pagination's requested `sort` (and its tiebreaker) has to be the one that
    # actually determines row order and page boundaries.
    prefix = "e7-preordered-"
    _make_cost_type(session, f"{prefix}b", "B")
    _make_cost_type(session, f"{prefix}a", "A")
    _make_cost_type(session, f"{prefix}c", "C")
    session.commit()

    pre_ordered_query = (
        session.query(CostType)
        .filter(CostType.code.like(f"{prefix}%"))
        .order_by(CostType.name.desc())
    )

    result = apply_pagination(
        pre_ordered_query,
        ListParams(limit=None, offset=0, sort="name", q=None),
        sortable={"name": CostType.name},
        tiebreaker=CostType.id,
    )

    assert [row.name for row in result.rows] == ["A", "B", "C"]


def test_pagination_is_stable_on_a_non_unique_sort_column(session: Session) -> None:
    prefix = "e7-stable-"
    # Every row shares the same `kind`: without the primary-key tiebreaker,
    # two consecutive pages ordered only by `kind` could return rows in an
    # arbitrary, possibly overlapping or gap-leaving order.
    created = [
        _make_cost_type(session, f"{prefix}{index}", f"Type {index}", kind="labor")
        for index in range(6)
    ]
    session.commit()
    expected_ids = sorted(row.id for row in created)

    query = session.query(CostType).filter(CostType.code.like(f"{prefix}%"))
    first_page = apply_pagination(
        query,
        ListParams(limit=3, offset=0, sort="kind", q=None),
        sortable={"kind": CostType.kind},
        tiebreaker=CostType.id,
    )
    second_page = apply_pagination(
        query,
        ListParams(limit=3, offset=3, sort="kind", q=None),
        sortable={"kind": CostType.kind},
        tiebreaker=CostType.id,
    )

    first_ids = [row.id for row in first_page.rows]
    second_ids = [row.id for row in second_page.rows]
    assert first_ids + second_ids == expected_ids
    assert set(first_ids).isdisjoint(second_ids)


def _build_test_app() -> FastAPI:
    app = FastAPI()

    @app.get("/items")
    def list_items(  # pyright: ignore[reportUnusedFunction] -- registered via the decorator
        params: ListParams = Depends(list_params),
    ) -> dict[str, object]:
        return {
            "limit": params.limit,
            "offset": params.offset,
            "sort": params.sort,
            "q": params.q,
        }

    return app


def test_list_params_rejects_out_of_bounds_limit_and_offset() -> None:
    client = TestClient(_build_test_app())

    assert client.get("/items", params={"limit": 0}).status_code == 422
    assert client.get("/items", params={"limit": 501}).status_code == 422
    assert client.get("/items", params={"offset": -1}).status_code == 422


def test_list_params_rejects_offset_without_limit() -> None:
    client = TestClient(_build_test_app())

    response = client.get("/items", params={"offset": 10})
    assert response.status_code == 400

    # offset=0 is the (implicit) default, not a real request for an offset:
    # it must not trip the same rule.
    assert client.get("/items").status_code == 200
    assert client.get("/items", params={"limit": 5}).status_code == 200


def test_list_params_accepts_limit_with_offset() -> None:
    client = TestClient(_build_test_app())

    response = client.get("/items", params={"limit": 10, "offset": 20})
    assert response.status_code == 200
    assert response.json() == {"limit": 10, "offset": 20, "sort": None, "q": None}
