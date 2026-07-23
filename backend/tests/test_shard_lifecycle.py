"""AL-49: agent memory is telemetry until a human publishes it. The candidate →
published boundary keeps unverified agent notes out of the default retrieval path."""


def _login(client, email="alex@ascme-labs.com"):
    r = client.post("/api/auth/login", json={"email": email, "password": "agentledger"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _key(client, auth, **body):
    return client.post("/api/api-keys", json={"name": "mem", **body}, headers=auth).json()["plaintext"]


def _mcp(client, key, tool, args):
    return client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": tool, "arguments": args}},
        headers={"X-API-Key": key},
    ).json()["result"]["structuredContent"]


# ---- the trust boundary ----

def test_agent_add_memory_is_candidate(client, auth):
    key = _key(client, auth, project_id="core")
    shard = _mcp(client, key, "add_memory", {"text": "agent-guessed fact about caching"})
    assert shard["status"] == "candidate"


# top_k high so eligibility, not the stub embedder's arbitrary ranking, decides
# membership — the tests are about the status filter, not relevance.
def test_candidate_hidden_from_default_search(client, auth):
    key = _key(client, auth, project_id="core")
    cid = _mcp(client, key, "add_memory", {"text": "zzz canary alpha"})["id"]
    hits = _mcp(client, key, "search_memory", {"query": "zzz canary alpha", "top_k": 50})
    assert all(h["id"] != cid for h in hits["results"])


def test_candidate_visible_with_include_flag(client, auth):
    key = _key(client, auth, project_id="core")
    cid = _mcp(client, key, "add_memory", {"text": "yyy canary beta"})["id"]
    hits = _mcp(client, key, "search_memory",
                {"query": "yyy canary beta", "top_k": 50, "include_candidates": True})
    assert any(h["id"] == cid for h in hits["results"])
    assert all(h["status"] in ("candidate", "published") for h in hits["results"])


def test_human_shard_is_published_and_searchable(client, auth):
    key = _key(client, auth, project_id="core")
    created = client.post("/api/memory/shards",
                          json={"text": "human-authored fact xyz", "scope": "global", "project_id": "core"},
                          headers=auth).json()
    assert created["status"] == "published"
    assert created["origin"].startswith("user:")
    hits = _mcp(client, key, "search_memory", {"query": "human-authored fact xyz"})
    assert any(h["text"] == "human-authored fact xyz" for h in hits["results"])


# ---- review flow ----

def test_publish_promotes_candidate_into_search(client, auth):
    key = _key(client, auth, project_id="core")
    shard = _mcp(client, key, "add_memory", {"text": "promote me wxyz"})
    q = {"query": "promote me wxyz", "top_k": 50}
    # invisible before publish (candidate not in the eligible set)
    assert all(h["id"] != shard["id"] for h in _mcp(client, key, "search_memory", q)["results"])
    r = client.post(f"/api/memory/shards/{shard['id']}/publish", headers=auth)
    assert r.status_code == 200 and r.json()["status"] == "published"
    # visible after
    assert any(h["id"] == shard["id"] for h in _mcp(client, key, "search_memory", q)["results"])


def test_rejected_never_surfaces(client, auth):
    key = _key(client, auth, project_id="core")
    shard = _mcp(client, key, "add_memory", {"text": "reject me qrst"})
    client.post(f"/api/memory/shards/{shard['id']}/reject", headers=auth)
    for inc in (False, True):
        hits = _mcp(client, key, "search_memory",
                    {"query": "reject me qrst", "top_k": 50, "include_candidates": inc})
        assert all(h["id"] != shard["id"] for h in hits["results"])


def test_candidates_queue_lists_only_candidates(client, auth):
    key = _key(client, auth, project_id="core")
    _mcp(client, key, "add_memory", {"text": "queue candidate one"})
    rows = client.get("/api/memory/candidates?project_id=core", headers=auth).json()
    assert rows and all(r["status"] == "candidate" for r in rows)


def test_review_records_an_event(client, auth):
    key = _key(client, auth, project_id="core")
    shard = _mcp(client, key, "add_memory", {"text": "audited publish abcd"})
    client.post(f"/api/memory/shards/{shard['id']}/publish", headers=auth)
    actions = [e["action"] for e in client.get("/api/events?project_id=core", headers=auth).json()["results"]]
    assert "publish_shard" in actions


# ---- authz ----

def test_read_only_member_cannot_publish(client):
    alex = _login(client, "alex@ascme-labs.com")
    key = _key(client, alex, project_id="core")
    shard = _mcp(client, key, "add_memory", {"text": "ops cannot publish this"})
    ops = _login(client, "ops@ascme-labs.com")  # read-only on core
    r = client.post(f"/api/memory/shards/{shard['id']}/publish", headers=ops)
    assert r.status_code == 403


# ---- AL-50: recurring-lesson clustering ----

def test_similar_candidates_cluster(client, auth):
    key = _key(client, auth, project_id="core")
    # Identical text → identical (deterministic stub) embedding → same cluster.
    for _ in range(3):
        _mcp(client, key, "add_memory", {"text": "always validate MCP args before dispatch"})
    _mcp(client, key, "add_memory", {"text": "unrelated note about drag reorder flicker on safari"})
    clusters = client.get("/api/memory/candidate-clusters?project_id=core", headers=auth).json()
    assert len(clusters) == 1
    c = clusters[0]
    assert c["size"] == 3
    assert len(c["members"]) == 2  # representative excluded


def test_promote_cluster_publishes_rep_and_rejects_dupes(client, auth):
    key = _key(client, auth, project_id="core")
    for _ in range(3):
        _mcp(client, key, "add_memory", {"text": "prefer typed errors with a repair hint"})
    cluster = client.get("/api/memory/candidate-clusters?project_id=core", headers=auth).json()[0]
    rep = cluster["representative"]["id"]
    dupes = [m["id"] for m in cluster["members"]]

    r = client.post("/api/memory/promote-cluster",
                    json={"publish_id": rep, "reject_ids": dupes}, headers=auth)
    assert r.status_code == 200
    # representative is now searchable; dupes never surface; queue is empty.
    hits = _mcp(client, key, "search_memory", {"query": "prefer typed errors repair hint", "top_k": 50})
    ids = {h["id"] for h in hits["results"]}
    assert rep in ids and not (ids & set(dupes))
    assert client.get("/api/memory/candidate-clusters?project_id=core", headers=auth).json() == []


def test_read_only_member_cannot_promote_cluster(client):
    alex = _login(client, "alex@ascme-labs.com")
    key = _key(client, alex, project_id="core")
    for _ in range(2):
        _mcp(client, key, "add_memory", {"text": "some recurring agent lesson zzz"})
    cluster = client.get("/api/memory/candidate-clusters?project_id=core", headers=alex).json()[0]
    ops = _login(client, "ops@ascme-labs.com")  # read-only on core
    r = client.post("/api/memory/promote-cluster",
                    json={"publish_id": cluster["representative"]["id"]}, headers=ops)
    assert r.status_code == 403


# ---- auto-extraction enters as candidate ----

def test_extract_lessons_are_candidates(client, auth):
    key = _key(client, auth, project_id="core")
    res = _mcp(client, key, "extract_lessons", {"id": "AL-12"})
    assert res["results"], "stub extractor should produce at least one lesson"
    assert all(r["status"] == "candidate" for r in res["results"])
