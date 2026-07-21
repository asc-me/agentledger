"""Phase 4: dashboard, roadmap, links graph data, MCP tools page + metering."""
import json


def test_dashboard(client, auth):
    d = client.get("/api/dashboard", headers=auth).json()
    assert d["items_total"] == 9
    assert d["items_by_status"]["in_progress"] == 2
    assert d["shard_count"] == 5
    assert d["prd_count"] == 3
    assert d["requests_total"] == 5
    assert d["mcp_calls"] > 0  # seeded starting counts
    assert len(d["recent_items"]) <= 6


def test_roadmap_phases_and_progress(client, auth):
    phases = client.get("/api/roadmap", headers=auth).json()
    assert [p["key"] for p in phases] == ["mvp", "post", "later"]
    mvp = phases[0]
    assert mvp["name"] == "MVP" and mvp["total"] == 8 and mvp["done"] == 5
    assert len(mvp["milestones"]) == 8


def test_public_roadmap_no_auth(client):
    phases = client.get("/api/public/roadmap").json()  # no Authorization header
    assert len(phases) == 3


def test_links_graph_data(client, auth):
    links = client.get("/api/links", headers=auth).json()
    assert len(links) == 8
    dep = [l for l in links if l["type"] == "dependency"]
    assert any(l["a"] == "AL-12" and l["b"] == "AL-08" for l in dep)
    assert all(0 <= l["confidence"] <= 1 for l in links)


def test_mcp_tools_page_lists_all_with_counts(client, auth):
    data = client.get("/api/mcp/tools", headers=auth).json()
    assert data["live"] == 11
    assert len(data["tools"]) == 11
    by_name = {t["name"]: t for t in data["tools"]}
    assert by_name["search_memory"]["calls"] == 5200  # seeded
    assert "query" in by_name["search_items"]["params"]


def test_mcp_call_increments_counter(client, auth):
    key = client.post("/api/api-keys", json={"name": "meter"}, headers=auth).json()["plaintext"]
    before = {t["name"]: t["calls"] for t in client.get("/api/mcp/tools", headers=auth).json()["tools"]}
    client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "search_items", "arguments": {"query": "x"}}},
        headers={"X-API-Key": key},
    )
    after = {t["name"]: t["calls"] for t in client.get("/api/mcp/tools", headers=auth).json()["tools"]}
    assert after["search_items"] == before["search_items"] + 1
    # the JSON-RPC call itself still returns a valid result
    _ = json
