"""memory auto-triage — toggles + auto-action provenance

AL-227: let the AL-151 candidate scorer ACT on agent-written memory instead of only
advising. Three project toggles gate it — `memory_auto_reject` (on by default, drops
near-dups / resembles-rejected candidates), `memory_auto_accept` (off, publishes
high-confidence corroborated lessons), `memory_llm_judge` (off, reserved for the LLM
scorer). Two shard columns record an auto-action for the "recent auto-actions" lane:
`scoring_source` ("" = human-only) and `auto_confidence`.

Revision ID: 0036
Revises: 0035
Create Date: 2026-07-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("memory_auto_reject", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "projects",
        sa.Column("memory_auto_accept", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "projects",
        sa.Column("memory_llm_judge", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "memory_shards",
        sa.Column("scoring_source", sa.String(), nullable=False, server_default=""),
    )
    op.add_column(
        "memory_shards",
        sa.Column("auto_confidence", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("memory_shards", "auto_confidence")
    op.drop_column("memory_shards", "scoring_source")
    op.drop_column("projects", "memory_llm_judge")
    op.drop_column("projects", "memory_auto_accept")
    op.drop_column("projects", "memory_auto_reject")
