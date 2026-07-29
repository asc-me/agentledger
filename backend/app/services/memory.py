"""Memory shard service — semantic search over pgvector with a SQLite fallback."""
from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.embeddings import cosine_similarity, get_embedder, safe_embed
from app.models import MemoryShard, Project
from app.services import events as events_svc


def _includes_global(db: Session, project_id: str) -> bool:
    """Whether project-less ("global", project_id IS NULL) shards should surface in
    THIS project's memory. Honors the project's `share_global_memory` opt-out
    (AL-71) — previously ignored, so global shards bled into every project. In
    hosted mode global shards can't be created at all, so this stays False and no
    tenant's memory ever crosses into another's."""
    if settings.hosted_mode:
        return False
    project = db.get(Project, project_id)
    return bool(project and project.share_global_memory)


def list_shards(
    db: Session, project_id: str | None = None, status: str | None = None
) -> list[MemoryShard]:
    stmt = select(MemoryShard)
    if project_id:
        if _includes_global(db, project_id):
            stmt = stmt.where(
                (MemoryShard.project_id == project_id) | (MemoryShard.project_id.is_(None))
            )
        else:
            stmt = stmt.where(MemoryShard.project_id == project_id)
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
    auto_triage: bool = True,
) -> MemoryShard:
    shard = MemoryShard(
        id="m_" + uuid.uuid4().hex[:10],
        text=text_body,
        scope=scope,
        source=source or ("global" if scope == "global" else (f"from {item_id}" if item_id else "")),
        item_id=item_id,
        project_id=project_id,
        # Never lose the write to a down embedder — backfill fills a NULL vector later.
        embedding=safe_embed(text_body),
        fresh=fresh,
        status=status,
        origin=origin,
    )
    db.add(shard)
    db.commit()
    db.refresh(shard)
    # Agent candidates are triaged on write (AL-227): the scorer may auto-reject or
    # auto-publish per the project's toggles, giving the agent instant feedback in
    # the same call. Human/published writes skip it (only candidates are triaged).
    if auto_triage and shard.status == "candidate":
        shard = triage_candidate(db, shard)
    return shard


def cluster_candidates(
    db: Session, *, project_id: str | None = None, threshold: float = 0.88, min_size: int = 2
) -> list[list[MemoryShard]]:
    """Group candidate shards by embedding similarity — recurring agent lessons
    worth promoting together (AL-50). When the same correction shows up N times,
    it points at an underlying principle that deserves a durable owner (the
    feedback thesis). Greedy single-pass; returns clusters of size >= min_size,
    largest first. Small by construction — it runs over the review queue only."""
    cands = [
        s for s in list_shards(db, project_id=project_id, status="candidate")
        if s.embedding is not None
    ]
    vecs = {s.id: list(s.embedding) for s in cands}  # coerce pgvector arrays → lists
    used: set[str] = set()
    clusters: list[list[MemoryShard]] = []
    for i, a in enumerate(cands):
        if a.id in used:
            continue
        group = [a]
        used.add(a.id)
        for b in cands[i + 1:]:
            if b.id in used:
                continue
            if cosine_similarity(vecs[a.id], vecs[b.id]) >= threshold:
                group.append(b)
                used.add(b.id)
        if len(group) >= min_size:
            clusters.append(group)
    clusters.sort(key=len, reverse=True)
    return clusters


# --- Candidate scoring (AL-151) -------------------------------------------------
# Similarity + heuristics over embeddings we already store — no LLM, works offline.
_SIM_STRONG = 0.88     # corroborated by / clusters with trusted memory (matches cluster threshold)
_SIM_DUP = 0.95        # near-identical → duplicate of an existing published shard
_SIM_REJECTED = 0.85   # resembles something a human already rejected
# Auto-triage (AL-227): auto-publish is reserved for the strongest corroboration —
# a higher bar than the advisory "accept" so novel recurrence alone won't publish.
_AUTO_ACCEPT_MIN = 0.9


