from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user, get_current_admin_user
from waterfall.db.session import get_db
from waterfall.models.resources import (
    Calendar,
    CalendarWeekday,
    CostCategory,
    CostRate,
    CostType,
    EstimateCostLine,
    InflationRate,
    ResourceNode,
    ResourceRole,
    RoleCapacity,
)
from waterfall.models.user import User
from waterfall.schemas.resources import (
    CalendarCreate,
    CalendarRead,
    CalendarUpdate,
    CalendarWeekdayCreate,
    CalendarWeekdayRead,
    CostCategoryCreate,
    CostCategoryRead,
    CostCategoryUpdate,
    CostRateCreate,
    CostRateRead,
    CostRateUpdate,
    CostTypeCreate,
    CostTypeRead,
    CostTypeUpdate,
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


def _get_active_category_or_400(db: Session, category_id: int) -> CostCategory:
    category = (
        db.query(CostCategory)
        .filter(CostCategory.id == category_id)
        .filter(CostCategory.is_active.is_(True))
        .first()
    )
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cost category not found or inactive",
        )
    return category


def _category_in_use(db: Session, category_id: int) -> bool:
    used_by_role = (
        db.query(ResourceRole).filter(ResourceRole.cost_category_id == category_id).first()
        is not None
    )
    used_by_cost_line = (
        db.query(EstimateCostLine).filter(EstimateCostLine.cost_category_id == category_id).first()
        is not None
    )
    return used_by_role or used_by_cost_line


def _validate_node_parent(db: Session, node_id: int, parent_id: int | None) -> None:
    if parent_id is None:
        return

    visited: set[int] = set()
    current_id: int | None = parent_id
    while current_id is not None:
        if current_id == node_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Node cannot be assigned below its descendant",
            )
        if current_id in visited:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Resource hierarchy contains a cycle",
            )
        visited.add(current_id)
        current_node = _get_or_404(db, ResourceNode, current_id, "Parent node")
        current_id = current_node.parent_id


def _descendant_node_ids(db: Session, node_id: int) -> set[int]:
    nodes = db.query(ResourceNode.id, ResourceNode.parent_id).all()
    children_by_parent: dict[int | None, list[int]] = {}
    for child_id, parent_id in nodes:
        children_by_parent.setdefault(parent_id, []).append(child_id)

    descendants = {node_id}
    pending = [node_id]
    while pending:
        current_id = pending.pop()
        for child_id in children_by_parent.get(current_id, []):
            if child_id not in descendants:
                descendants.add(child_id)
                pending.append(child_id)
    return descendants


def _get_calendar_for_update_or_404(db: Session, calendar_id: int) -> Calendar:
    # Locks the Calendar row for the remainder of the transaction (released on
    # commit/rollback) so a concurrent request cannot read a stale is_active value
    # between this check and the write it guards -- see issue #50. SQLite (used by
    # the default test suite) has no SELECT ... FOR UPDATE semantics; SQLAlchemy's
    # sqlite dialect silently drops the clause, so this is a no-op there and existing
    # SQLite-backed tests are unaffected. The lock only takes effect on PostgreSQL.
    calendar = db.query(Calendar).filter(Calendar.id == calendar_id).with_for_update().first()
    if calendar is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar not found")
    return calendar


def _get_active_calendar_or_400(db: Session, calendar_id: int) -> Calendar:
    calendar = _get_calendar_for_update_or_404(db, calendar_id)
    if not calendar.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Calendar is inactive and cannot be assigned",
        )
    return calendar


def _ensure_calendar_not_assigned_to_active_role(db: Session, calendar_id: int) -> None:
    assigned_role = (
        db.query(ResourceRole.id)
        .filter(ResourceRole.calendar_id == calendar_id)
        .filter(ResourceRole.is_active.is_(True))
        .first()
    )
    if assigned_role is not None:
        raise _conflict("Calendar is assigned to active resource roles and cannot be deactivated")


