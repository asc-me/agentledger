"""code graph — agent-described code structure (code_nodes + code_edges)

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-22
"""
from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBED_DIM = 384
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "code_nodes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id")),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("kind", sa.String()),
        sa.Column("name", sa.String()),
        sa.Column("lang", sa.String()),
        sa.Column("summary", sa.Text()),
        sa.Column("content_hash", sa.String()),
        sa.Column("fresh", sa.Boolean()),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBED_DIM), nullable=True),
        sa.Column("created_at", TS),
        sa.Column("updated_at", TS),
        sa.UniqueConstraint("project_id", "path", name="uq_code_node_path"),
    )
    op.create_table(
        "code_edges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id")),
        sa.Column("src", sa.String(), nullable=False),
        sa.Column("dst", sa.String(), nullable=False),
        sa.Column("type", sa.String()),
        sa.Column("created_at", TS),
        sa.UniqueConstraint("project_id", "src", "dst", "type", name="uq_code_edge"),
    )

    # Approximate cosine index for semantic code search (mirrors memory_shards).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_code_nodes_embedding "
        "ON code_nodes USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.drop_table("code_edges")
    op.drop_table("code_nodes")
