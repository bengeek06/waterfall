from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from waterfall.db.base import Base


class WfPlanning(Base):
    __tablename__ = "wf_planning"
    __table_args__ = (
        CheckConstraint("version_number > 0", name="ck_wf_planning_version"),
        CheckConstraint(
            "status IN ('draft', 'validated', 'superseded')",
            name="ck_wf_planning_status",
        ),
        UniqueConstraint("project_id", "version_number", name="uq_wf_planning_project_version"),
        UniqueConstraint("project_id", "id", name="uq_wf_planning_project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("ms_project.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    structure_draft_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WfPlanningTaskSnapshot(Base):
    __tablename__ = "wf_planning_task_snapshot"
    __table_args__ = (
        UniqueConstraint("planning_id", "uid", name="uq_wf_planning_task_snapshot_uid"),
        UniqueConstraint(
            "planning_id", "structure_key", name="uq_wf_planning_task_snapshot_structure_key"
        ),
        ForeignKeyConstraint(
            ["planning_id", "parent_uid"],
            ["wf_planning_task_snapshot.planning_id", "wf_planning_task_snapshot.uid"],
            name="fk_wf_planning_task_snapshot_parent",
        ),
        CheckConstraint(
            "task_type IN (0, 1, 2) OR task_type IS NULL",
            name="ck_wf_planning_task_snapshot_type",
        ),
        CheckConstraint(
            "structure_kind IN ('poste', 'lot', 'livrable', 'milestone', 'task') "
            "OR structure_kind IS NULL",
            name="ck_wf_planning_task_snapshot_structure_kind",
        ),
        CheckConstraint(
            "parent_uid IS NULL OR parent_uid > 0",
            name="ck_wf_planning_task_snapshot_parent_uid",
        ),
        CheckConstraint(
            "position IS NULL OR position > 0",
            name="ck_wf_planning_task_snapshot_position",
        ),
        CheckConstraint(
            "percent_complete BETWEEN 0 AND 100 OR percent_complete IS NULL",
            name="ck_wf_planning_task_snapshot_percent_complete",
        ),
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes >= 0",
            name="ck_wf_planning_task_snapshot_duration",
        ),
        CheckConstraint(
            "work_minutes IS NULL OR work_minutes >= 0",
            name="ck_wf_planning_task_snapshot_work",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    planning_id: Mapped[int] = mapped_column(ForeignKey("wf_planning.id"), nullable=False)
    uid: Mapped[int] = mapped_column(Integer, nullable=False)
    id_display: Mapped[int | None] = mapped_column(Integer, nullable=True)
    structure_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    structure_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    parent_uid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class WfPlanningLinkSnapshot(Base):
    __tablename__ = "wf_planning_link_snapshot"
    __table_args__ = (
        ForeignKeyConstraint(
            ["planning_id", "task_uid"],
            ["wf_planning_task_snapshot.planning_id", "wf_planning_task_snapshot.uid"],
            name="fk_wf_planning_link_snapshot_task",
        ),
        ForeignKeyConstraint(
            ["planning_id", "predecessor_uid"],
            ["wf_planning_task_snapshot.planning_id", "wf_planning_task_snapshot.uid"],
            name="fk_wf_planning_link_snapshot_pred",
        ),
        UniqueConstraint(
            "planning_id",
            "task_uid",
            "predecessor_uid",
            "link_type",
            name="uq_wf_planning_link_snapshot",
        ),
        CheckConstraint("link_type IN (0, 1, 2, 3)", name="ck_wf_planning_link_snapshot_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    planning_id: Mapped[int] = mapped_column(ForeignKey("wf_planning.id"), nullable=False)
    task_uid: Mapped[int] = mapped_column(Integer, nullable=False)
    predecessor_uid: Mapped[int] = mapped_column(Integer, nullable=False)
    link_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    lag_tenth_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lag_format: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
