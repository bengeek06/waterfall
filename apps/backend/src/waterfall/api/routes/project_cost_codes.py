from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user
from waterfall.api.routes.project_access import get_mutable_project_lock, get_project_or_404
from waterfall.db.session import get_db
from waterfall.models.resources import ProjectCostCode
from waterfall.models.user import User
from waterfall.schemas.projects import (
    ProjectCostCodeCreate,
    ProjectCostCodeListRead,
    ProjectCostCodeRead,
    ProjectCostCodeUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"])
ResponseType = TypeVar("ResponseType")


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _commit(db: Session, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _conflict(detail) from exc


def _flush(db: Session, detail: str) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise _conflict(detail) from exc


def _snapshot_and_commit(
    db: Session,
    detail: str,
    snapshot: Callable[[], ResponseType],
) -> ResponseType:
    _flush(db, detail)
    response = snapshot()
    _commit(db, detail)
    return response


def get_cost_code_or_404(db: Session, project_id: int, cost_code_id: int) -> ProjectCostCode:
    cost_code = (
        db.query(ProjectCostCode)
        .filter(ProjectCostCode.id == cost_code_id)
        .filter(ProjectCostCode.project_id == project_id)
        .first()
    )
    if cost_code is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost code not found")
    return cost_code


def _ensure_deactivatable(db: Session, cost_code: ProjectCostCode) -> None:
    has_active_children = (
        db.query(ProjectCostCode.id)
        .filter(ProjectCostCode.parent_id == cost_code.id)
        .filter(ProjectCostCode.is_active.is_(True))
        .first()
    )
    if has_active_children is not None:
        raise _conflict("Cost code has active child codes and cannot be deactivated")
    # The root (parent_id IS NULL) is the project's default cost-imputation attachment
    # point (E6-02/#63) -- a project must always keep exactly one active root, so it is
    # never itself deactivatable, unlike every other node.
    if cost_code.parent_id is None:
        raise _conflict("The project's root cost code cannot be deactivated")


def _get_cost_code_in_project_or_400(
    db: Session,
    project_id: int,
    cost_code_id: int,
    *,
    detail: str = "Parent cost code does not belong to project",
) -> ProjectCostCode:
    # Deliberately 400, not 404: this validates a caller-supplied `parent_id` (or,
    # since #63/E6-02, `cost_code_id`) reference, not the primary resource identified
    # by the URL path -- same convention already used for
    # `EstimateCostLineCreate.task_id` in api/routes/estimates.py ("Task does not
    # belong to project"), so a reference that either does not exist at all or
    # belongs to a different project is reported identically here.
    cost_code = (
        db.query(ProjectCostCode)
        .filter(ProjectCostCode.id == cost_code_id)
        .filter(ProjectCostCode.project_id == project_id)
        .first()
    )
    if cost_code is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    return cost_code


def resolve_cost_code_id(db: Session, project_id: int, requested_cost_code_id: int | None) -> int:
    """Resolve the `cost_code_id` to store on a newly created cost line (#63/E6-02).

    An explicit `cost_code_id` must belong to the project -- same 400 convention as
    `parent_id` validation above. When omitted, every project is guaranteed to carry
    exactly one active root cost code (the #62/E6-01 invariant), which becomes the
    default attachment point for a cost line created without an explicit one.
    """
    if requested_cost_code_id is not None:
        cost_code = _get_cost_code_in_project_or_400(
            db,
            project_id,
            requested_cost_code_id,
            detail="Cost code does not belong to project",
        )
        # Unlike parent_id validation (#62), which must be able to walk through an
        # inactive ancestor to detect cycles, attaching new spend to a cost line is a
        # forward-looking action: a deactivated code should never accept a new
        # attachment, even though it may already be referenced by pre-existing lines.
        if not cost_code.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cost code is not active",
            )
        return cost_code.id
    try:
        root = (
            db.query(ProjectCostCode)
            .filter(ProjectCostCode.project_id == project_id)
            .filter(ProjectCostCode.parent_id.is_(None))
            .filter(ProjectCostCode.is_active.is_(True))
            .one()
        )
    except NoResultFound as exc:
        # Should never happen: #62/E6-01 guarantees every project always has exactly
        # one active root, enforced at creation (atomic with the project itself) and
        # at deactivation (the root can never be deactivated). Surfaced as a clean 500
        # rather than a bare, undocumented Starlette error if that invariant is ever
        # violated (e.g. a project created by tooling that bypasses `create_project`).
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Project has no active root cost code",
        ) from exc
    return root.id


