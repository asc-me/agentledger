"""code_sync_state — per-project last-pushed code-graph manifest

AL-139: the diff base for an incremental, resumable local→cloud code-graph push.

Revision ID: 0033
Revises: 0032
Create Date: 2026-07-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "code_sync_state",
        sa.Column("project_id", sa.String(), primary_key=True),
        sa.Column("manifest", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("code_sync_state")
