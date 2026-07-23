"""AL-47: the MCP dispatcher validates args and speaks a typed error taxonomy
with repair hints — the platform's core agent-facing UX (review finding F6)."""


def _key(client, auth):
    return client.post("/api/api-keys", json={"name": "e"}, headers=auth).json()["plaintext"]


def _call(client, key, tool, arguments):
    return client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": tool, "arguments": arguments}},
        headers={"X-API-Key": key},
    ).json()


def _err(client, key, tool, arguments):
    result = _call(client, key, tool, arguments)["result"]
    assert result.get("isError") is True, result
    return result["structuredContent"]["error"]


# ---- schema validation before dispatch ----

def test_missing_required_arg_is_validation_with_hint(client, auth):
    key = _key(client, auth)
    err = _err(client, key, "create_item", {})  # title is required
    assert err["code"] == "validation"
    assert "title" in err["message"]
    assert "required" in err["hint"]  # names the required set


def test_bad_enum_lists_allowed_values(client, auth):
    key = _key(client, auth)
    err = _err(client, key, "create_item", {"title": "x", "status": "shipped"})
    assert err["code"] == "validation"
    assert "backlog" in err["hint"] and "done" in err["hint"]


def test_wrong_type_is_validation(client, auth):
    key = _key(client, auth)
    err = _err(client, key, "create_item", {"title": "x", "effort": "lots"})
    assert err["code"] == "validation"
    assert "integer" in err["message"]


# ---- taxonomy ----

def test_not_found_carries_repair_hint(client, auth):
    key = _key(client, auth)
    err = _err(client, key, "update_item", {"id": "AL-9999", "status": "done"})
    assert err["code"] == "not_found"
    assert "search_items" in err["hint"]


def test_lease_conflict_is_conflict(client, auth):
    key = _key(client, auth)
    # AL-12 exists but this agent holds no lease on it.
    err = _err(client, key, "heartbeat", {"id": "AL-12"})
    assert err["code"] == "conflict"


def test_unknown_tool_is_validation(client, auth):
    key = _key(client, auth)
    err = _err(client, key, "teleport", {})
    assert err["code"] == "validation"
    assert "tools/list" in err["hint"]


# ---- body parsing no longer escapes the envelope ----

def test_malformed_body_is_parse_error_not_500(client, auth):
    key = _key(client, auth)
    r = client.post("/api/mcp", content=b"{not json", headers={"X-API-Key": key})
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32700


# ---- idempotency scoping ----

def test_idempotency_key_reuse_across_tools_conflicts(client, auth):
    key = _key(client, auth)
    _call(client, key, "create_item", {"title": "first", "idempotency_key": "tok-1"})
    # Same token, different tool → conflict, not a silent wrong-resource return.
    err = _err(client, key, "add_memory", {"text": "note", "idempotency_key": "tok-1"})
    assert err["code"] == "conflict"
    assert "create_item" in err["message"]


def test_idempotency_same_tool_returns_original(client, auth):
    key = _key(client, auth)
    a = _call(client, key, "create_item", {"title": "once", "idempotency_key": "tok-2"})["result"]
    b = _call(client, key, "create_item", {"title": "once", "idempotency_key": "tok-2"})["result"]
    assert a["structuredContent"]["id"] == b["structuredContent"]["id"]


# ---- stable shapes / receipts ----

def test_suggest_next_wraps_item(client, auth):
    key = _key(client, auth)
    res = _call(client, key, "suggest_next", {})["result"]["structuredContent"]
    assert "item" in res  # never a bare null


def test_describe_code_echoes_paths(client, auth):
    key = _key(client, auth)
    res = _call(client, key, "describe_code", {
        "nodes": [{"path": "backend/app/x.py", "kind": "file", "summary": "x"}],
    })["result"]["structuredContent"]
    assert res["upserted_paths"] == ["backend/app/x.py"]
    assert res["stale_paths"] == []


# ---- metering only on success (dashboard not inflated by errors) ----

def test_failed_calls_do_not_meter(client, auth):
    before = {t["name"]: t["calls"] for t in client.get("/api/mcp/tools", headers=auth).json()["tools"]}
    key = _key(client, auth)
    _err(client, key, "update_item", {"id": "AL-9999"})  # not_found
    after = {t["name"]: t["calls"] for t in client.get("/api/mcp/tools", headers=auth).json()["tools"]}
    assert after.get("update_item", 0) == before.get("update_item", 0)