def _ensure_calendar_not_default(calendar: Calendar) -> None:
    # No DB query needed: the row is already loaded/locked by
    # _get_calendar_for_update_or_404 (see issue #50), so its in-memory
    # is_default reflects the value under the current transaction's lock.
    if calendar.is_default:
        raise _conflict(
            "Calendar is the system default calendar and cannot be deactivated or deleted"
        )


def _weekdays_by_calendar(db: Session, calendar_ids: list[int]) -> dict[int, list[CalendarWeekday]]:
    if not calendar_ids:
        return {}
    weekdays = (
        db.query(CalendarWeekday)
        .filter(CalendarWeekday.calendar_id.in_(calendar_ids))
        .order_by(CalendarWeekday.calendar_id, CalendarWeekday.day_type)
        .all()
    )
    grouped: dict[int, list[CalendarWeekday]] = {}
    for weekday in weekdays:
        grouped.setdefault(weekday.calendar_id, []).append(weekday)
    return grouped


def _calendar_read(calendar: Calendar, weekdays: list[CalendarWeekday]) -> CalendarRead:
    payload = CalendarRead.model_validate(calendar)
    payload.weekdays = [CalendarWeekdayRead.model_validate(weekday) for weekday in weekdays]
    return payload


def _replace_calendar_weekdays(
    db: Session,
    calendar_id: int,
    weekdays: list[CalendarWeekdayCreate],
) -> None:
    db.query(CalendarWeekday).filter(CalendarWeekday.calendar_id == calendar_id).delete(
        synchronize_session=False
    )
    for weekday in weekdays:
        db.add(
            CalendarWeekday(
                calendar_id=calendar_id,
                day_type=weekday.day_type,
                hours_per_day=weekday.hours_per_day,
            )
        )