def _best_match(vec: list[float], pool: list[tuple[MemoryShard, list[float]]]) -> tuple[MemoryShard | None, float]:
    """The most-similar shard in `pool` and its cosine score (0.0 if the pool is empty)."""
    best, score = None, 0.0
    for shard, svec in pool:
        sim = cosine_similarity(vec, svec)
        if sim > score:
            best, score = shard, sim
    return best, score


def _score_shard(
    cv: list[float],
    published: list[tuple[MemoryShard, list[float]]],
    rejected: list[tuple[MemoryShard, list[float]]],
    support: int,
    human_derived: bool,
) -> tuple[str, float, list[str], str | None]:
    """Score one candidate embedding into (suggestion, confidence, reasons, duplicate_of).

    The single source of truth for the accept/reject/review heuristic — shared by the
    advisory review queue (`score_candidates`) and synchronous auto-triage
    (`triage_candidate`) so both judge a shard identically. Vetoes (rejection
    resemblance, duplication) win over accept signals."""
    best_pub, corr = _best_match(cv, published)
    _, rej = _best_match(cv, rejected)
    reasons: list[str] = []
    duplicate_of: str | None = None

    if rej >= _SIM_REJECTED:
        suggestion, confidence = "reject", rej
        reasons.append(f"resembles a previously rejected shard ({rej:.0%})")
    elif corr >= _SIM_DUP and best_pub is not None:
        suggestion, confidence = "reject", corr
        duplicate_of = best_pub.id
        reasons.append(f"near-duplicate of published {best_pub.id} ({corr:.0%}) — merge candidate")
    elif support >= 2 or corr >= _SIM_STRONG:
        suggestion = "accept"
        confidence = min(1.0, max(corr, 0.6 + 0.1 * support) + (0.1 if human_derived else 0.0))
        if support >= 2:
            reasons.append(f"recurs across {support} candidates")
        if corr >= _SIM_STRONG and best_pub is not None:
            reasons.append(f"corroborated by trusted {best_pub.id} ({corr:.0%})")
        if human_derived:
            reasons.append("from a human-reviewed decision")
    else:
        suggestion, confidence = "review", 0.3
        reasons.append("novel — no strong signal either way")

    return suggestion, round(confidence, 3), reasons, duplicate_of


def score_candidates(db: Session, *, project_id: str | None = None) -> list[dict]:
    """Advisory accept/reject suggestions for the review queue (AL-151).

    For each candidate, compare its embedding against the trusted (`published`) and
    vetoed (`rejected`) pools and its own recurrence (clusters), then emit a suggestion
    (`accept` | `reject` | `review`), a confidence, and human-readable reasons. Never
    mutates and never auto-publishes — the AL-49 human boundary holds. Sorted most
    actionable first (highest confidence), so obvious accepts/dupes rise to the top.

    Similarity-only, so it degrades to noise (not an error) when embeddings are the
    offline stub — it needs no chat provider."""
    cands = [s for s in list_shards(db, project_id=project_id, status="candidate") if s.embedding is not None]
    published = [(s, list(s.embedding)) for s in list_shards(db, project_id=project_id, status="published") if s.embedding is not None]
    rejected = [(s, list(s.embedding)) for s in list_shards(db, project_id=project_id, status="rejected") if s.embedding is not None]

    # Recurrence: how many candidates each one clusters with (reuse AL-50 clustering).
    cluster_size: dict[str, int] = {}
    for group in cluster_candidates(db, project_id=project_id):
        for s in group:
            cluster_size[s.id] = len(group)

    out: list[dict] = []
    for c in cands:
        support = cluster_size.get(c.id, 1)
        human_derived = c.origin.startswith("user:") or "grill" in c.origin
        suggestion, confidence, reasons, duplicate_of = _score_shard(
            list(c.embedding), published, rejected, support, human_derived
        )
        out.append({
            "shard": c,
            "suggestion": suggestion,
            "confidence": confidence,
            "reasons": reasons,
            "duplicate_of": duplicate_of,
        })

    out.sort(key=lambda r: r["confidence"], reverse=True)
    return out


