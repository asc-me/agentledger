"""milestones + mcp_tool_stats

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "milestones",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id")),
        sa.Column("phase", sa.String()),
        sa.Column("title", sa.String()),
        sa.Column("tag", sa.String()),
        sa.Column("done", sa.Boolean()),
        sa.Column("sort_order", sa.Integer()),
    )
    op.create_table(
        "mcp_tool_stats",
        sa.Column("tool", sa.String(), primary_key=True),
        sa.Column("calls", sa.Integer()),
    )


def downgrade() -> None:
    op.drop_table("mcp_tool_stats")
    op.drop_table("milestones")
