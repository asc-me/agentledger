"""Persist the grill conversation server-side (AL-296 / PRD-15 D4).

The grill lived entirely in the client: it posted the whole transcript to
`/grill/stream` and `/grill/apply` and nothing was retained. Acceptable while the grill
was advisory; not acceptable now that PRD-15 derives approval from it, because the
server has to answer "has this PRD been grilled, and is anything still open?" without
taking a caller's word for it.

Additive and independent of the memory shards `capture_grill_decisions` already writes.
Those keep the durable CONTENT of each decision; this keeps the STRUCTURE of the
conversation. Existing PRDs simply have no turns, which reads correctly as "not grilled".

Revision ID: 0042
Revises: 0041
"""
from alembic import op
import sqlalchemy as sa

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "grill_turns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prd_id", sa.String(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["prd_id"], ["prds.id"]),
        sa.PrimaryKeyConstraint("id"),
        # A double-submitted round can't interleave into the same position.
        sa.UniqueConstraint("prd_id", "seq", name="uq_grill_turn_seq"),
    )
    op.create_index(op.f("ix_grill_turns_prd_id"), "grill_turns", ["prd_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_grill_turns_prd_id"), table_name="grill_turns")
    op.drop_table("grill_turns")
