"""Project resolution helpers — shared by MCP and public endpoints.

After the seeded ``core`` project went away, no write may assume a fixed project
id. These helpers pick a sensible project so single-project deploys "just work"
while multi-project callers can still be explicit.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import tagging
from app.models import LegacyEntityKey, Project, ProjectTagHistory


def tag_available(db: Session, tag: str) -> tuple[bool, str]:
    """Is ``tag`` free on THIS deployment? Returns ``(available, reason)``.

    Three instance-local conditions make a tag unavailable — no reserved-word list ships
    in the product, so a fresh self-host starts with the whole namespace open, including
    ``AL`` and ``PRD``:

    1. **currently held** by a project
    2. **previously held** — in tag history. Reuse would make a key rendered under the
       old tag ambiguous the moment the new holder had an entity with the same number.
    3. **present as a pre-tag prefix** in the legacy table. This is the one that is easy
       to miss: ``PRD`` was never a project *tag*, so history cannot express it, but
       ``PRD-12`` is a legal rendering of item 12 in a project tagged ``PRD``. Letting a
       project claim it would collide with a legacy id that must resolve forever.

    ``R`` excludes itself by failing the two-character minimum.
    """
    try:
        tag = tagging.validate(tag)
    except ValueError as e:
        return False, str(e)

    if db.scalar(select(Project).where(Project.tag == tag)) is not None:
        return False, "already in use by another project"
    if db.get(ProjectTagHistory, tag) is not None:
        return False, "previously used on this deployment; tags are never reused"
    if db.scalar(select(LegacyEntityKey).where(LegacyEntityKey.old_key.like(f"{tag}-%"))):
        return False, "reserved by ids issued before project tags existed"
    return True, ""


def unique_tag(db: Session, name: str) -> str:
    """A free tag derived from ``name``, mirroring the ``_unique_slug`` convention.

    Derivation must always succeed rather than reject: every project needs a tag, and an
    agent bootstrapping one shouldn't fail over a missing four-character string. The
    result is visible and changeable immediately.
    """
    for candidate in tagging.variants(tagging.derive(name)):
        if tag_available(db, candidate)[0]:
            return candidate
    raise ValueError(f"could not derive a free tag for {name!r}")


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
