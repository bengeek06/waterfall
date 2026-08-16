from __future__ import annotations

from datetime import date
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user, get_current_admin_user
from waterfall.db.session import get_db
from waterfall.models.resources import (
    CostCategory,
    CostRate,
    InflationRate,
    ResourceNode,
    ResourceRole,
    RoleCapacity,
)
from waterfall.models.user import User
from waterfall.schemas.resources import (
    CostCategoryCreate,
    CostCategoryRead,
    CostCategoryUpdate,
    CostRateCreate,
    CostRateRead,
    CostRateUpdate,
    InflationRateRead,
    InflationRateUpdate,
    ResourceNodeCreate,
    ResourceNodeRead,
    ResourceNodeUpdate,
    ResourceRoleCreate,
    ResourceRoleRead,
    ResourceRoleUpdate,
    RoleCapacityCreate,
    RoleCapacityRead,
    RoleCapacityUpdate,
)

router = APIRouter(prefix="/resources", tags=["resources"])
ModelType = TypeVar("ModelType")


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _commit(db: Session, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _conflict(detail) from exc


def _get_or_404(
    db: Session,
    model: type[ModelType],
    item_id: int,
    label: str,
) -> ModelType:
    item = db.query(model).filter(model.id == item_id).first()  # type: ignore[attr-defined]
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found")
    return item


@router.get("/nodes", response_model=list[ResourceNodeRead])
def list_nodes(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> list[ResourceNode]:
    return (
        db.query(ResourceNode)
        .filter(ResourceNode.is_active.is_(True))
        .order_by(ResourceNode.code)
        .all()
    )


@router.post("/nodes", response_model=ResourceNodeRead, status_code=status.HTTP_201_CREATED)
def create_node(
    payload: ResourceNodeCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> ResourceNode:
    if payload.parent_id is not None:
        _get_or_404(db, ResourceNode, payload.parent_id, "Parent node")
    node = ResourceNode(**payload.model_dump())
    db.add(node)
    _commit(db, "Resource node code already exists")
    db.refresh(node)
    return node


@router.get("/nodes/{node_id}", response_model=ResourceNodeRead)
def get_node(
    node_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> ResourceNode:
    node = _get_or_404(db, ResourceNode, node_id, "Resource node")
    return node


@router.patch("/nodes/{node_id}", response_model=ResourceNodeRead)
def update_node(
    node_id: int,
    payload: ResourceNodeUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> ResourceNode:
    node = _get_or_404(db, ResourceNode, node_id, "Resource node")
    if payload.parent_id == node.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Node cannot parent itself",
        )
    if payload.parent_id is not None:
        _get_or_404(db, ResourceNode, payload.parent_id, "Parent node")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(node, field, value)
    db.add(node)
    _commit(db, "Resource node update conflicts with existing data")
    db.refresh(node)
    return node


@router.get("/roles", response_model=list[ResourceRoleRead])
def list_roles(
    node_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> list[ResourceRole]:
    query = db.query(ResourceRole).filter(ResourceRole.is_active.is_(True))
    if node_id is not None:
        query = query.filter(ResourceRole.node_id == node_id)
    return query.order_by(ResourceRole.code).all()


@router.post("/roles", response_model=ResourceRoleRead, status_code=status.HTTP_201_CREATED)
def create_role(
    payload: ResourceRoleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> ResourceRole:
    _get_or_404(db, ResourceNode, payload.node_id, "Resource node")
    _get_or_404(db, CostCategory, payload.cost_category_id, "Cost category")
    role = ResourceRole(**payload.model_dump())
    db.add(role)
    _commit(db, "Resource role code already exists")
    db.refresh(role)
    return role


@router.get("/roles/{role_id}", response_model=ResourceRoleRead)
def get_role(
    role_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> ResourceRole:
    return _get_or_404(db, ResourceRole, role_id, "Resource role")


@router.patch("/roles/{role_id}", response_model=ResourceRoleRead)
def update_role(
    role_id: int,
    payload: ResourceRoleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> ResourceRole:
    role = _get_or_404(db, ResourceRole, role_id, "Resource role")
    values = payload.model_dump(exclude_unset=True)
    if "node_id" in values:
        _get_or_404(db, ResourceNode, values["node_id"], "Resource node")
    if "cost_category_id" in values:
        _get_or_404(db, CostCategory, values["cost_category_id"], "Cost category")
    for field, value in values.items():
        setattr(role, field, value)
    db.add(role)
    _commit(db, "Resource role update conflicts with existing data")
    db.refresh(role)
    return role


@router.get("/categories", response_model=list[CostCategoryRead])
def list_categories(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> list[CostCategory]:
    return (
        db.query(CostCategory)
        .filter(CostCategory.is_active.is_(True))
        .order_by(CostCategory.code)
        .all()
    )


@router.post("/categories", response_model=CostCategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CostCategoryCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> CostCategory:
    category = CostCategory(**payload.model_dump())
    db.add(category)
    _commit(db, "Cost category code already exists")
    db.refresh(category)
    return category


@router.get("/categories/{category_id}", response_model=CostCategoryRead)
def get_category(
    category_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> CostCategory:
    return _get_or_404(db, CostCategory, category_id, "Cost category")


@router.patch("/categories/{category_id}", response_model=CostCategoryRead)
def update_category(
    category_id: int,
    payload: CostCategoryUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> CostCategory:
    category = _get_or_404(db, CostCategory, category_id, "Cost category")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    db.add(category)
    _commit(db, "Cost category update conflicts with existing data")
    db.refresh(category)
    return category


@router.get("/categories/{category_id}/rates", response_model=list[CostRateRead])
def list_rates(
    category_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> list[CostRate]:
    _get_or_404(db, CostCategory, category_id, "Cost category")
    return (
        db.query(CostRate)
        .filter(CostRate.cost_category_id == category_id)
        .order_by(CostRate.year)
        .all()
    )


@router.post("/rates", response_model=CostRateRead, status_code=status.HTTP_201_CREATED)
def create_rate(
    payload: CostRateCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> CostRate:
    _get_or_404(db, CostCategory, payload.cost_category_id, "Cost category")
    rate = CostRate(**payload.model_dump())
    db.add(rate)
    _commit(db, "A cost rate already exists for this category and year")
    db.refresh(rate)
    return rate


@router.patch("/rates/{rate_id}", response_model=CostRateRead)
def update_rate(
    rate_id: int,
    payload: CostRateUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> CostRate:
    rate = _get_or_404(db, CostRate, rate_id, "Cost rate")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rate, field, value)
    db.add(rate)
    _commit(db, "Cost rate update conflicts with existing data")
    db.refresh(rate)
    return rate


@router.get("/inflation", response_model=list[InflationRateRead])
def list_inflation_rates(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> list[InflationRate]:
    return db.query(InflationRate).order_by(InflationRate.year).all()


@router.put("/inflation/{year}", response_model=InflationRateRead)
def put_inflation_rate(
    year: int,
    payload: InflationRateUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> InflationRate:
    rate = db.query(InflationRate).filter(InflationRate.year == year).first()
    if rate is None:
        coefficient = payload.coefficient
        rate = InflationRate(year=year, coefficient=coefficient)
        db.add(rate)
    else:
        rate.coefficient = payload.coefficient
        db.add(rate)
    _commit(db, "Inflation rate update conflicts with existing data")
    db.refresh(rate)
    return rate


@router.get("/capacities", response_model=list[RoleCapacityRead])
def list_capacities(
    role_id: int | None = Query(default=None, gt=0),
    period_start: date | None = None,
    period_end: date | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> list[RoleCapacity]:
    query = db.query(RoleCapacity)
    if role_id is not None:
        query = query.filter(RoleCapacity.role_id == role_id)
    if period_start is not None:
        query = query.filter(RoleCapacity.period_end > period_start)
    if period_end is not None:
        query = query.filter(RoleCapacity.period_start < period_end)
    return query.order_by(RoleCapacity.period_start, RoleCapacity.role_id).all()


@router.post("/capacities", response_model=RoleCapacityRead, status_code=status.HTTP_201_CREATED)
def create_capacity(
    payload: RoleCapacityCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> RoleCapacity:
    _get_or_404(db, ResourceRole, payload.role_id, "Resource role")
    capacity = RoleCapacity(**payload.model_dump())
    db.add(capacity)
    _commit(db, "Role capacity conflicts with existing data")
    db.refresh(capacity)
    return capacity


@router.patch("/capacities/{capacity_id}", response_model=RoleCapacityRead)
def update_capacity(
    capacity_id: int,
    payload: RoleCapacityUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> RoleCapacity:
    capacity = _get_or_404(db, RoleCapacity, capacity_id, "Role capacity")
    values = payload.model_dump(exclude_unset=True)
    period_start = values.get("period_start", capacity.period_start)
    period_end = values.get("period_end", capacity.period_end)
    if period_end <= period_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period_end must be after period_start",
        )
    for field, value in values.items():
        setattr(capacity, field, value)
    db.add(capacity)
    _commit(db, "Role capacity update conflicts with existing data")
    db.refresh(capacity)
    return capacity
