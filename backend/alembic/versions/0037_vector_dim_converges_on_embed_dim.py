"""vector columns: CONVERGE on EMBED_DIM, not just set it once (AL-248)

Migration 0019 sized the pgvector columns from ``settings.embed_dim`` — but only at
the moment it ran. Alembic never re-runs an applied revision, so changing EMBED_DIM
afterwards silently does nothing: the columns keep their old width and every
embedding write then fails with ``expected N dimensions, not M``.

That is exactly how the hosted instance got stranded. 0019 ran with the default 384,
the deployment later needed 1024 (bge-m3 via the self-hosted gateway), and there was
no path from one to the other — setting EMBED_DIM=1024 alone would have broken every
write rather than resized anything.

This revision closes the gap by CONVERGING instead of setting: read the live column
width, compare it to ``settings.embed_dim``, rebuild only on a mismatch. A matching
width is a no-op, so upgrading a correctly-configured instance costs nothing and
nobody loses vectors they still want.

Rebuilding DROPS existing embeddings (derived data — the source text is untouched).
Re-populate with ``POST /api/memory/backfill``, which re-embeds shards AND code nodes
with the current provider. The migration says so loudly when it drops non-empty data,
because a silent wipe of derived data is how you lose trust in migrations.

Postgres-only: SQLite (tests / zero-infra) stores embeddings in a Text column.

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-01
"""
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.config import settings

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VECTOR_COLS = [
    ("memory_shards", "ix_memory_shards_embedding"),
    ("code_nodes", "ix_code_nodes_embedding"),
]


def _current_dim(bind, table: str) -> int | None:
    """Live width of ``table.embedding``, or None if the column/table isn't there."""
    declared = bind.execute(
        sa.text(
            """
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = :t
              AND a.attname = 'embedding'
              AND a.attnum > 0
              AND NOT a.attisdropped
              AND n.nspname = current_schema()
            """
        ),
        {"t": table},
    ).scalar()
    if not declared:
        return None
    m = re.match(r"vector\((\d+)\)", declared)
    return int(m.group(1)) if m else None


def converge(bind, target: int) -> list[tuple[str, int, int]]:
    """Rebuild every vector column whose width differs from ``target``.

    Returns ``(table, from_dim, to_dim)`` per rebuild — empty when the schema already
    matches, which is the common case and must stay free. Plain SQL rather than
    ``op.*`` so this is callable with any connection, including from a test: a
    from-scratch migration run can never exercise the rebuild branch (0019 already
    sizes from ``embed_dim``), so the interesting path is only reachable directly.
    """
    target = int(target)  # interpolated into DDL below; never let it be anything else
    changed: list[tuple[str, int, int]] = []
    for table, ix in _VECTOR_COLS:
        current = _current_dim(bind, table)
        if current is None or current == target:
            continue  # absent, or already the right width — nothing to do

        populated = (
            bind.execute(
                sa.text(f"SELECT count(*) FROM {table} WHERE embedding IS NOT NULL")  # noqa: S608
            ).scalar()
            or 0
        )
        if populated:
            print(
                f"  [0037] {table}: resizing embedding {current} -> {target}; "
                f"DROPPING {populated} existing vector(s). "
                f"Run POST /api/memory/backfill after deploy to re-embed.",
                flush=True,
            )

        bind.execute(sa.text(f"DROP INDEX IF EXISTS {ix}"))
        bind.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN embedding"))
        bind.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN embedding vector({target})"))
        bind.execute(
            sa.text(f"CREATE INDEX {ix} ON {table} USING hnsw (embedding vector_cosine_ops)")
        )
        changed.append((table, current, target))
    return changed


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    converge(bind, settings.embed_dim)


def downgrade() -> None:
    """No-op. A converging migration has no meaningful inverse: the prior width isn't
    recorded anywhere, and guessing it would drop vectors a second time. Set EMBED_DIM
    back and re-run `upgrade` to converge the other way."""
