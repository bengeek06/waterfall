"""project cost code (E6-01, issue #62)

Adds `wf_project_cost_code`: a project-scoped tree of user-defined cost-imputation
codes, structurally identical to `wf_resource_node` (self-referencing `parent_id`,
`code` + `name` + `is_active`), except uniqueness of `code` is scoped per project
(`UniqueConstraint(project_id, code)`) rather than global, and exactly one root row
(`parent_id IS NULL`) is enforced per project via a partial unique index -- the same
pattern as `uq_wf_calendar_is_default_true` (issue #51): SQLite and PostgreSQL each
need their own dialect-specific partial-index kwarg to actually produce a partial
index.

Backfills a root cost code for every project that already exists at migration time,
using the same rule the API applies at project-creation time going forward:
`code = ms_project.code` when set, or the deterministic `PRJ-{id}` fallback when
`ms_project.code` is NULL.

Revision ID: 20260909_0009
Revises: 20260908_0008
Create Date: 2026-09-09 09:00:00.000000

"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260909_0009"
down_revision = "20260908_0008"
branch_labels = None
depends_on = None

SINGLE_ROOT_INDEX_NAME = "uq_wf_project_cost_code_single_root"


def upgrade() -> None:
    op.create_table(
        "wf_project_cost_code",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["ms_project.id"]),
        sa.ForeignKeyConstraint(["parent_id"], ["wf_project_cost_code.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "code", name="uq_wf_project_cost_code_project_code"),
    )
    op.create_index(
        "idx_wf_project_cost_code_project", "wf_project_cost_code", ["project_id"], unique=False
    )
    op.create_index(
        "idx_wf_project_cost_code_parent", "wf_project_cost_code", ["parent_id"], unique=False
    )
    op.create_index(
        SINGLE_ROOT_INDEX_NAME,
        "wf_project_cost_code",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NULL"),
        sqlite_where=sa.text("parent_id IS NULL"),
    )

    # Backfill a root cost code for every project that already exists, using the same
    # rule the API applies going forward (see create_project in
    # api/routes/projects.py): code = ms_project.code when set, else PRJ-{id}.
    connection = op.get_bind()
    project_table = sa.table(
        "ms_project",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("code", sa.String),
    )
    cost_code_table = sa.table(
        "wf_project_cost_code",
        sa.column("project_id", sa.Integer),
        sa.column("parent_id", sa.Integer),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    now = datetime.now(UTC)
    projects = connection.execute(
        sa.select(project_table.c.id, project_table.c.name, project_table.c.code)
    ).all()
    if projects:
        connection.execute(
            sa.insert(cost_code_table).values(
                [
                    {
                        "project_id": project.id,
                        "parent_id": None,
                        "code": project.code or f"PRJ-{project.id}",
                        "name": project.name,
                        "is_active": True,
                        "created_at": now,
                        "updated_at": now,
                    }
                    for project in projects
                ]
            )
        )


def downgrade() -> None:
    op.drop_index(SINGLE_ROOT_INDEX_NAME, table_name="wf_project_cost_code")
    op.drop_index("idx_wf_project_cost_code_parent", table_name="wf_project_cost_code")
    op.drop_index("idx_wf_project_cost_code_project", table_name="wf_project_cost_code")
    op.drop_table("wf_project_cost_code")
