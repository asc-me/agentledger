"""Run Alembic migrations programmatically at startup (Postgres path)."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def run_migrations() -> None:
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    command.upgrade(cfg, "head")

    # Vector widths track EMBED_DIM, which is CONFIG — it changes independently of schema
    # revisions, so a migration can't own it. Alembic stamps a revision applied and never
    # re-runs it, so migration 0037 converged once (at the then-current EMBED_DIM) and was
    # skipped on every later boot, leaving the schema behind the configured embedder.
    # Runs on every startup instead; a no-op when the widths already agree.
    from app.vector_schema import converge_all

    converge_all()
