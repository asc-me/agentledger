"""org_usage — per-org monthly MCP-call counter for plan quotas (hosted SaaS)

AL-75: the only usage number we persist; project/seat/shard usage is counted on
demand. Inert unless HOSTED_MODE is on.

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "org_usage",
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), primary_key=True),
        sa.Column("period", sa.String(), primary_key=True),  # 'YYYY-MM' (UTC)
        sa.Column("mcp_calls", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("org_usage")