@router.get("/calendars", response_model=list[CalendarRead])
def list_calendars(
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> list[CalendarRead]:
    query = db.query(Calendar)
    if not include_inactive:
        query = query.filter(Calendar.is_active.is_(True))
    calendars = query.order_by(Calendar.code).all()
    grouped = _weekdays_by_calendar(db, [calendar.id for calendar in calendars])
    return [_calendar_read(calendar, grouped.get(calendar.id, [])) for calendar in calendars]


@router.post("/calendars", response_model=CalendarRead, status_code=status.HTTP_201_CREATED)
def create_calendar(
    payload: CalendarCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> CalendarRead:
    calendar = Calendar(
        code=payload.code,
        name=payload.name,
        weeks_per_year=payload.weeks_per_year,
    )
    db.add(calendar)
    _flush(db, "Calendar code already exists")
    _replace_calendar_weekdays(db, calendar.id, payload.weekdays)
    return _snapshot_and_commit(
        db,
        "Calendar code already exists",
        lambda: _calendar_read(
            calendar, _weekdays_by_calendar(db, [calendar.id]).get(calendar.id, [])
        ),
    )


@router.get("/calendars/{calendar_id}", response_model=CalendarRead)
def get_calendar(
    calendar_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> CalendarRead:
    calendar = _get_or_404(db, Calendar, calendar_id, "Calendar")
    return _calendar_read(calendar, _weekdays_by_calendar(db, [calendar_id]).get(calendar_id, []))


@router.patch("/calendars/{calendar_id}", response_model=CalendarRead)
def update_calendar(
    calendar_id: int,
    payload: CalendarUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> CalendarRead:
    calendar = _get_calendar_for_update_or_404(db, calendar_id)
    values = payload.model_dump(exclude_unset=True)
    values.pop("weekdays", None)
    if values.get("is_active") is False:
        _ensure_calendar_not_assigned_to_active_role(db, calendar_id)
        _ensure_calendar_not_default(calendar)

    # is_default is the only field that can never be applied by a plain setattr: promoting
    # a new default calendar must atomically demote whichever calendar currently holds the
    # flag (the partial unique index only allows one true row at a time), and unsetting the
    # current default without promoting a replacement in the same call is rejected outright
    # -- see issue #51.
    if "is_default" in values:
        promote_as_default = values.pop("is_default")
        if promote_as_default:
            effective_is_active = values.get("is_active", calendar.is_active)
            if not effective_is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Only an active calendar can be set as default",
                )
            previous_default = (
                db.query(Calendar)
                .filter(Calendar.is_default.is_(True))
                .filter(Calendar.id != calendar_id)
                .with_for_update()
                .first()
            )
            if previous_default is not None:
                previous_default.is_default = False
                db.add(previous_default)
                # Force the demotion UPDATE to hit the database before the promotion
                # below is applied. SQLAlchemy's unit of work batches same-table
                # UPDATEs ordered by primary key, not by session-attach order, so
                # without this explicit flush, promoting a calendar whose id is
                # LOWER than previous_default.id would flush "calendar.is_default =
                # true" first while previous_default.is_default is still true in
                # the database -- an immediate, non-deferrable violation of the
                # partial unique index uq_wf_calendar_is_default_true, surfacing as
                # a spurious 409 for an otherwise valid promotion.
                db.flush()
            calendar.is_default = True
        elif calendar.is_default:
            raise _conflict(
                "Cannot unset the default calendar directly; promote another calendar as "
                "default instead (PATCH it with is_default=true)"
            )
        # else: setting is_default=false on a calendar that is already not the default is
        # a harmless no-op.

    # Known v1 limitation: editing an active calendar's weekdays here does not
    # recalculate duration_minutes on any draft planning task whose role is
    # already staffed with this calendar -- that only happens on the next
    # move_planning_tasks call (see planning_tree.py). Left for E3-03.
    for field, value in values.items():
        setattr(calendar, field, value)
    db.add(calendar)
    if payload.weekdays is not None:
        _replace_calendar_weekdays(db, calendar_id, payload.weekdays)
    return _snapshot_and_commit(
        db,
        "Calendar update conflicts with existing data",
        lambda: _calendar_read(
            calendar, _weekdays_by_calendar(db, [calendar_id]).get(calendar_id, [])
        ),
    )


@router.delete("/calendars/{calendar_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calendar(
    calendar_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> None:
    calendar = _get_calendar_for_update_or_404(db, calendar_id)
    _ensure_calendar_not_assigned_to_active_role(db, calendar_id)
    _ensure_calendar_not_default(calendar)
    calendar.is_active = False
    db.add(calendar)
    _commit(db, "Calendar deletion conflicts with existing data")


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
) -> ResourceNodeRead:
    if payload.parent_id is not None:
        _get_or_404(db, ResourceNode, payload.parent_id, "Parent node")
    node = ResourceNode(**payload.model_dump())
    db.add(node)
    return _snapshot_and_commit(
        db,
        "Resource node code already exists",
        lambda: ResourceNodeRead.model_validate(node),
    )


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
) -> ResourceNodeRead:
    node = _get_or_404(db, ResourceNode, node_id, "Resource node")
    if payload.parent_id is not None:
        _validate_node_parent(db, node.id, payload.parent_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(node, field, value)
    db.add(node)
    return _snapshot_and_commit(
        db,
        "Resource node update conflicts with existing data",
        lambda: ResourceNodeRead.model_validate(node),
    )


@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_node(
    node_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> None:
    node = _get_or_404(db, ResourceNode, node_id, "Resource node")
    has_children = db.query(ResourceNode.id).filter(ResourceNode.parent_id == node_id).first()
    if has_children is not None:
        raise _conflict("Resource node has child nodes and cannot be deleted")
    has_roles = db.query(ResourceRole.id).filter(ResourceRole.node_id == node_id).first()
    if has_roles is not None:
        raise _conflict("Resource node has roles and cannot be deleted")
    node.is_active = False
    db.add(node)
    _commit(db, "Resource node deletion conflicts with existing data")


@router.get("/roles", response_model=list[ResourceRoleRead])
def list_roles(
    node_id: int | None = Query(default=None, gt=0),
    include_descendants: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> list[ResourceRole]:
    query = db.query(ResourceRole).filter(ResourceRole.is_active.is_(True))
    if node_id is not None:
        _get_or_404(db, ResourceNode, node_id, "Resource node")
        if include_descendants:
            query = query.filter(ResourceRole.node_id.in_(_descendant_node_ids(db, node_id)))
        else:
            query = query.filter(ResourceRole.node_id == node_id)
    return query.order_by(ResourceRole.name).all()


@router.post("/roles", response_model=ResourceRoleRead, status_code=status.HTTP_201_CREATED)
def create_role(
    payload: ResourceRoleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> ResourceRoleRead:
    _get_or_404(db, ResourceNode, payload.node_id, "Resource node")
    _get_active_category_or_400(db, payload.cost_category_id)
    if payload.calendar_id is not None:
        _get_active_calendar_or_400(db, payload.calendar_id)
    role = ResourceRole(**payload.model_dump())
    db.add(role)
    return _snapshot_and_commit(
        db,
        "Resource role creation conflicts with existing data",
        lambda: ResourceRoleRead.model_validate(role),
    )


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
) -> ResourceRoleRead:
    role = _get_or_404(db, ResourceRole, role_id, "Resource role")
    values = payload.model_dump(exclude_unset=True)
    if "node_id" in values:
        _get_or_404(db, ResourceNode, values["node_id"], "Resource node")
    if "cost_category_id" in values:
        _get_active_category_or_400(db, values["cost_category_id"])
    # Validate/lock the *effective* calendar (payload value if provided, else the
    # role's current one) whenever the role ends up active with a calendar_id --
    # not just when calendar_id itself is part of this PATCH. Otherwise
    # reactivating a role via {"is_active": true} alone could silently leave it
    # pointing at a calendar that was deactivated while the role was inactive.
    # See issue #50 for the original locking rationale.
    effective_calendar_id = values.get("calendar_id", role.calendar_id)
    effective_is_active = values.get("is_active", role.is_active)
    if effective_is_active and effective_calendar_id is not None:
        _get_active_calendar_or_400(db, effective_calendar_id)
    for field, value in values.items():
        setattr(role, field, value)
    db.add(role)
    return _snapshot_and_commit(
        db,
        "Resource role update conflicts with existing data",
        lambda: ResourceRoleRead.model_validate(role),
    )


@router.get("/categories", response_model=list[CostCategoryRead])
def list_categories(
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> list[CostCategory]:
    query = db.query(CostCategory)
    if not include_inactive:
        query = query.filter(CostCategory.is_active.is_(True))
    return query.order_by(CostCategory.accounting_code).all()


@router.get("/cost-types", response_model=list[CostTypeRead])
def list_cost_types(
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> list[CostType]:
    query = db.query(CostType)
    if not include_inactive:
        query = query.filter(CostType.is_active.is_(True))
    return query.order_by(CostType.code).all()


@router.post("/cost-types", response_model=CostTypeRead, status_code=status.HTTP_201_CREATED)
def create_cost_type(
    payload: CostTypeCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> CostTypeRead:
    cost_type = CostType(**payload.model_dump())
    db.add(cost_type)
    return _snapshot_and_commit(
        db,
        "Cost type code already exists",
        lambda: CostTypeRead.model_validate(cost_type),
    )


@router.patch("/cost-types/{cost_type_id}", response_model=CostTypeRead)
def update_cost_type(
    cost_type_id: int,
    payload: CostTypeUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> CostTypeRead:
    cost_type = _get_or_404(db, CostType, cost_type_id, "Cost type")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(cost_type, field, value)
    db.add(cost_type)
    return _snapshot_and_commit(
        db,
        "Cost type update conflicts with existing data",
        lambda: CostTypeRead.model_validate(cost_type),
    )


@router.post("/categories", response_model=CostCategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CostCategoryCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> CostCategoryRead:
    _get_or_404(db, CostType, payload.cost_type_id, "Cost type")
    category = CostCategory(**payload.model_dump())
    db.add(category)
    return _snapshot_and_commit(
        db,
        "Cost category code already exists",
        lambda: CostCategoryRead.model_validate(category),
    )


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
) -> CostCategoryRead:
    category = _get_or_404(db, CostCategory, category_id, "Cost category")
    values = payload.model_dump(exclude_unset=True)
    if "cost_type_id" in values and values["cost_type_id"] != category.cost_type_id:
        _get_or_404(db, CostType, values["cost_type_id"], "Cost type")
        if _category_in_use(db, category_id):
            raise _conflict("Cost category is already in use and cannot change type")
    for field, value in values.items():
        setattr(category, field, value)
    db.add(category)
    return _snapshot_and_commit(
        db,
        "Cost category update conflicts with existing data",
        lambda: CostCategoryRead.model_validate(category),
    )


@router.get("/categories/{category_id}/rates", response_model=list[CostRateRead])
def list_category_rates(
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
) -> CostRateRead:
    _get_or_404(db, CostCategory, payload.cost_category_id, "Cost category")
    rate = CostRate(**payload.model_dump())
    db.add(rate)
    return _snapshot_and_commit(
        db,
        "A cost rate already exists for this category and year",
        lambda: CostRateRead.model_validate(rate),
    )


@router.get("/rates", response_model=list[CostRateRead])
def list_rates(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> list[CostRate]:
    return db.query(CostRate).order_by(CostRate.year, CostRate.cost_category_id).all()


@router.patch("/rates/{rate_id}", response_model=CostRateRead)
def update_rate(
    rate_id: int,
    payload: CostRateUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> CostRateRead:
    rate = _get_or_404(db, CostRate, rate_id, "Cost rate")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rate, field, value)
    db.add(rate)
    return _snapshot_and_commit(
        db,
        "Cost rate update conflicts with existing data",
        lambda: CostRateRead.model_validate(rate),
    )


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
) -> InflationRateRead:
    rate = db.query(InflationRate).filter(InflationRate.year == year).first()
    if rate is None:
        coefficient = payload.coefficient
        rate = InflationRate(year=year, coefficient=coefficient)
        db.add(rate)
    else:
        rate.coefficient = payload.coefficient
        db.add(rate)
    return _snapshot_and_commit(
        db,
        "Inflation rate update conflicts with existing data",
        lambda: InflationRateRead.model_validate(rate),
    )


@router.get("/capacities", response_model=list[RoleCapacityRead])
def list_capacities(
    role_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
) -> list[RoleCapacity]:
    query = db.query(RoleCapacity)
    if role_id is not None:
        query = query.filter(RoleCapacity.role_id == role_id)
    return query.order_by(RoleCapacity.role_id).all()


@router.post("/capacities", response_model=RoleCapacityRead, status_code=status.HTTP_201_CREATED)
def create_capacity(
    payload: RoleCapacityCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> RoleCapacityRead:
    _get_or_404(db, ResourceRole, payload.role_id, "Resource role")
    capacity = db.query(RoleCapacity).filter(RoleCapacity.role_id == payload.role_id).one_or_none()
    if capacity is None:
        capacity = RoleCapacity(**payload.model_dump())
        db.add(capacity)
    else:
        capacity.person_count = payload.person_count
        capacity.available_hours = payload.available_hours
    return _snapshot_and_commit(
        db,
        "Role capacity conflicts with existing data",
        lambda: RoleCapacityRead.model_validate(capacity),
    )


@router.patch("/capacities/{capacity_id}", response_model=RoleCapacityRead)
def update_capacity(
    capacity_id: int,
    payload: RoleCapacityUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> RoleCapacityRead:
    capacity = _get_or_404(db, RoleCapacity, capacity_id, "Role capacity")
    values = payload.model_dump(exclude_unset=True)
    for field, value in values.items():
        setattr(capacity, field, value)
    db.add(capacity)
    return _snapshot_and_commit(
        db,
        "Role capacity update conflicts with existing data",
        lambda: RoleCapacityRead.model_validate(capacity),
    )
