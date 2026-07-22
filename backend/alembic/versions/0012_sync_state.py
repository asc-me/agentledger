"""sync_state — per-PRD last-synced snapshot for Drive sync conflict detection

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sync_state",
        sa.Column("prd_id", sa.String(), primary_key=True),
        sa.Column("file_name", sa.String()),
        sa.Column("last_hash", sa.String()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("sync_state")
