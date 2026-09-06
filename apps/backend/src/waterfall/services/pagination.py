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

_LIKE_ESCAPE_CHAR = "\\"


def _escape_like(value: str) -> str:
    """Escape `%`, `_` and the escape character itself for a LIKE/ILIKE pattern.

    Without this, `%`/`_` in a user's search term are interpreted as SQL
    wildcards rather than the literal characters the contract promises
    (`q=%` would otherwise match every non-null value instead of rows
    containing a literal percent sign).
    """
    return (
        value.replace(_LIKE_ESCAPE_CHAR, _LIKE_ESCAPE_CHAR * 2)
        .replace("%", f"{_LIKE_ESCAPE_CHAR}%")
        .replace("_", f"{_LIKE_ESCAPE_CHAR}_")
    )


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

    `list_params` accepts `q` unconditionally, even for endpoints with no
    `searchable` columns of their own. Without a check here, such a `q`
    would be silently ignored -- a request that filtered nothing would
    look identical to one that filtered everything out, with no error to
    tell the two apart. So `q` on a resource with no `searchable` columns
    is rejected the same way an unknown `sort` column is.
    """
    # Drop any ordering already present on `query` up front: apply_pagination owns
    # ordering entirely, and Query.order_by() *appends* rather than replaces on each
    # call -- leaving a caller-supplied order in place would keep it primary, silently
    # overriding the requested `sort`/tiebreaker that is supposed to define page
    # boundaries.
    query = query.order_by(None)

    if params.q is not None:
        if not searchable:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This resource does not support the 'q' search parameter",
            )
        pattern = f"%{_escape_like(params.q)}%"
        query = query.filter(
            or_(*(column.ilike(pattern, escape=_LIKE_ESCAPE_CHAR) for column in searchable))
        )

    order_columns: list[SortableColumn | ColumnElement[Any]]
    if params.sort is not None:
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

    # ORDER BY has no effect on COUNT(*) but needlessly complicates the query plan.
    total = query.order_by(None).count()

    query = query.order_by(*order_columns).offset(params.offset)
    if params.limit is not None:
        query = query.limit(params.limit)

    return PaginationResult(rows=query.all(), total=total, limit=params.limit, offset=params.offset)
