"""AL-133: setup_project first-run bootstrap checklist + empty-project detection."""


def _key(client, auth, project_id, scopes=None):
    body = {"name": "agent", "project_id": project_id}
    if scopes:
        body["scopes"] = scopes
    return client.post("/api/api-keys", json=body, headers=auth).json()["plaintext"]


def _sc(client, key, tool, args=None):
    return client.post("/api/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": args or {}}},
        headers={"X-API-Key": key}).json()["result"]["structuredContent"]


def test_setup_project_lists_the_four_v1_steps(client, auth):
    r = _sc(client, _key(client, auth, "core"), "setup_project")
    assert [s["name"] for s in r["steps"]] == [
        "Confirm the project", "Build the code graph", "Load memories", "Propose work items"]
    assert r["project_id"] == "core"
    # sources are surfaced + extensible per D2
    assert "AGENTS.md" in r["steps"][2]["sources"]


def test_empty_project_flags_pending_and_get_context_empty(client, auth):
    proj = client.post("/api/projects", json={"name": "Fresh"}, headers=auth).json()
    key = _key(client, auth, proj["id"])
    setup = _sc(client, key, "setup_project")
    assert setup["empty"] is True and setup["complete"] is False
    assert all(s["status"] == "pending" for s in setup["steps"][1:])  # steps 2–4 pending
    assert _sc(client, key, "get_context")["empty"] is True  # the first-run signal


def test_checklist_reflects_progress_resumably(client, auth):
    proj = client.post("/api/projects", json={"name": "Grows"}, headers=auth).json()
    key = _key(client, auth, proj["id"])
    _sc(client, key, "describe_code", {"nodes": [{"path": "x.py", "summary": "x"}]})
    setup = _sc(client, key, "setup_project")
    assert setup["empty"] is False
    graph = next(s for s in setup["steps"] if s["name"] == "Build the code graph")
    assert graph["status"] == "done"  # re-run reflects the new state


def test_setup_project_is_read_only_and_in_a_read_key_manifest(client, auth):
    key = _key(client, auth, "core", scopes=["read"])
    tools = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                        headers={"X-API-Key": key}).json()["result"]["tools"]
    assert "setup_project" in {t["name"] for t in tools}  # visible to a read-only key
