"""platform_config.sync_graph — per-project "never sync the graph" privacy flag

AL-137 (D8): opt-out of pushing a project's code graph to the linked cloud tenant.

Revision ID: 0034
Revises: 0033
Create Date: 2026-07-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "platform_config",
        sa.Column("sync_graph", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("platform_config", "sync_graph")
