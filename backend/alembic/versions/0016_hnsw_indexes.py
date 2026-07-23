"""vector indexes: ivfflat → HNSW — fix silent low recall on small tables

ivfflat trains k-means centroids from whatever rows exist at CREATE INDEX time.
Migrations 0001/0013 built these indexes on empty tables, so pgvector itself
warns "ivfflat index created with little data — This will cause low recall":
an index scan for `ORDER BY embedding <=> ... LIMIT k` probes 1 of 100
degenerate lists and silently drops matching rows. HNSW needs no training step
and has correct recall from the first row, at our scale with negligible cost.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-22
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memory_shards_embedding")
    op.execute(
        "CREATE INDEX ix_memory_shards_embedding "
        "ON memory_shards USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("DROP INDEX IF EXISTS ix_code_nodes_embedding")
    op.execute(
        "CREATE INDEX ix_code_nodes_embedding "
        "ON code_nodes USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memory_shards_embedding")
    op.execute(
        "CREATE INDEX ix_memory_shards_embedding "
        "ON memory_shards USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute("DROP INDEX IF EXISTS ix_code_nodes_embedding")
    op.execute(
        "CREATE INDEX ix_code_nodes_embedding "
        "ON code_nodes USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
