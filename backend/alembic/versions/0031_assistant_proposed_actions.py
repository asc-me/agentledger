"""assistant_proposed_actions — propose-then-approve for assistant writes

AL-177: a write the assistant proposed but has not executed. The human applies (executes
+ audits, capturing prior_value for reversibility) or rejects.

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assistant_proposed_actions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("thread_id", sa.String(), sa.ForeignKey("assistant_threads.id"), nullable=False),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("tool", sa.String(), nullable=False),
        sa.Column("args", sa.JSON(), nullable=True),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("prior_value", sa.JSON(), nullable=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_assistant_proposed_actions_thread_id", "assistant_proposed_actions", ["thread_id"])
    op.create_index("ix_assistant_proposed_actions_status", "assistant_proposed_actions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_assistant_proposed_actions_status", "assistant_proposed_actions")
    op.drop_index("ix_assistant_proposed_actions_thread_id", "assistant_proposed_actions")
    op.drop_table("assistant_proposed_actions")
