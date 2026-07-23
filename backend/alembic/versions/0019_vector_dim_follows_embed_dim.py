"""vector columns: follow EMBED_DIM instead of a hardcoded 384 (AL-64)

Migrations 0001/0013 pinned the pgvector columns at 384, so an instance
configured for a different embedder (e.g. Ollama bge-m3 → 1024, EMBED_DIM=1024)
fails every embedding write: `expected 384 dimensions, not N`. This recreates
both vector columns (+ their HNSW indexes) at `settings.embed_dim`, so the schema
tracks the configured embedder.

Recreating the column drops existing embeddings (derived data — the text is
untouched). Re-populate with `POST /api/memory/backfill` after deploy, which
re-embeds shards AND code nodes with the current provider.

SQLite (tests / zero-infra) uses a Text column and is unaffected.

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

from app.config import settings

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VECTOR_COLS = [
    ("memory_shards", "ix_memory_shards_embedding"),
    ("code_nodes", "ix_code_nodes_embedding"),
]


def _rebuild(dim: int) -> None:
    for table, ix in _VECTOR_COLS:
        op.execute(f"DROP INDEX IF EXISTS {ix}")
        op.drop_column(table, "embedding")
        op.add_column(table, sa.Column("embedding", pgvector.sqlalchemy.Vector(dim), nullable=True))
        op.execute(f"CREATE INDEX {ix} ON {table} USING hnsw (embedding vector_cosine_ops)")


def upgrade() -> None:
    _rebuild(settings.embed_dim)


def downgrade() -> None:
    _rebuild(384)  # the pre-0019 hardcoded dimension
