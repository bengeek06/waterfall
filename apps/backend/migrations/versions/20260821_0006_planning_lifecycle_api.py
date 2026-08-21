"""align project lifecycle and add estimate reference

Revision ID: 20260821_0006
Revises: 20260821_0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260821_0006"
down_revision = "20260821_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ms_project") as batch_op:
        batch_op.drop_constraint("ck_ms_project_status", type_="check")
        batch_op.add_column(sa.Column("reference_estimate_id", sa.Integer(), nullable=True))
        batch_op.alter_column("status", type_=sa.String(length=24))
        batch_op.create_foreign_key(
            "fk_ms_project_reference_estimate",
            "wf_estimate",
            ["reference_estimate_id"],
            ["id"],
        )
        batch_op.alter_column("status", server_default="cree")
    op.execute(
        sa.text(
            "UPDATE ms_project SET status = CASE status "
            "WHEN 'active' THEN 'initialise' ELSE 'cree' END"
        )
    )
    with op.batch_alter_table("ms_project") as batch_op:
        batch_op.create_check_constraint(
            "ck_ms_project_status",
            "status IN ('cree', 'initialise', 'en_reponse_appel_offre', 'perdu', "
            "'en_cours', 'termine', 'abandonne')",
        )


def downgrade() -> None:
    with op.batch_alter_table("ms_project") as batch_op:
        batch_op.drop_constraint("fk_ms_project_reference_estimate", type_="foreignkey")
        batch_op.drop_column("reference_estimate_id")
        batch_op.drop_constraint("ck_ms_project_status", type_="check")
    op.execute(
        sa.text(
            "UPDATE ms_project SET status = CASE status "
            "WHEN 'cree' THEN 'draft' "
            "WHEN 'initialise' THEN 'active' "
            "WHEN 'en_reponse_appel_offre' THEN 'active' "
            "WHEN 'perdu' THEN 'archived' "
            "WHEN 'en_cours' THEN 'active' "
            "WHEN 'termine' THEN 'archived' "
            "WHEN 'abandonne' THEN 'archived' "
            "ELSE 'draft' END"
        )
    )
    with op.batch_alter_table("ms_project") as batch_op:
        batch_op.create_check_constraint(
            "ck_ms_project_status", "status IN ('draft', 'active', 'archived')"
        )
        batch_op.alter_column("status", type_=sa.String(length=16))
        batch_op.alter_column("status", server_default="draft")
