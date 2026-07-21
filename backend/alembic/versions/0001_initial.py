"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBED_DIM = 384
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("handle", sa.String(), nullable=False, unique=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("avatar", sa.String()),
        sa.Column("initials", sa.String()),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("created_at", TS),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("accent", sa.String()),
        sa.Column("visibility", sa.String()),
        sa.Column("description", sa.Text()),
        sa.Column("share_global_memory", sa.Boolean()),
        sa.Column("auto_extract", sa.Boolean()),
        sa.Column("mcp_enabled", sa.Boolean()),
        sa.Column("embed_model", sa.String()),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id")),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id")),
        sa.Column("role", sa.String()),
        sa.Column("access", sa.String()),
    )
    op.create_table(
        "items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id")),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String()),
        sa.Column("tags", sa.JSON()),
        sa.Column("effort", sa.Integer()),
        sa.Column("sort_order", sa.Integer()),
        sa.Column("blocker", sa.String()),
        sa.Column("date", sa.String()),
        sa.Column("reporter", sa.JSON()),
        sa.Column("pr", sa.JSON(), nullable=True),
        sa.Column("created_at", TS),
        sa.Column("updated_at", TS),
    )
    op.create_table(
        "memory_shards",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("item_id", sa.String(), sa.ForeignKey("items.id"), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("scope", sa.String()),
        sa.Column("source", sa.String()),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBED_DIM), nullable=True),
        sa.Column("fresh", sa.Boolean()),
        sa.Column("created_at", TS),
    )
    op.create_table(
        "requests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id")),
        sa.Column("type", sa.String()),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("by", sa.String()),
        sa.Column("votes", sa.Integer()),
        sa.Column("status", sa.String()),
        sa.Column("linked_to", sa.String(), sa.ForeignKey("items.id"), nullable=True),
        sa.Column("ago", sa.String()),
        sa.Column("created_at", TS),
    )
    op.create_table(
        "links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id")),
        sa.Column("a", sa.String()),
        sa.Column("b", sa.String()),
        sa.Column("type", sa.String()),
        sa.Column("confidence", sa.Float()),
        sa.Column("reason", sa.String()),
        sa.Column("created_at", TS),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id")),
        sa.Column("name", sa.String()),
        sa.Column("prefix", sa.String()),
        sa.Column("hashed_key", sa.String()),
        sa.Column("scopes", sa.JSON()),
        sa.Column("last_used", TS, nullable=True),
        sa.Column("created_at", TS),
    )

    # Approximate cosine index for semantic memory search.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memory_shards_embedding "
        "ON memory_shards USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    for t in ("api_keys", "links", "requests", "memory_shards", "items", "memberships", "projects", "users"):
        op.drop_table(t)
