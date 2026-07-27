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
from app.models import ApiKey
from app.security import authz
from app.security.deps import get_agent_key
from app.services import code_graph
from app.services import events as events_svc

router = APIRouter(prefix="/sync", tags=["sync"])


class CodeGraphIn(BaseModel):
    """Nodes/edges in `describe_code` shape — no `project_id` (resolved from the key) and no
    embeddings (re-embedded cloud-side)."""
    nodes: list[dict] = []
    edges: list[dict] = []
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
    events_svc.record_key(
        db, key, action="sync_code_graph", target_type="project", target_id=project_id,
        project_id=project_id,
        meta={"nodes_upserted": result["nodes_upserted"], "edges_upserted": result["edges_upserted"],
              "marked_stale": result["marked_stale"], "prune": body.prune},
    )
    return {"project_id": project_id, **result}
