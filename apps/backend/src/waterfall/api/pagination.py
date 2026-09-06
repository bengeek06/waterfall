from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Query, status


@dataclass(frozen=True)
class ListParams:
    """Raw, resource-agnostic list query parameters (EPIC E7).

    Bounds are enforced by FastAPI/Pydantic before this dependency ever
    runs (``Query(..., ge=..., le=...)`` below), so an out-of-bounds
    ``limit``/``offset`` is rejected with FastAPI's own 422 -- this
    dataclass only ever carries already-valid values, except for the
    offset-requires-limit cross-field rule below (Pydantic/FastAPI's
    per-parameter ``Query(...)`` validators cannot express a rule spanning
    two parameters). Column-name validation for ``sort`` (is this column
    declared for this resource?) is deliberately not this dependency's job
    either: it has no knowledge of any resource's schema, and belongs to
    ``services.pagination.apply_pagination`` instead, which raises an
    explicit 400 for an unknown column rather than ever interpolating it
    into SQL.
    """

    limit: int | None
    offset: int
    sort: str | None
    q: str | None


def list_params(
    limit: int | None = Query(
        default=None,
        ge=1,
        le=500,
        description="Absent: renvoie l'integralite des lignes du jeu filtre.",
    ),
    offset: int = Query(default=0, ge=0),
    sort: str | None = Query(
        default=None,
        description="Nom de colonne, prefixe de '-' pour un tri descendant.",
    ),
    q: str | None = Query(default=None, min_length=1, alias="q"),
) -> ListParams:
    # Mirrors the "Regle offset/limit" documented in
    # openapi/spec/components/schemas/PaginationMeta.yaml: an offset without
    # a limit is under-specified (does `items` cover the whole filtered set,
    # contradicting `offset`, or only what follows it, contradicting the
    # "no limit -> everything" guarantee?), so it is rejected outright
    # rather than picking one of those two silently.
    if offset and limit is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="offset requires limit to be set",
        )
    return ListParams(limit=limit, offset=offset, sort=sort, q=q)
