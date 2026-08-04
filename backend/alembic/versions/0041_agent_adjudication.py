"""May an agent operate this project's quality gates? (AL-282 / PRD-14 D2)

PRD-14 separates QUALITY gates ("is this good?" — memory publish, PRD approval) from
AUTHORITY gates ("are you allowed?" — credential minting, retag, org/tenant). An agent
may hold a quality gate when the project's owner says so; it never holds an authority
gate in any configuration.

Defaults to false, including for every existing project: turning it on moves the AL-49
human boundary, which is the owner's decision and not something a migration should make
for them.

Revision ID: 0041
Revises: 0040
"""
from alembic import op
import sqlalchemy as sa

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("agent_adjudication", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )


def downgrade() -> None:
    # Shards adjudicated by an agent keep `scoring_source = 'agent'`, so the provenance
    # survives a downgrade even though the toggle doesn't — a human can still find
    # exactly what was published without them.
    op.drop_column("projects", "agent_adjudication")
