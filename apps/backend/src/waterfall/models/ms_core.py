from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from waterfall.db.base import Base


class MsProject(Base):
    __tablename__ = "ms_project"
    __table_args__ = (
        CheckConstraint(
            "source_version IN (2010, 2013, 2016)",
            name="ck_ms_project_source_version",
        ),
        CheckConstraint(
            "save_version_out IN (14, 15, 16)",
            name="ck_ms_project_save_version_out",
        ),
        CheckConstraint(
            "(schedule_from_start = true AND start_date IS NOT NULL) OR "
            "(schedule_from_start = false AND finish_date IS NOT NULL)",
            name="ck_ms_project_schedule_dates",
        ),
        Index("idx_ms_project_name", "name"),
        CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="ck_ms_project_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    external_uid: Mapped[str | None] = mapped_column(String(16), nullable=True)
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    short_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    save_version_out: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=16)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    schedule_from_start: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finish_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    calendar_uid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minutes_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=480)
    minutes_per_week: Mapped[int] = mapped_column(Integer, nullable=False, default=2400)
    days_per_month: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    planning_reference_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    displayed_planning_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )


class MsTask(Base):
    __tablename__ = "ms_task"
    __table_args__ = (
        UniqueConstraint("project_id", "uid", name="uq_ms_task_project_uid"),
        UniqueConstraint("project_id", "structure_key", name="uq_ms_task_project_structure_key"),
        ForeignKeyConstraint(
            ["project_id", "parent_uid"],
            ["ms_task.project_id", "ms_task.uid"],
            name="fk_ms_task_parent",
        ),
        CheckConstraint("task_type IN (0, 1, 2) OR task_type IS NULL", name="ck_ms_task_type"),
        CheckConstraint(
            "structure_kind IN ('poste', 'lot', 'livrable', 'milestone', 'task') "
            "OR structure_kind IS NULL",
            name="ck_ms_task_structure_kind",
        ),
        CheckConstraint(
            "parent_uid IS NULL OR parent_uid > 0",
            name="ck_ms_task_parent_uid_positive",
        ),
        CheckConstraint(
            "position IS NULL OR position > 0",
            name="ck_ms_task_position_positive",
        ),
        CheckConstraint(
            "percent_complete BETWEEN 0 AND 100 OR percent_complete IS NULL",
            name="ck_ms_task_percent_complete",
        ),
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes >= 0",
            name="ck_ms_task_duration_non_negative",
        ),
        CheckConstraint(
            "work_minutes IS NULL OR work_minutes >= 0",
            name="ck_ms_task_work_non_negative",
        ),
        Index("idx_ms_task_project_outline", "project_id", "outline_level", "outline_number"),
        Index("idx_ms_task_project_id_display", "project_id", "id_display"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("ms_project.id"), nullable=False)
    uid: Mapped[int] = mapped_column(Integer, nullable=False)
    id_display: Mapped[int | None] = mapped_column(Integer, nullable=True)
    structure_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    structure_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    parent_uid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    task_type: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    outline_number: Mapped[str | None] = mapped_column(String(512), nullable=True)
    outline_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wbs: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_format: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    work_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    percent_complete: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    is_summary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_milestone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_manual: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    calendar_uid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class MsTaskLink(Base):
    __tablename__ = "ms_task_link"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "task_uid"],
            ["ms_task.project_id", "ms_task.uid"],
            name="fk_ms_task_link_task",
        ),
        ForeignKeyConstraint(
            ["project_id", "predecessor_uid"],
            ["ms_task.project_id", "ms_task.uid"],
            name="fk_ms_task_link_pred",
        ),
        UniqueConstraint(
            "project_id",
            "task_uid",
            "predecessor_uid",
            "link_type",
            name="uq_ms_task_link",
        ),
        CheckConstraint("link_type IN (0, 1, 2, 3)", name="ck_ms_task_link_type"),
        Index("idx_ms_task_link_task_uid", "project_id", "task_uid"),
        Index("idx_ms_task_link_predecessor_uid", "project_id", "predecessor_uid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("ms_project.id"), nullable=False)
    task_uid: Mapped[int] = mapped_column(Integer, nullable=False)
    predecessor_uid: Mapped[int] = mapped_column(Integer, nullable=False)
    link_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    lag_tenth_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lag_format: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
