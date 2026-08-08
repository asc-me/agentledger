"""Record when an item was attached to its PRD (GRPH-243 / PRD-12).

Scope-drift reports "items linked to the PRD after approval". `created_at` cannot answer
that: an item raised months before a PRD existed and linked to it after approval is scope
*added*, and reading its creation time files it as original scope — under-reporting the
growth the feature exists to surface.

Left NULL for rows that predate the column rather than backfilled from `created_at`.
Backfilling would invent a fact nobody recorded and make it indistinguishable from a
measured one; `scope_drift` instead falls back to `created_at` for NULLs and reports how
many readings it had to infer, so the number carries its own caveat.

Revision ID: 0048
Revises: 0047
"""
from alembic import op
import sqlalchemy as sa

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("items", sa.Column("prd_linked_at", sa.DateTime(timezone=True),
                                     nullable=True))


def downgrade() -> None:
    op.drop_column("items", "prd_linked_at")
