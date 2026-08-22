"""Store planning structure drafts separately from user notes."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260822_0010"
down_revision = "20260822_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("wf_planning") as batch_op:
        batch_op.add_column(sa.Column("structure_draft_json", sa.Text(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE wf_planning "
            "SET structure_draft_json = substr(note, :prefix_length + 1), note = NULL "
            "WHERE note LIKE :prefix_pattern"
        ).bindparams(
            prefix_length=len("planning-structure-draft:"),
            prefix_pattern="planning-structure-draft:%",
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("wf_planning") as batch_op:
        batch_op.drop_column("structure_draft_json")
