"""Project resolution helpers — shared by MCP and public endpoints.

After the seeded ``core`` project went away, no write may assume a fixed project
id. These helpers pick a sensible project so single-project deploys "just work"
while multi-project callers can still be explicit.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project


def default_project_id(db: Session) -> str | None:
    """The first project by name, or None if the database has no projects yet."""
    p = db.scalars(select(Project).order_by(Project.name)).first()
    return p.id if p else None


def resolve_project_id(db: Session, project_id: str | None) -> str | None:
    """Return ``project_id`` if it names an existing project, else the default project."""
    if project_id and db.get(Project, project_id) is not None:
        return project_id
    return default_project_id(db)
