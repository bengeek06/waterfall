from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, or_
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.orm import Query as OrmQuery

from waterfall.api.pagination import ListParams

RowT = TypeVar("RowT")
SortableColumn = InstrumentedAttribute[Any]


@dataclass(frozen=True)
class PaginationResult(Generic[RowT]):
    rows: list[RowT]
    total: int
    limit: int | None
    offset: int


def apply_pagination(
    query: OrmQuery[RowT],
    params: ListParams,
    *,
    sortable: Mapping[str, SortableColumn],
    tiebreaker: SortableColumn,
    default_sort: SortableColumn | None = None,
    searchable: Sequence[SortableColumn] = (),
) -> PaginationResult[RowT]:
    """Apply search, sort and pagination to `query` (EPIC E7 backend foundation).

    Returns `total` computed on the full filtered set, before `limit`/
    `offset` are applied -- never the size of the returned page. When
    `params.limit` is `None`, every row of the filtered set is returned and
    `total` equals `len(rows)`: absence of `limit` must never truncate a
    list.

    Ordering always ends with `tiebreaker` (normally the primary key), after
    the requested `sort` column if any, or after `default_sort` otherwise.
    Without this, two consecutive pages could overlap or omit rows whenever
    the sort column is not unique -- `tiebreaker` guarantees a total,
    deterministic order regardless.

    `sortable` maps every column name the `sort` query parameter is allowed
    to reference to its ORM column. A `sort` value naming anything else is
    rejected with an explicit 400 (`ck_pagination_unknown_sort_column`-style
    intent, no dedicated exception type): it is never interpolated into SQL,
    which is what makes arbitrary column names safe to accept from a client
    in the first place.
    """
    if params.q and searchable:
        pattern = f"%{params.q}%"
        query = query.filter(or_(*(column.ilike(pattern) for column in searchable)))

    order_columns: list[SortableColumn | ColumnElement[Any]]
    if params.sort:
        descending = params.sort.startswith("-")
        column_name = params.sort[1:] if descending else params.sort
        column = sortable.get(column_name)
        if column is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown sort column: {column_name}",
            )
        order_columns = [column.desc() if descending else column.asc(), tiebreaker]
    elif default_sort is not None:
        order_columns = [default_sort, tiebreaker]
    else:
        order_columns = [tiebreaker]

    # order_by(None) drops any ordering already present on `query` before counting:
    # ORDER BY has no effect on COUNT(*) but needlessly complicates the query plan.
    total = query.order_by(None).count()

    query = query.order_by(*order_columns).offset(params.offset)
    if params.limit is not None:
        query = query.limit(params.limit)

    return PaginationResult(rows=query.all(), total=total, limit=params.limit, offset=params.offset)
