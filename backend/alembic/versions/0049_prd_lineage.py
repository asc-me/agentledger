"""PRD lineage for promoted dropped scope (GRPH-246 / PRD-12).

A PRD created to carry intent dropped from an earlier one points back at it. PRD-12:
*"the successor carries a lineage link back to the closed one — keeping the chain from
original intent, through what was dropped, to what came next walkable."*

Two columns, because the link alone only says a successor exists. `promoted_sections`
names the baselined sections it inherited, which is the "through what was dropped" part
of that sentence and the only reason the chain is walkable rather than merely present.

`supersedes_prd_id` is a plain String, not a ForeignKey. Deliberate: a successor may
outlive the PRD it came from in an export/import round trip, and a dangling lineage link
is a recoverable fact worth keeping, while an FK would make the parent undeletable or the
child collateral. It stores the FROZEN id, never a rendering — the GRPH-319 rule.

Revision ID: 0049
Revises: 0048
"""
from alembic import op
import sqlalchemy as sa

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prds", sa.Column("supersedes_prd_id", sa.String(), nullable=True))
    op.add_column("prds", sa.Column("promoted_sections", sa.JSON(), nullable=True))
    op.execute("UPDATE prds SET promoted_sections = '[]' WHERE promoted_sections IS NULL")


def downgrade() -> None:
    op.drop_column("prds", "promoted_sections")
    op.drop_column("prds", "supersedes_prd_id")
