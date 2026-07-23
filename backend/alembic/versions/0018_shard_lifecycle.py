"""memory_shards: candidate → published lifecycle + provenance

AL-49: agent self-reports are telemetry, not truth — they enter as `candidate`
and only reach the default retrieval path once a human publishes them. Existing
rows default to `published` so nothing already trusted disappears from search.

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "memory_shards",
        sa.Column("status", sa.String(), nullable=False, server_default="published"),
    )
    op.add_column(
        "memory_shards",
        sa.Column("origin", sa.String(), nullable=False, server_default=""),
    )
    op.create_index("ix_memory_shards_status", "memory_shards", ["status"])


def downgrade() -> None:
    op.drop_index("ix_memory_shards_status", table_name="memory_shards")
    op.drop_column("memory_shards", "origin")
    op.drop_column("memory_shards", "status")
