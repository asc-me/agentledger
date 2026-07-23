"""events — append-only audit ledger (who did what, when)

AL-43 / review finding F1b: mutations recorded no actor. This table captures one
row per accepted mutation, written at the MCP + REST boundaries.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_type", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False, server_default=""),
        sa.Column("actor_label", sa.String(), nullable=False, server_default=""),
        sa.Column("surface", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False, server_default=""),
        sa.Column("target_id", sa.String(), nullable=False, server_default=""),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
    )
    op.create_index("ix_events_ts", "events", ["ts"])
    op.create_index("ix_events_project_id", "events", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_events_project_id", table_name="events")
    op.drop_index("ix_events_ts", table_name="events")
    op.drop_table("events")
