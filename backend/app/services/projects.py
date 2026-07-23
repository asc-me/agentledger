"""Project resolution helpers — shared by MCP and public endpoints.

After the seeded ``core`` project went away, no write may assume a fixed project
id. These helpers pick a sensible project so single-project deploys "just work"
while multi-project callers can still be explicit.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project


def default_project_id(db: Session, allowed_ids: list[str] | None = None) -> str | None:
    """The first project by name, or None if the database has no projects yet.

    Pass ``allowed_ids`` (the caller's readable projects) so a single-project deploy
    "just works" without the fallback ever crossing into another tenant's project
    (AL-71). ``None`` means unscoped (legacy / trusted internal callers)."""
    stmt = select(Project).order_by(Project.name)
    if allowed_ids is not None:
        if not allowed_ids:
            return None
        stmt = stmt.where(Project.id.in_(allowed_ids))
    p = db.scalars(stmt).first()
    return p.id if p else None


def resolve_project_id(
    db: Session, project_id: str | None, allowed_ids: list[str] | None = None
) -> str | None:
    """Return ``project_id`` if it names an existing project, else the default.

    A named-but-existing project is returned as-is; authorization is the caller's
    job (``require_readable``/``require_writable``) so a named-but-forbidden id is
    rejected there, not silently swapped. Only the *fallback* is bounded by
    ``allowed_ids`` — the caller's own projects — so an omitted/unknown id never
    resolves to another tenant's first-by-name project (AL-71)."""
    if project_id and db.get(Project, project_id) is not None:
        return project_id
    return default_project_id(db, allowed_ids)
