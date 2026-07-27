"""Local↔cloud sync ingest (AL-137, part of the local-first hybrid AL-134).

A linked local instance builds its code graph locally (the expensive LLM describe pass runs
on the dev's machine) and pushes the *result* here in bulk. This is the cloud receiver.

Two invariants come straight from the grill:
- **Tenant-safe (D3).** The target project is resolved SERVER-SIDE from the sync credential
  (`key_sync_ids`) — never from the payload — so a push can't land in another tenant's
  workspace even if the body names a different project.
- **Re-embed, don't trust foreign vectors (D1).** The payload carries node summaries + a
  content hash, NOT embedding vectors. `describe_code` → `upsert_node` re-embeds each summary
  with the cloud's OWN embedder, so cloud search stays in one comparable vector space.

Bulk one-request ingest (not N metered MCP calls), so a full-graph push doesn't burn the
hosted call quota (D7) — locally-executed describe work never touched the cloud in the first
place.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey, User
from app.security import authz
from app.security.deps import get_agent_key, get_current_user
from app.services import code_graph
from app.services import code_sync
from app.services import events as events_svc

router = APIRouter(prefix="/sync", tags=["sync"])


class CodeGraphIn(BaseModel):
    """Nodes/edges in `describe_code` shape — no `project_id` (resolved from the key) and no
    embeddings (re-embedded cloud-side). `remove` marks specific paths stale (incremental
    delete); `prune` marks everything not in this batch stale (full push)."""
    nodes: list[dict] = []
    edges: list[dict] = []
    remove: list[str] = []
    prune: bool = False


@router.post("/code-graph")
def ingest_code_graph(
    body: CodeGraphIn,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(get_agent_key),
):
    targets = authz.key_sync_ids(db, key)
    if not targets:
        raise HTTPException(
            403,
            "this key can't sync a code graph — it needs the 'sync' scope and its owner "
            "needs write access to the target project",
        )
    project_id = targets[0]  # a sync credential is pinned to one project
    result = code_graph.describe_code(
        db, project_id=project_id, nodes=body.nodes, edges=body.edges, prune=body.prune
    )
    marked = code_graph.mark_paths_stale(db, project_id, body.remove)
    if marked:
        db.commit()
    result["marked_stale"] += marked
    events_svc.record_key(
        db, key, action="sync_code_graph", target_type="project", target_id=project_id,
        project_id=project_id,
        meta={"nodes_upserted": result["nodes_upserted"], "edges_upserted": result["edges_upserted"],
              "marked_stale": result["marked_stale"], "prune": body.prune},
    )
    return {"project_id": project_id, **result}


@router.delete("/code-graph")
def purge_code_graph(db: Session = Depends(get_db), key: ApiKey = Depends(get_agent_key)):
    """Purge the synced code graph for the credential's project (AL-137 D8) — deletes every
    node + edge. Target resolved server-side from the sync credential, same as ingest."""
    targets = authz.key_sync_ids(db, key)
    if not targets:
        raise HTTPException(403, "this key can't purge a code graph — needs the 'sync' scope")
    project_id = targets[0]
    result = code_graph.delete_project_graph(db, project_id)
    db.commit()
    events_svc.record_key(db, key, action="purge_code_graph", target_type="project",
                          target_id=project_id, project_id=project_id, meta=result)
    return {"project_id": project_id, **result}


class PushIn(BaseModel):
    project_id: str = "core"


@router.post("/push")
def trigger_push(
    body: PushIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Push THIS (local) instance's code graph for a project up to its linked cloud tenant
    (AL-139) — the `agentledger sync` trigger. Only a member who can write the project may
    sync it; a `409` means the instance isn't linked to a cloud."""
    authz.require_writable(db, user.id, body.project_id, "item")
    try:
        return code_sync.push(db, project_id=body.project_id)
    except code_sync.NotLinked as e:
        raise HTTPException(409, str(e))


@router.post("/purge")
def trigger_purge(
    body: PushIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete THIS project's code graph from its linked cloud tenant (AL-137 D8) and reset the
    local sync manifest. Write-gated; `409` when not linked."""
    authz.require_writable(db, user.id, body.project_id, "item")
    try:
        return code_sync.purge(db, project_id=body.project_id)
    except code_sync.NotLinked as e:
        raise HTTPException(409, str(e))
