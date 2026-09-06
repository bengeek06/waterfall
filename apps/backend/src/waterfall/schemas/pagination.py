from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

ItemT = TypeVar("ItemT")


class PaginatedList(BaseModel, Generic[ItemT]):
    """Generic list envelope: ``{items, total, limit, offset}`` (EPIC E7).

    Mirrors the OpenAPI ``PaginationMeta`` component
    (``openapi/spec/components/schemas/PaginationMeta.yaml``); keep both in
    sync. ``limit`` is ``None`` when the caller did not request one: ``items``
    then holds every row of the filtered set and ``total`` equals
    ``len(items)`` -- callers must never substitute a default limit here, or
    a list would be silently truncated with no way for the client to detect
    it.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[ItemT]
    total: int
    limit: int | None
    offset: int
