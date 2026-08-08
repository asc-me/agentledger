"""Stamp which baseline an item's work started against (GRPH-242 / GRPH-312 / PRD-12).

A rebaseline lands while other agents hold claims. The requesting agent knows intent
moved; the others do not, and keep building against superseded intent — their output then
lands as drift through no fault of their own.

PRD-12 wants that notice PULL-based, "so no push channel can fail and the agent cannot
miss it." This column is what makes the pull possible: record the governing baseline
version when work starts, and the hold is derived by comparing it against the baseline
now. Derived rather than stored means it cannot go stale, and there is nothing to
acknowledge away — the item WAS claimed under v1.0 and the baseline IS v1.1, and that
stays true regardless of who read what.

Left NULL for existing rows. Work that started before this was recorded cannot honestly
be said to target any particular intent, and inventing a version for it would put a
fabricated claim in the one record delivery acceptance is meant to check.

Revision ID: 0050
Revises: 0049
"""
from alembic import op
import sqlalchemy as sa

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("items", sa.Column("baseline_at_claim", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("items", "baseline_at_claim")
