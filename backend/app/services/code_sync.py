"""Local→cloud code-graph push (AL-139) — the client side of the sync (cloud receiver is
AL-137, `POST /api/sync/code-graph`).

Incremental by content hash: only nodes whose describe output changed since the last confirmed
push ship. The last-pushed manifest ({path: content_hash}) lives in `CodeSyncState` and is
updated **per confirmed batch**, so an interrupted push resumes without re-sending confirmed
work (the resumability guarantee, D4). Paths removed locally are pruned on the cloud (the
staleness guard). Vectors never leave the box — the payload is summaries + hashes; the cloud
re-embeds (D1).
"""
from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import CodeSyncState, utcnow
from app.services import code_graph

_BATCH = 200      # nodes per request — bounds payload size and sets resumability granularity
_TIMEOUT = 30.0


class NotLinked(Exception):
    """No cloud sync target configured — a pure local-only instance never pushes (D2)."""


def compute_diff(local: dict[str, str], pushed: dict[str, str]) -> tuple[list[str], list[str]]:
    """(changed, removed): paths whose hash is new or differs from the last push, and paths
    that were pushed before but are gone locally now."""
    changed = sorted(p for p, h in local.items() if pushed.get(p) != h)
    removed = sorted(p for p in pushed if p not in local)
    return changed, removed


def _node_payload(n) -> dict:
    return {"path": n.path, "kind": n.kind, "name": n.name, "lang": n.lang,
            "summary": n.summary, "content_hash": n.content_hash}


def _post(url: str, api_key: str, body: dict) -> None:
    resp = httpx.post(f"{url.rstrip('/')}/api/sync/code-graph", json=body,
                      headers={"X-API-Key": api_key}, timeout=_TIMEOUT)
    resp.raise_for_status()


def push(db: Session, *, project_id: str, cloud_url: str = "", api_key: str = "",
         batch_size: int = _BATCH) -> dict:
    """Push the local code graph for `project_id` to the linked cloud tenant, incrementally."""
    url = cloud_url or settings.sync_cloud_url
    key = api_key or settings.sync_api_key
    if not url or not key:
        raise NotLinked("no cloud sync target configured (set SYNC_CLOUD_URL / SYNC_API_KEY)")

    nodes = {n.path: n for n in code_graph.list_nodes(db, project_id)}
    local = {p: (n.content_hash or "") for p, n in nodes.items()}

    state = db.get(CodeSyncState, project_id)
    if state is None:
        state = CodeSyncState(project_id=project_id, manifest={})
        db.add(state)
    pushed = dict(state.manifest or {})

    changed, removed = compute_diff(local, pushed)

    sent = 0
    for i in range(0, len(changed), batch_size):
        chunk = changed[i:i + batch_size]
        _post(url, key, {"nodes": [_node_payload(nodes[p]) for p in chunk]})
        for p in chunk:
            pushed[p] = local[p]
        state.manifest = dict(pushed)     # persist progress BEFORE the next batch → resumable
        state.last_synced_at = utcnow()
        db.commit()
        sent += len(chunk)

    if removed:
        _post(url, key, {"remove": removed})
        for p in removed:
            pushed.pop(p, None)
        state.manifest = dict(pushed)
        state.last_synced_at = utcnow()
        db.commit()

    # Edges are lightweight and idempotent on the cloud (upsert_edge skips dupes); push the
    # current set whenever nodes moved. Edge-level incrementality is a follow-up.
    if changed or removed:
        edges = code_graph.list_edges(db, project_id)
        if edges:
            _post(url, key, {"edges": [{"src": e.src, "dst": e.dst, "type": e.type} for e in edges]})

    return {"project_id": project_id, "pushed": sent, "removed": len(removed),
            "unchanged": len(local) - len(changed)}
