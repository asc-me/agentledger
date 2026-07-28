"""AL-221: unlink_items removes a typed relationship — the inverse of link_items."""
import json


def _mcp(client, key, name, args):
    r = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": name, "arguments": args}},
        headers={"X-API-Key": key},
    )
    return json.loads(r.json()["result"]["content"][0]["text"])


def _key(client, auth, scopes=None):
    body = {"name": "linker"}
    if scopes is not None:
        body["scopes"] = scopes
    return client.post("/api/api-keys", json=body, headers=auth).json()["plaintext"]


def test_unlink_items_round_trip_is_idempotent(client, auth):
    key = _key(client, auth)
    a = _mcp(client, key, "create_item", {"title": "dep A"})["id"]
    b = _mcp(client, key, "create_item", {"title": "dep B"})["id"]
    _mcp(client, key, "link_items", {"a": a, "b": b, "type": "dependency"})

    out = _mcp(client, key, "unlink_items", {"a": a, "b": b, "type": "dependency"})
    assert out["removed"] == 1
    # Idempotent: unlinking again removes nothing and is not an error.
    assert _mcp(client, key, "unlink_items", {"a": a, "b": b, "type": "dependency"})["removed"] == 0


def test_unlink_items_omitting_type_removes_every_type_for_the_pair(client, auth):
    key = _key(client, auth)
    a = _mcp(client, key, "create_item", {"title": "multi A"})["id"]
    b = _mcp(client, key, "create_item", {"title": "multi B"})["id"]
    _mcp(client, key, "link_items", {"a": a, "b": b, "type": "dependency"})
    _mcp(client, key, "link_items", {"a": a, "b": b, "type": "semantic"})

    assert _mcp(client, key, "unlink_items", {"a": a, "b": b})["removed"] == 2


def test_unlink_items_is_gated_by_write_scope(client, auth):
    ro = _key(client, auth, scopes=["read"])
    # Scope-gated manifest (AL-78): a read-only key never sees the write tool.
    tools = client.post(
        "/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"X-API-Key": ro},
    ).json()["result"]["tools"]
    assert "unlink_items" not in {t["name"] for t in tools}
    # And calling it anyway is refused before any lookup.
    r = client.post(
        "/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "unlink_items", "arguments": {"a": "AL-01", "b": "AL-02"}}},
        headers={"X-API-Key": ro},
    ).json()
    assert r["result"]["isError"] is True
