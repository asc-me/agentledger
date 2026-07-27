"""AL-137: local↔cloud code-graph sync ingest — sync-scoped credential, tenant-safe target,
cloud re-embeds (no vectors on the wire), audited to the human behind the key."""


def _key(client, auth, scopes, project_id="core"):
    return client.post("/api/api-keys",
                       json={"name": "spoke", "scopes": scopes, "project_id": project_id},
                       headers=auth).json()["plaintext"]


_NODES = [
    {"path": "backend/app/sync.py", "kind": "file", "name": "sync router",
     "summary": "Cloud receiver for the local code-graph push.", "content_hash": "h1"},
    {"path": "backend/app/services/code_graph.py", "kind": "file", "name": "code graph",
     "summary": "Upsert and embed code nodes.", "content_hash": "h2"},
]
_EDGES = [{"src": "backend/app/sync.py", "dst": "backend/app/services/code_graph.py", "type": "imports"}]


def _ingest(client, key, **body):
    return client.post("/api/sync/code-graph", json=body, headers={"X-API-Key": key})


def test_sync_ingests_and_reembeds_cloud_side(client, auth):
    from app.db import SessionLocal
    from app.services import code_graph

    key = _key(client, auth, scopes=["read", "sync"])
    r = _ingest(client, key, nodes=_NODES, edges=_EDGES)

    assert r.status_code == 200
    data = r.json()
    assert data["project_id"] == "core" and data["nodes_upserted"] == 2 and data["edges_upserted"] == 1

    # the nodes landed in core AND were embedded cloud-side (D1) — the payload carried no vectors
    db = SessionLocal()
    try:
        got = {n.path: n for n in code_graph.list_nodes(db, "core")}
        assert "backend/app/sync.py" in got
        assert got["backend/app/sync.py"].embedding is not None  # re-embedded on ingest
        assert got["backend/app/sync.py"].summary == "Cloud receiver for the local code-graph push."
    finally:
        db.close()


def test_sync_requires_the_sync_scope(client, auth):
    # a plain read/write key can't bulk-ingest — sync is a distinct, purpose-minted credential
    key = _key(client, auth, scopes=["read", "write"])
    r = _ingest(client, key, nodes=_NODES)
    assert r.status_code == 403 and "sync" in r.json()["detail"]


def test_sync_target_is_the_key_project_not_the_payload(client, auth):
    # tenant safety (D3): the schema has no project_id, so a smuggled one is ignored — the
    # ingest always lands in the sync credential's own project
    key = _key(client, auth, scopes=["sync"], project_id="core")
    r = client.post("/api/sync/code-graph",
                    json={"nodes": _NODES, "project_id": "someone-elses-project"},
                    headers={"X-API-Key": key})
    assert r.status_code == 200 and r.json()["project_id"] == "core"


def test_sync_unauthenticated_is_401(client):
    assert client.post("/api/sync/code-graph", json={"nodes": _NODES}).status_code == 401


def test_sync_prune_marks_absent_nodes_stale(client, auth):
    key = _key(client, auth, scopes=["sync"])
    _ingest(client, key, nodes=_NODES)
    # a second push with only one node + prune marks the other stale (not deleted)
    r = _ingest(client, key, nodes=_NODES[:1], prune=True)
    assert r.status_code == 200 and r.json()["marked_stale"] == 1


def test_sync_is_audited_with_the_human_principal(client, auth):
    key = _key(client, auth, scopes=["sync"])
    _ingest(client, key, nodes=_NODES)
    ev = client.get("/api/events", params={"project_id": "core"}, headers=auth).json()
    top = next(e for e in ev["results"] if e["action"] == "sync_code_graph")
    assert top["target_id"] == "core" and top["agent"] == "spoke"  # the sync key is the agent
    assert top["principal"]  # AL-197 — the human who minted it, not just the key
