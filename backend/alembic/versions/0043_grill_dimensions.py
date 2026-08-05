"""Per-dimension grill outcomes — the completion standard (AL-297 / PRD-15 D1).

Approval is derived from whether the grill is finished, and "finished" has to mean the
same thing on every instance: four fixed dimensions (scope edges, failure modes,
contracts, open decisions), three outcomes each (resolved, deferred, unanswered).

A dimension with no row is `unanswered`, so existing PRDs need no backfill — none of them
were graded against this standard and pretending otherwise would manufacture approvals.
PRDs already marked `approved` under the old manual model keep that status; AL-300
governs transitions from here rather than recomputing history.

Revision ID: 0043
Revises: 0042
"""
from alembic import op
import sqlalchemy as sa

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "grill_dimensions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prd_id", sa.String(), nullable=False),
        sa.Column("dimension", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("turn_seq", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["prd_id"], ["prds.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prd_id", "dimension", name="uq_grill_dimension"),
    )
    op.create_index(op.f("ix_grill_dimensions_prd_id"), "grill_dimensions", ["prd_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_grill_dimensions_prd_id"), table_name="grill_dimensions")
    op.drop_table("grill_dimensions")
