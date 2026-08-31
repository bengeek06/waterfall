from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from waterfall.db.session import get_session_factory
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.resources import (
    Calendar,
    CalendarWeekday,
    CostCategory,
    CostRate,
    CostType,
    Estimate,
    EstimateLine,
    InflationRate,
    ResourceNode,
    ResourceRole,
    RoleCapacity,
    TaskRoleAssignment,
)


def _seed_resource_graph() -> tuple[int, int, int]:
    session_factory = get_session_factory()
    with session_factory() as session:
        cost_type = CostType(code="MO", name="Main d'oeuvre", kind="labor")
        session.add(cost_type)
        session.flush()

        category = CostCategory(
            cost_type_id=cost_type.id,
            accounting_code="DEV",
            category_code="IDEX",
            name="Developpement",
        )
        session.add(category)
        session.flush()

        node = ResourceNode(code="IT", name="Departement informatique")
        session.add(node)
        session.flush()

        role = ResourceRole(
            node_id=node.id,
            cost_category_id=category.id,
            name="Developpeur",
        )
        project = MsProject(
            external_uid=None,
            source_version=2016,
            save_version_out=16,
            name="Resource model test",
            schedule_from_start=True,
            start_date=datetime(2026, 1, 1, 8, tzinfo=UTC),
            finish_date=datetime(2026, 1, 31, 18, tzinfo=UTC),
            calendar_uid=None,
            minutes_per_day=480,
            minutes_per_week=2400,
            days_per_month=20,
            currency_code="EUR",
        )
        session.add_all([role, project])
        session.flush()

        task = MsTask(
            project_id=project.id,
            uid=1,
            id_display=1,
            name="Implementation",
            task_type=0,
            outline_number="1",
            outline_level=1,
            wbs="1",
            start_at=datetime(2026, 1, 1, 8, tzinfo=UTC),
            finish_at=datetime(2026, 1, 31, 18, tzinfo=UTC),
            duration_minutes=None,
            duration_format=None,
            work_minutes=None,
            percent_complete=0,
            is_summary=False,
            is_milestone=False,
            calendar_uid=None,
        )
        session.add(task)
        session.flush()

        session.add_all(
            [
                CostRate(
                    cost_category_id=category.id,
                    year=2026,
                    hourly_rate=Decimal("100.0000"),
                    currency_code="EUR",
                ),
                InflationRate(year=2026, coefficient=Decimal("1.00000000")),
                RoleCapacity(
                    role_id=role.id,
                    person_count=Decimal("2.00"),
                    available_hours=Decimal("3200.00"),
                ),
                TaskRoleAssignment(
                    task_id=task.id,
                    role_id=role.id,
                    quantity=Decimal("1.00"),
                    hours=Decimal("24.00"),
                ),
            ]
        )
        session.commit()
        return project.id, task.id, role.id


def test_resource_models_persist_assignments_and_estimate_snapshots() -> None:
    project_id, task_id, role_id = _seed_resource_graph()

    session_factory = get_session_factory()
    with session_factory() as session:
        estimate = Estimate(
            project_id=project_id,
            version_number=1,
            kind="initial",
            status="validated",
            currency_code="EUR",
            validated_at=datetime.now(UTC),
        )
        session.add(estimate)
        session.flush()
        session.add(
            EstimateLine(
                estimate_id=estimate.id,
                task_id=task_id,
                role_id=role_id,
                task_name="Implementation",
                role_code="DEV-SW",
                role_name="Developpeur",
                accounting_code="DEV",
                year=2026,
                quantity=Decimal("1.00"),
                hours=Decimal("24.00"),
                hourly_rate=Decimal("100.0000"),
                inflation_coefficient=Decimal("1.00000000"),
                budget_cost=Decimal("2400.00"),
            )
        )
        session.commit()

        assert session.query(TaskRoleAssignment).count() == 1
        assert session.query(EstimateLine).count() == 1


def test_resource_codes_are_unique() -> None:
    _seed_resource_graph()

    session_factory = get_session_factory()
    with session_factory() as session:
        session.add(ResourceNode(code="IT", name="Duplicate code"))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("resource node codes must be unique")


def _create_standard_calendar() -> int:
    session_factory = get_session_factory()
    with session_factory() as session:
        calendar = Calendar(code="STANDARD", name="Standard", weeks_per_year=47)
        session.add(calendar)
        session.flush()
        session.add_all(
            CalendarWeekday(
                calendar_id=calendar.id,
                day_type=day_type,
                hours_per_day=Decimal("0.00") if day_type in (1, 7) else Decimal("7.00"),
            )
            for day_type in range(1, 8)
        )
        session.commit()
        return calendar.id


def test_calendar_persists_full_week() -> None:
    calendar_id = _create_standard_calendar()

    session_factory = get_session_factory()
    with session_factory() as session:
        calendar = session.get(Calendar, calendar_id)
        assert calendar is not None
        assert calendar.weeks_per_year == 47
        assert calendar.is_active is True

        weekdays = (
            session.query(CalendarWeekday)
            .filter(CalendarWeekday.calendar_id == calendar_id)
            .order_by(CalendarWeekday.day_type)
            .all()
        )
        assert [weekday.day_type for weekday in weekdays] == [1, 2, 3, 4, 5, 6, 7]
        assert [Decimal(weekday.hours_per_day) for weekday in weekdays] == [
            Decimal("0.00"),
            Decimal("7.00"),
            Decimal("7.00"),
            Decimal("7.00"),
            Decimal("7.00"),
            Decimal("7.00"),
            Decimal("0.00"),
        ]


def test_calendar_weekday_rejects_hours_out_of_range() -> None:
    calendar_id = _create_standard_calendar()

    session_factory = get_session_factory()
    for invalid_hours in (Decimal("-1.00"), Decimal("24.01")):
        with session_factory() as session:
            session.add(
                CalendarWeekday(
                    calendar_id=calendar_id,
                    day_type=2,
                    hours_per_day=invalid_hours,
                )
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
            else:
                raise AssertionError("hours_per_day must stay within [0, 24]")


def test_calendar_weekday_rejects_duplicate_day_type() -> None:
    calendar_id = _create_standard_calendar()

    session_factory = get_session_factory()
    with session_factory() as session:
        session.add(
            CalendarWeekday(calendar_id=calendar_id, day_type=2, hours_per_day=Decimal("6.00"))
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("(calendar_id, day_type) must be unique")


def test_resource_role_calendar_is_optional() -> None:
    _, _, role_id = _seed_resource_graph()
    calendar_id = _create_standard_calendar()

    session_factory = get_session_factory()
    with session_factory() as session:
        role = session.get(ResourceRole, role_id)
        assert role is not None
        assert role.calendar_id is None

        role.calendar_id = calendar_id
        session.commit()

    with session_factory() as session:
        role = session.get(ResourceRole, role_id)
        assert role is not None
        assert role.calendar_id == calendar_id
