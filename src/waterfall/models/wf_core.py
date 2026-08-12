from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from waterfall.db.base import Base


class WfImportBatch(Base):
    __tablename__ = "wf_import_batch"
    __table_args__ = (
        CheckConstraint("import_mode IN ('standard', 'full')", name="ck_wf_import_batch_mode"),
        CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_wf_import_batch_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("ms_project.id"), nullable=True)
    import_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    log_json: Mapped[str | None] = mapped_column(String, nullable=True)


class WfExcelImport(Base):
    __tablename__ = "wf_excel_import"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_wf_excel_import_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("ms_project.id"), nullable=False)
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_import_batch.id"),
        nullable=True,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    log_json: Mapped[str | None] = mapped_column(String, nullable=True)


class WfChargeLine(Base):
    __tablename__ = "wf_charge_line"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "task_uid"],
            ["ms_task.project_id", "ms_task.uid"],
            name="fk_wf_charge_line_task",
        ),
        CheckConstraint("load_minutes >= 0", name="ck_wf_charge_line_load_non_negative"),
        Index("idx_wf_charge_line_task", "project_id", "task_uid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("ms_project.id"), nullable=False)
    task_uid: Mapped[int] = mapped_column(Integer, nullable=False)
    load_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_cost: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    source_excel_import_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_excel_import.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
