"""Migration 0037: the pgvector columns must follow EMBED_DIM, not a one-time snapshot.

0019 sized the columns from `settings.embed_dim` at the moment it ran, and alembic never
re-runs an applied revision — so changing EMBED_DIM afterwards silently left the schema
behind, and every embedding write then failed with `expected N dimensions, not M`. The
hosted instance sat at vector(384) with no path to the 1024 its gateway needed (AL-248).

Postgres-only: SQLite stores embeddings in a Text column and is unaffected.
"""
import re

import pytest
from sqlalchemy import text

from app.config import settings
from app.db import engine

pytestmark = pytest.mark.skipif(
    engine.url.drivername.startswith("sqlite"),
    reason="pgvector columns are Postgres-only",
)

_DECLARED_TYPE = text(
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
)


@pytest.mark.parametrize("table", ["memory_shards", "code_nodes"])
def test_vector_column_matches_configured_embed_dim(client, table):
    """The invariant 0037 exists to hold. `client` runs the lifespan, which migrates."""
    with engine.connect() as conn:
        declared = conn.execute(_DECLARED_TYPE, {"t": table}).scalar()
    assert declared == f"vector({settings.embed_dim})", (
        f"{table}.embedding is {declared} but EMBED_DIM is {settings.embed_dim} — "
        "a mismatch fails every embedding write at runtime"
    )


@pytest.mark.parametrize("table", ["memory_shards", "code_nodes"])
def test_hnsw_index_survives_the_rebuild(client, table):
    """Rebuilding the column drops its index; 0037 must put it back or every vector
    search silently degrades to a sequential scan."""
    with engine.connect() as conn:
        found = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE tablename = :t AND indexname = :ix"),
            {"t": table, "ix": f"ix_{table}_embedding"},
        ).scalar()
    assert found and "hnsw" in found.lower(), f"{table} lost its HNSW index"


def _migration():
    """Load 0037 directly — a from-scratch migration run can never reach its rebuild
    branch, because 0019 already sizes the columns from `embed_dim`."""
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0037_vector_dim_converges_on_embed_dim.py"
    )
    spec = importlib.util.spec_from_file_location("mig0037", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    return mig


def test_current_dim_helper_parses_and_tolerates_missing(client):
    """`_current_dim` drives the skip-vs-rebuild decision — a wrong None would skip a
    stale column, and a wrong value would rebuild a correct one and drop live vectors."""
    mig = _migration()
    with engine.connect() as conn:
        assert mig._current_dim(conn, "memory_shards") == settings.embed_dim
        assert mig._current_dim(conn, "table_that_does_not_exist") is None


def test_converge_resizes_a_stale_column_and_restores_its_index(client):
    """The actual bug: a column left at the old width while EMBED_DIM moved on.

    Simulated by shrinking the column behind the migration's back, exactly as 0019
    would have left it, then converging back."""
    mig = _migration()
    target = settings.embed_dim
    stale = 99  # any width that isn't the configured one

    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ix_memory_shards_embedding"))
        conn.execute(text("ALTER TABLE memory_shards DROP COLUMN embedding"))
        conn.execute(text(f"ALTER TABLE memory_shards ADD COLUMN embedding vector({stale})"))
        assert mig._current_dim(conn, "memory_shards") == stale

        changed = mig.converge(conn, target)

        assert ("memory_shards", stale, target) in changed
        assert mig._current_dim(conn, "memory_shards") == target
        idx = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_memory_shards_embedding'")
        ).scalar()
        assert idx and "hnsw" in idx.lower(), "convergence must restore the HNSW index"


def test_converge_is_a_no_op_when_widths_already_match(client):
    """The common case — every deploy of a correctly-configured instance. It must not
    touch the columns, or a routine upgrade would silently drop everyone's vectors."""
    mig = _migration()
    with engine.begin() as conn:
        assert mig.converge(conn, settings.embed_dim) == []
        assert mig._current_dim(conn, "memory_shards") == settings.embed_dim
        assert mig._current_dim(conn, "code_nodes") == settings.embed_dim


def test_migration_docstring_names_the_backfill_remedy():
    """Rebuilding drops derived vectors. If the migration doesn't say how to recover
    them, an operator finds out by noticing search got worse."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0037_vector_dim_converges_on_embed_dim.py"
    ).read_text()
    assert re.search(r"memory/backfill", src)