def _validate_cost_code_parent(
    db: Session, project_id: int, cost_code_id: int, parent_id: int
) -> None:
    visited: set[int] = set()
    current_id: int | None = parent_id
    while current_id is not None:
        if current_id == cost_code_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cost code cannot be assigned below its descendant",
            )
        if current_id in visited:
            raise _conflict("Project cost code hierarchy contains a cycle")
        visited.add(current_id)
        current_node = _get_cost_code_in_project_or_400(db, project_id, current_id)
        current_id = current_node.parent_id


@router.get("/{project_id}/cost-codes", response_model=ProjectCostCodeListRead)
def list_project_cost_codes(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectCostCodeListRead:
    get_project_or_404(db, project_id, current_user.id)
    # Deliberately not paginated (same rationale as GET /resources/nodes): callers
    # rebuild the full cost-code tree client-side and a truncated page would
    # silently produce an incomplete/broken tree.
    cost_codes = (
        db.query(ProjectCostCode)
        .filter(ProjectCostCode.project_id == project_id)
        .filter(ProjectCostCode.is_active.is_(True))
        .order_by(ProjectCostCode.code)
        .all()
    )
    items = [ProjectCostCodeRead.model_validate(cost_code) for cost_code in cost_codes]
    return ProjectCostCodeListRead(items=items, total=len(items), limit=None, offset=0)


@router.post(
    "/{project_id}/cost-codes",
    response_model=ProjectCostCodeRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project_cost_code(
    project_id: int,
    payload: ProjectCostCodeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectCostCodeRead:
    get_mutable_project_lock(db, project_id, current_user.id)
    if payload.parent_id is not None:
        _get_cost_code_in_project_or_400(db, project_id, payload.parent_id)
    cost_code = ProjectCostCode(project_id=project_id, **payload.model_dump())
    db.add(cost_code)
    return _snapshot_and_commit(
        db,
        "Cost code already exists for this project",
        lambda: ProjectCostCodeRead.model_validate(cost_code),
    )


@router.get("/{project_id}/cost-codes/{cost_code_id}", response_model=ProjectCostCodeRead)
def get_project_cost_code(
    project_id: int,
    cost_code_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectCostCode:
    get_project_or_404(db, project_id, current_user.id)
    return get_cost_code_or_404(db, project_id, cost_code_id)


@router.patch("/{project_id}/cost-codes/{cost_code_id}", response_model=ProjectCostCodeRead)
def update_project_cost_code(
    project_id: int,
    cost_code_id: int,
    payload: ProjectCostCodeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectCostCodeRead:
    get_mutable_project_lock(db, project_id, current_user.id)
    cost_code = get_cost_code_or_404(db, project_id, cost_code_id)
    values = payload.model_dump(exclude_unset=True)
    if values.get("parent_id") is not None:
        _validate_cost_code_parent(db, project_id, cost_code.id, values["parent_id"])
    if values.get("is_active") is False:
        _ensure_deactivatable(db, cost_code)
    for field, value in values.items():
        setattr(cost_code, field, value)
    db.add(cost_code)
    return _snapshot_and_commit(
        db,
        "Cost code update conflicts with existing data",
        lambda: ProjectCostCodeRead.model_validate(cost_code),
    )


@router.delete("/{project_id}/cost-codes/{cost_code_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_cost_code(
    project_id: int,
    cost_code_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    get_mutable_project_lock(db, project_id, current_user.id)
    cost_code = get_cost_code_or_404(db, project_id, cost_code_id)
    _ensure_deactivatable(db, cost_code)
    cost_code.is_active = False
    db.add(cost_code)
    _commit(db, "Cost code deactivation conflicts with existing data")
