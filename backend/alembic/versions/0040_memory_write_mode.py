"""Memory write mode replaces the memory_auto_accept boolean (AL-280 / PRD-14 D1).

`memory_auto_accept` promised more than it delivered: `_score_shard` only ever suggests
`accept` on `support >= 2` or corroboration against an already-published shard, so a
first-of-its-kind fact always scored `review` and stayed a candidate no matter what the
toggle said. An agent could not read back what it had just written.

`memory_write_mode` names the three real behaviors, and adds the one that was missing:

    review  -> a novel write stays a candidate (the AL-49 boundary; today's default)
    auto    -> publishes only when strongly corroborated (what auto_accept meant)
    trusted -> publishes on write

The mapping is exact, so no deployed project changes behavior: `auto_accept=true` was
asking for corroborated auto-publish, which is `auto`; `false` is `review`. Nothing maps
to `trusted` — it is opt-in, because it is the one that moves the human boundary.

`memory_auto_reject` is deliberately NOT folded in. It is orthogonal and vetoes in every
mode: dedup is worth keeping without a human, and `trusted` without it would fill the
store with restatements of one fact.

Revision ID: 0040
Revises: 0039
"""
from alembic import op
import sqlalchemy as sa

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("memory_write_mode", sa.String(), nullable=False, server_default="review"),
    )
    # Carry each project's intent across before the old column goes away.
    op.execute("UPDATE projects SET memory_write_mode = 'auto' WHERE memory_auto_accept = true")
    op.drop_column("projects", "memory_auto_accept")


def downgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("memory_auto_accept", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # `trusted` has no boolean equivalent. It collapses to true (auto-publish on), which
    # is the closer of the two: a downgraded instance keeps publishing without a human
    # for corroborated shards rather than silently reinstating the review gate.
    op.execute(
        "UPDATE projects SET memory_auto_accept = true "
        "WHERE memory_write_mode IN ('auto', 'trusted')"
    )
    op.drop_column("projects", "memory_write_mode")
