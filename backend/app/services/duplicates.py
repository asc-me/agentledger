"""Auto-duplicate detection (AL-21): embed a submission and surface similar
existing items/requests above a threshold before it enters triage.

Embeds candidates on the fly via the configured Embedder — provider-agnostic and
fine for the current corpus size. (For large corpora with a real provider, persist
item/request embeddings; the interface here stays the same.)
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.providers import cosine_similarity, get_embedder
from app.models import Item, Request

DEFAULT_THRESHOLD = 0.55


def find_duplicates(
    db: Session,
    text: str,
    *,
    project_id: str = "core",
    threshold: float = DEFAULT_THRESHOLD,
    top_k: int = 5,
    exclude_request_id: str | None = None,
) -> list[dict]:
    embedder = get_embedder()
    qv = embedder.embed(text)

    scored: list[dict] = []
    for req in db.scalars(select(Request).where(Request.project_id == project_id)).all():
        if req.id == exclude_request_id:
            continue
        score = cosine_similarity(qv, embedder.embed(req.title))
        scored.append({"kind": "request", "id": req.id, "title": req.title, "type": req.type, "score": score})
    for item in db.scalars(select(Item).where(Item.project_id == project_id)).all():
        score = cosine_similarity(qv, embedder.embed(f"{item.title} {item.description}"))
        scored.append({"kind": "item", "id": item.id, "title": item.title, "status": item.status, "score": score})

    hits = [s for s in scored if s["score"] >= threshold]
    hits.sort(key=lambda s: s["score"], reverse=True)
    for h in hits:
        h["score"] = round(h["score"], 4)
    return hits[:top_k]
