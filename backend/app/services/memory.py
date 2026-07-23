"""Memory shard service — semantic search over pgvector with a SQLite fallback."""
from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.embeddings import cosine_similarity, get_embedder
from app.models import MemoryShard


def list_shards(
    db: Session, project_id: str | None = None, status: str | None = None
) -> list[MemoryShard]:
    stmt = select(MemoryShard)
    if project_id:
        stmt = stmt.where(
            (MemoryShard.project_id == project_id) | (MemoryShard.project_id.is_(None))
        )
    if status is not None:
        stmt = stmt.where(MemoryShard.status == status)
    stmt = stmt.order_by(MemoryShard.created_at.desc())
    return list(db.scalars(stmt).all())


def add_memory(
    db: Session,
    *,
    text_body: str,
    scope: str = "global",
    source: str = "",
    item_id: str | None = None,
    project_id: str | None = "core",
    fresh: bool = True,
    status: str = "published",
    origin: str = "",
) -> MemoryShard:
    embedder = get_embedder()
    shard = MemoryShard(
        id="m_" + uuid.uuid4().hex[:10],
        text=text_body,
        scope=scope,
        source=source or ("global" if scope == "global" else (f"from {item_id}" if item_id else "")),
        item_id=item_id,
        project_id=project_id,
        embedding=embedder.embed(text_body),
        fresh=fresh,
        status=status,
        origin=origin,
    )
    db.add(shard)
    db.commit()
    db.refresh(shard)
    return shard


def set_status(db: Session, shard_id: str, status: str) -> MemoryShard | None:
    """Promote (→published) or reject (→rejected) a candidate shard (AL-49)."""
    if status not in ("candidate", "published", "rejected"):
        raise ValueError(f"invalid shard status: {status}")
    shard = db.get(MemoryShard, shard_id)
    if shard is None:
        return None
    shard.status = status
    db.commit()
    db.refresh(shard)
    return shard


def update_shard(db: Session, shard_id: str, *, text_body: str) -> MemoryShard | None:
    """Edit a shard's text and RE-EMBED it (fixes stale-embedding-after-edit, R-27)."""
    shard = db.get(MemoryShard, shard_id)
    if shard is None:
        return None
    shard.text = text_body
    shard.embedding = get_embedder().embed(text_body)
    db.commit()
    db.refresh(shard)
    return shard


def backfill_embeddings(db: Session) -> int:
    """Re-embed every shard with the current provider. Run after switching providers."""
    embedder = get_embedder()
    shards = list(db.scalars(select(MemoryShard)).all())
    for s in shards:
        s.embedding = embedder.embed(s.text)
    db.commit()
    return len(shards)


def export_shards(db: Session, project_id: str | None = None) -> list[dict]:
    out = []
    for s in list_shards(db, project_id=project_id):
        out.append({"text": s.text, "scope": s.scope, "source": s.source, "item_id": s.item_id})
    return out


def import_shards(db: Session, rows: list[dict], project_id: str = "core") -> int:
    for row in rows:
        add_memory(
            db,
            text_body=row["text"],
            scope=row.get("scope", "global"),
            source=row.get("source", ""),
            item_id=row.get("item_id"),
            project_id=project_id,
        )
    return len(rows)


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def search_memory(
    db: Session, query: str, top_k: int = 5, project_id: str | None = None,
    include_candidates: bool = False,
) -> list[tuple[MemoryShard, float]]:
    """Return (shard, similarity) pairs ranked by cosine similarity, best first.

    The trusted-publication boundary (AL-49): only `published` shards surface by
    default. `include_candidates` also returns unreviewed agent self-reports;
    `rejected` shards never surface."""
    qvec = get_embedder().embed(query)
    allowed = ("published", "candidate") if include_candidates else ("published",)

    if not settings.is_sqlite:
        # pgvector: cosine distance operator `<=>`; similarity = 1 - distance.
        params: dict = {"qv": _vector_literal(qvec), "k": top_k}
        project_clause = ""
        if project_id is not None:
            project_clause = "AND (project_id = :pid OR project_id IS NULL)"
            params["pid"] = project_id
        # Bind the allowed statuses as an IN-list (never surface `rejected`).
        status_names = [f":st{i}" for i in range(len(allowed))]
        for i, st in enumerate(allowed):
            params[f"st{i}"] = st
        sql = text(
            f"""
            SELECT id, (embedding <=> (:qv)::vector) AS distance
            FROM memory_shards
            WHERE embedding IS NOT NULL
              AND status IN ({", ".join(status_names)})
              {project_clause}
            ORDER BY distance ASC
            LIMIT :k
            """
        )
        rows = db.execute(sql, params).all()
        out: list[tuple[MemoryShard, float]] = []
        for row in rows:
            shard = db.get(MemoryShard, row.id)
            if shard is not None:
                out.append((shard, 1.0 - float(row.distance)))
        return out

    # SQLite fallback: cosine in Python over the (small) shard set.
    shards = [s for s in list_shards(db, project_id=project_id) if s.status in allowed]
    scored = [
        (s, cosine_similarity(qvec, s.embedding)) for s in shards if s.embedding is not None
    ]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:top_k]
