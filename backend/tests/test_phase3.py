"""Phase 3: PRD tracker + markdown editor + versions + AI commands."""


def test_seeded_prds(client, auth):
    prds = client.get("/api/prds", headers=auth).json()
    assert len(prds) == 3
    ids = {p["id"] for p in prds}
    assert ids == {"PRD-1", "PRD-2", "PRD-3"}
    p1 = next(p for p in prds if p["id"] == "PRD-1")
    assert p1["status"] == "approved" and p1["version"] == "v1.0"
    assert "AL-08" in p1["linked"]


def test_get_prd_body_and_versions(client, auth):
    prd = client.get("/api/prds/PRD-1", headers=auth).json()
    assert prd["title"] == "AgentLedger Core MVP"
    assert prd["body"].startswith("# AgentLedger Core MVP")
    versions = client.get("/api/prds/PRD-1/versions", headers=auth).json()
    assert [v["version"] for v in versions] == ["v1.0", "v0.3", "v0.1"]  # newest first
    assert versions[0]["body"].startswith("# AgentLedger")  # latest snapshot has body


def test_create_from_template(client, auth):
    r = client.post("/api/prds", json={"title": "New Spec", "template": "standard"}, headers=auth)
    assert r.status_code == 201
    prd = r.json()
    assert prd["id"] == "PRD-4"
    assert "## Success Metrics" in prd["body"]
    assert prd["status"] == "draft" and prd["version"] == "v0.1"
    # An initial version snapshot exists.
    versions = client.get(f"/api/prds/{prd['id']}/versions", headers=auth).json()
    assert len(versions) == 1


def test_edit_and_status(client, auth):
    client.patch("/api/prds/PRD-3", json={"body": "# Rewritten\n\nfresh content"}, headers=auth)
    up = client.patch("/api/prds/PRD-3", json={"status": "review"}, headers=auth).json()
    assert up["status"] == "review"
    assert client.get("/api/prds/PRD-3", headers=auth).json()["body"] == "# Rewritten\n\nfresh content"


def test_invalid_status_rejected(client, auth):
    assert client.patch("/api/prds/PRD-3", json={"status": "shipped"}, headers=auth).status_code == 422


def test_create_version_snapshots_and_bumps(client, auth):
    client.patch("/api/prds/PRD-2", json={"body": "# v-next body"}, headers=auth)
    before = len(client.get("/api/prds/PRD-2/versions", headers=auth).json())
    up = client.post("/api/prds/PRD-2/versions", json={"note": "cut a version"}, headers=auth).json()
    assert up["version"] == "v0.5"  # bumped from v0.4
    versions = client.get("/api/prds/PRD-2/versions", headers=auth).json()
    assert len(versions) == before + 1
    assert versions[0]["version"] == "v0.5" and versions[0]["body"] == "# v-next body"
    assert versions[0]["note"] == "cut a version"


def test_link_item_add_and_remove(client, auth):
    linked = client.post("/api/prds/PRD-3/link", json={"item_id": "AL-04", "add": True}, headers=auth).json()
    assert "AL-04" in linked["linked"]
    unlinked = client.post("/api/prds/PRD-3/link", json={"item_id": "AL-04", "add": False}, headers=auth).json()
    assert "AL-04" not in unlinked["linked"]


def test_ai_command_stub(client, auth):
    r = client.post("/api/prds/PRD-1/ai", json={"command": "risks"}, headers=auth).json()
    assert "Risks & Open Questions" in r["text"]
    bad = client.post("/api/prds/PRD-1/ai", json={"command": "nope"}, headers=auth)
    assert bad.status_code == 422