def _triage_prefs(db: Session, project_id: str | None) -> tuple[bool, bool]:
    """(auto_reject, auto_accept) for a project (AL-227). Project-less ("global")
    shards, or an unknown project, fall back to the platform defaults: reject on,
    accept off."""
    if project_id is None:
        return True, False
    project = db.get(Project, project_id)
    if project is None:
        return True, False
    return bool(project.memory_auto_reject), bool(project.memory_auto_accept)


def triage_candidate(db: Session, shard: MemoryShard) -> MemoryShard:
    """Synchronously score a freshly-written candidate and act on it if the project
    opts in (AL-227): auto-reject near-dups / resembles-rejected, or auto-publish a
    high-confidence corroborated lesson (>= `_AUTO_ACCEPT_MIN`). Records the score on
    the shard plus a system audit event, so every auto-action shows in the "recent
    auto-actions" lane and can be undone.

    A no-op returning the shard unchanged when it isn't a candidate, has no embedding,
    or the relevant toggle is off — so the AL-49 human boundary holds by default for
    anything novel."""
    if shard.status != "candidate" or shard.embedding is None:
        return shard
    auto_reject, auto_accept = _triage_prefs(db, shard.project_id)
    if not (auto_reject or auto_accept):
        return shard

    published = [(s, list(s.embedding)) for s in list_shards(db, project_id=shard.project_id, status="published") if s.embedding is not None]
    rejected = [(s, list(s.embedding)) for s in list_shards(db, project_id=shard.project_id, status="rejected") if s.embedding is not None]
    # Recurrence: the size of the candidate cluster this shard belongs to (AL-50).
    support = 1
    for group in cluster_candidates(db, project_id=shard.project_id):
        if any(s.id == shard.id for s in group):
            support = len(group)
            break
    human_derived = shard.origin.startswith("user:") or "grill" in shard.origin
    suggestion, confidence, reasons, duplicate_of = _score_shard(
        list(shard.embedding), published, rejected, support, human_derived
    )

    if suggestion == "reject" and auto_reject:
        action, new_status = "auto_reject_shard", "rejected"
    elif suggestion == "accept" and auto_accept and confidence >= _AUTO_ACCEPT_MIN:
        action, new_status = "auto_publish_shard", "published"
    else:
        return shard  # left as a candidate for human review

    shard.status = new_status
    shard.scoring_source = "similarity"
    shard.auto_confidence = confidence
    db.commit()
    db.refresh(shard)
    events_svc.record(
        db, actor_type="system", actor_label="memory-auto-triage", surface="system",
        action=action, target_type="shard", target_id=shard.id, project_id=shard.project_id,
        meta={"confidence": confidence, "source": "similarity", "reasons": reasons,
              "duplicate_of": duplicate_of},
    )
    return shard


def auto_triaged_shards(
    db: Session, *, project_id: str | None = None, limit: int = 20
) -> list[MemoryShard]:
    """The "recent auto-actions" lane (AL-227): shards the scorer published or rejected
    without a human, newest first. `scoring_source != ""` marks an auto-action."""
    stmt = select(MemoryShard).where(MemoryShard.scoring_source != "")
    if project_id:
        stmt = stmt.where(MemoryShard.project_id == project_id)
    stmt = stmt.order_by(MemoryShard.created_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def undo_triage(db: Session, shard_id: str) -> MemoryShard | None:
    """Undo an auto-action (AL-227): return the shard to the `candidate` queue for
    human review and clear the auto-triage markers so it leaves the auto-actions lane."""
    shard = db.get(MemoryShard, shard_id)
    if shard is None:
        return None
    shard.status = "candidate"
    shard.scoring_source = ""
    shard.auto_confidence = None
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
    # An edit is a write too — don't lose the user's text to a down embedder.
    shard.embedding = safe_embed(text_body)
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
            params["pid"] = project_id
            # Honor share_global_memory: only fold in global (NULL) shards when the
            # project opts in and we're not in hosted mode (AL-71).
            if _includes_global(db, project_id):
                project_clause = "AND (project_id = :pid OR project_id IS NULL)"
            else:
                project_clause = "AND project_id = :pid"
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
