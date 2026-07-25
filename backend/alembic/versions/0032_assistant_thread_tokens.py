"""assistant_threads token counters — per-conversation metering

AL-179: accumulate the assistant's token usage per thread for cost visibility.

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assistant_threads", sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("assistant_threads", sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("assistant_threads", "output_tokens")
    op.drop_column("assistant_threads", "input_tokens")
