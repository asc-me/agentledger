"""AL-140: portable code-graph export/import — a cloud-free secondary transport that
re-embeds on arrival (D1)."""
_NODES = [
    {"path": "a.py", "kind": "file", "name": "a", "summary": "module a", "content_hash": "h1"},
    {"path": "b.py", "kind": "file", "name": "b", "summary": "module b", "content_hash": "h2"},
]
_EDGES = [{"src": "a.py", "dst": "b.py", "type": "imports"}]


def _login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": "agentledger"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _import(client, headers, project_id, nodes=_NODES, edges=None):
    return client.post("/api/sync/import",
                       json={"project_id": project_id, "nodes": nodes, "edges": edges or []},
                       headers=headers)


def test_export_import_round_trip_reembeds(client, auth):
    from app.db import SessionLocal
    from app.services import code_graph

    r = _import(client, auth, "core", edges=_EDGES)
    assert r.status_code == 200 and r.json()["nodes_upserted"] == 2 and r.json()["edges_upserted"] == 1

    bundle = client.get("/api/sync/export?project_id=core", headers=auth).json()
    assert bundle["bundle_version"] == 1 and bundle["project_id"] == "core"
    assert {"a.py", "b.py"} <= {n["path"] for n in bundle["nodes"]}
    assert "embedding" not in bundle["nodes"][0]  # vector-free bundle (D1)

    db = SessionLocal()
    try:
        got = {n.path: n for n in code_graph.list_nodes(db, "core")}
        assert got["a.py"].embedding is not None  # re-embedded by THIS instance on import
    finally:
        db.close()


def test_export_requires_auth(client):
    assert client.get("/api/sync/export?project_id=core").status_code == 401


def test_import_requires_write(client):
    ops = _login(client, "ops@ascme-labs.com")  # read-only on core
    assert _import(client, ops, "core").status_code == 403


def test_bundle_moves_between_projects_without_a_cloud(client, auth):
    _import(client, auth, "core", edges=_EDGES)
    bundle = client.get("/api/sync/export?project_id=core", headers=auth).json()

    proj = client.post("/api/projects", json={"name": "Imported"}, headers=auth).json()
    r = _import(client, auth, proj["id"], nodes=bundle["nodes"], edges=bundle["edges"])
    assert r.status_code == 200 and r.json()["nodes_upserted"] >= 2

    moved = client.get(f"/api/sync/export?project_id={proj['id']}", headers=auth).json()
    assert {"a.py", "b.py"} <= {n["path"] for n in moved["nodes"]}
