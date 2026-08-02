"""Resolve a human- or agent-supplied key to the stored id it means (PRD-13 / AL-257).

The inverse of ``tagging.render``. A key like ``GRPH-12`` is a *rendering* of
``(project tag, kind, number)`` and is not stored anywhere; the stored id is frozen at
issue time. So every path that accepts an id from outside has to translate, and it has
to keep translating keys that were rendered under a tag the project no longer holds —
from git history, merged PR titles, frozen PRD snapshots, and agent memory.

**Reads and writes both.** ``claim_next``, ``heartbeat``, ``update_item``, and
``release_item`` resolve through here exactly like ``get_item_details`` does. An agent
that claimed a lease on ``AL-12`` keeps working after its project is retagged only
because the write path translates too — and a missed call site fails *only* on a
renamed project, which no fresh-instance test would ever notice.

Resolution order, first hit wins:

1. **Current form** — parse the grammar, find the project holding that tag, look the
   entity up by number. This is what a key means *today*, so it outranks history.
2. **Tag history** — a tag the project used to hold. One row per rename.
3. **Legacy table** — an id issued before tags existed. ``R-`` and ``PRD-`` were
   entity-kind markers rather than project tags, so tag history cannot express them.
4. **Identity** — the stored id itself. Last, deliberately: once tags move, a stale
   stored id and a live rendered key can collide on the same string, and the live
   rendering has to win. This rung exists so internal callers and anything the first
   three cannot express still resolve.

Every rung is filtered by ``kind``, so asking for a PRD can never hand back an item
that happens to share a number.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import tagging
from app.models import Item, LegacyEntityKey, Prd, Project, ProjectTagHistory, Request

# kind -> model. The keys match tagging.KIND_LETTER so the grammar and the lookup
# can never disagree about what kinds exist.
MODELS = {"item": Item, "request": Request, "prd": Prd}


def resolve(db: Session, key: str, kind: str) -> str | None:
    """The stored id for ``key``, or None when it names nothing of that kind.

    None is the caller's 404 — it means "no such entity", not "malformed input".
    """
    model = MODELS[kind]
    key = (key or "").strip()
    if not key:
        return None

    parsed = tagging.parse(key)
    if parsed and parsed[1] == kind:
        tag, _kind, number = parsed

        project = db.scalar(select(Project).where(Project.tag == tag))
        if project is not None:
            found = db.scalar(
                select(model).where(model.project_id == project.id, model.number == number)
            )
            if found is not None:
                return found.id

        # A tag the project used to hold. Reuse is forbidden per deployment (AL-258),
        # which is what keeps this lookup unambiguous.
        history = db.get(ProjectTagHistory, tag)
        if history is not None:
            found = db.scalar(
                select(model).where(
                    model.project_id == history.project_id, model.number == number
                )
            )
            if found is not None:
                return found.id

    legacy = db.get(LegacyEntityKey, key)
    if legacy is not None and legacy.entity_type == kind:
        return legacy.entity_id

    return key if db.get(model, key) is not None else None


def resolve_item(db: Session, key: str) -> str | None:
    return resolve(db, key, "item")


def resolve_request(db: Session, key: str) -> str | None:
    return resolve(db, key, "request")


def resolve_prd(db: Session, key: str) -> str | None:
    return resolve(db, key, "prd")
