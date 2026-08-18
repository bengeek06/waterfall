"""store import xml outside database

Revision ID: 20260818_0007
Revises: 20260818_0006
Create Date: 2026-08-18 00:00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_0007"
down_revision = "20260818_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wf_import_batch",
        sa.Column("source_storage_path", sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("wf_import_batch", "source_storage_path")
