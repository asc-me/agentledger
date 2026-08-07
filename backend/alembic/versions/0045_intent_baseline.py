"""Mark the agreed spec: intent baselines on prd_versions (AL-239 / PRD-12 slice A).

A baseline is the snapshot taken when a PRD is approved — since PRD-15, when its grill
concludes. Everything PRD-12 does downstream compares shipped work against it, so it has
to be distinguishable from the ordinary snapshots that pile up during drafting.

`grill_outcomes` carries the per-dimension verdicts as they stood at approval. A
dimension the author deliberately DEFERRED is the interesting case: later divergence
there was foreseen and agreed, and a drift report that cannot tell it from an unplanned
change would cry wolf on the one thing everybody already knew about.

No backfill. Existing rows are ordinary snapshots, which is accurate — none of them were
taken at an approval under this rule, and marking one retroactively would invent an
agreement that never happened.

Revision ID: 0045
Revises: 0044
"""
from alembic import op
import sqlalchemy as sa

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "prd_versions",
        sa.Column("is_baseline", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("prd_versions", sa.Column("grill_outcomes", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("prd_versions", "grill_outcomes")
    op.drop_column("prd_versions", "is_baseline")
