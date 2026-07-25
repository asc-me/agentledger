"""assistant_threads + assistant_messages — in-app AI assistant conversations

AL-174: persist a conversation scoped to an item or PRD (thread + ordered messages,
carrying the tool-calling record and staged proposed-actions).

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assistant_threads",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_assistant_threads_project_id", "assistant_threads", ["project_id"])
    op.create_index("ix_assistant_threads_entity_id", "assistant_threads", ["entity_id"])

    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("thread_id", sa.String(), sa.ForeignKey("assistant_threads.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("tool_calls", sa.JSON(), nullable=True),
        sa.Column("tool_results", sa.JSON(), nullable=True),
        sa.Column("proposed_actions", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_assistant_messages_thread_id", "assistant_messages", ["thread_id"])


def downgrade() -> None:
    op.drop_index("ix_assistant_messages_thread_id", "assistant_messages")
    op.drop_table("assistant_messages")
    op.drop_index("ix_assistant_threads_entity_id", "assistant_threads")
    op.drop_index("ix_assistant_threads_project_id", "assistant_threads")
    op.drop_table("assistant_threads")
