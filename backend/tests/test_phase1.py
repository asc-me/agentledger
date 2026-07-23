"""Phase 1: real memory intelligence + full MCP surface (all on the stub provider)."""
import json


def _key(client, auth):
    return client.post("/api/api-keys", json={"name": "p1"}, headers=auth).json()["plaintext"]


def _call(client, key, name, args):
    r = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": name, "arguments": args}},
        headers={"X-API-Key": key},
    )
    return json.loads(r.json()["result"]["content"][0]["text"])


def test_reembed_on_shard_edit_changes_ranking(client, auth):
    # Create a shard about "kubernetes", then edit it to be about "postgres".
    s = client.post(
        "/api/memory/shards", json={"text": "Runs on kubernetes clusters", "scope": "global"}, headers=auth
    ).json()
    client.patch(f"/api/memory/shards/{s['id']}", json={"text": "Runs on a single postgres container"}, headers=auth)
    hits = client.post(
        "/api/memory/search", json={"query": "postgres container", "top_k": 1}, headers=auth
    ).json()
    assert "postgres" in hits[0]["shard"]["text"]  # re-embedded, so it now matches


def test_auto_extraction_on_done(client, auth):
    before = len(client.get("/api/memory/shards", headers=auth).json())
    # AL-15 is `next` in the seed; moving it to done should mint a lesson shard.
    client.patch("/api/items/AL-15", json={"status": "done"}, headers=auth)
    shards = client.get("/api/memory/shards", headers=auth).json()
    assert len(shards) == before + 1
    assert any(s["source"] == "lesson from AL-15" for s in shards)
    # Idempotent: re-setting done doesn't double-extract.
    client.patch("/api/items/AL-15", json={"status": "review"}, headers=auth)
    client.patch("/api/items/AL-15", json={"status": "done"}, headers=auth)
    assert len(client.get("/api/memory/shards", headers=auth).json()) == before + 1


def test_export_then_import_roundtrip(client, auth):
    # project_id is required since the authz pass (AL-42) — no all-projects dump.
    exported = client.get("/api/memory/export?project_id=core", headers=auth).json()["shards"]
    assert len(exported) == 5
    n = client.post("/api/memory/import", json={"shards": exported[:2]}, headers=auth).json()["imported"]
    assert n == 2
    assert len(client.get("/api/memory/shards", headers=auth).json()) == 7


def test_backfill_reembeds_all(client, auth):
    r = client.post("/api/memory/backfill", headers=auth).json()
    assert r["reembedded"] == 5


def test_agent_chat_grounded(client, auth):
    r = client.post("/api/agent/chat", json={"message": "pgvector self-host"}, headers=auth).json()
    assert "Project state" in r["reply"]
    assert len(r["shards"]) >= 1


def test_agent_chat_stream_sse(client, auth):
    r = client.post("/api/agent/chat/stream", json={"message": "pgvector self-host"}, headers=auth)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    body = r.text
    assert "event: shards" in body
    assert "event: delta" in body
    assert body.rstrip().endswith("event: done\ndata: {}")
    # Reassemble the streamed reply from the delta events.
    reply = ""
    for block in body.split("\n\n"):
        if block.startswith("event: delta"):
            data = block.split("data: ", 1)[1]
            reply += json.loads(data)["text"]
    assert "Project state" in reply


def test_mcp_all_new_tools(client, auth):
    key = _key(client, auth)

    backlog = _call(client, key, "get_backlog", {"limit": 5})
    assert all(i["status"] in ("backlog", "next") for i in backlog["results"])
    assert backlog["limit"] == 5 and "total" in backlog and "has_more" in backlog

    details = _call(client, key, "get_item_details", {"id": "AL-08"})
    assert details["id"] == "AL-08"
    assert "linked_shards" in details

    nxt = _call(client, key, "suggest_next", {})
    assert nxt["status"] in ("next", "backlog")

    link = _call(client, key, "link_items", {"a": "AL-12", "b": "AL-08", "type": "dependency"})
    assert link["a"] == "AL-12" and link["type"] == "dependency"

    lessons = _call(client, key, "extract_lessons", {"id": "AL-11"})
    assert isinstance(lessons["results"], list) and len(lessons["results"]) >= 1

    digest = _call(client, key, "generate_digest", {})
    assert "digest" in digest and "Status:" in digest["digest"]


def test_link_items_rejects_bad_type(client, auth):
    key = _key(client, auth)
    out = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "link_items", "arguments": {"a": "AL-1", "b": "AL-2", "type": "banana"}}},
        headers={"X-API-Key": key},
    ).json()
    assert out["result"]["isError"] is True
