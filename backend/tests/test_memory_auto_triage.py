"""AL-227: memory auto-triage. The AL-151 scorer ACTS on agent candidates on write —
auto-rejecting near-dups / resembles-rejected (on by default) and auto-publishing
strongly-corroborated lessons (off by default) — behind per-project toggles, with
every auto-action audited and undoable. Fresh projects give empty, deterministic
pools; the stub embedder yields identical vectors for identical text."""


def _mcp(client, key, tool, args):
    return client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": tool, "arguments": args}},
        headers={"X-API-Key": key},
    ).json()["result"]["structuredContent"]


def _key(client, auth, **body):
    return client.post("/api/api-keys", json={"name": "mem", **body}, headers=auth).json()["plaintext"]


def _proj(client, auth, name):
    return client.post("/api/projects", json={"name": name}, headers=auth).json()["id"]


def _login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": "agentledger"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---- defaults ----

def test_new_project_defaults(client, auth):
    """Reject on, accept + LLM judge off — the safe posture (AL-227)."""
    p = client.post("/api/projects", json={"name": "TriageDefaults"}, headers=auth).json()
    assert p["memory_auto_reject"] is True
    assert p["memory_auto_accept"] is False
    assert p["memory_llm_judge"] is False


# ---- auto-reject (default on) ----

def test_auto_reject_drops_duplicate_of_published_on_write(client, auth):
    pid = _proj(client, auth, "AutoRejDup")
    key = _key(client, auth, project_id=pid)
    pub = _mcp(client, key, "add_memory", {"text": "prefer idempotency keys on writes"})
    client.post(f"/api/memory/shards/{pub['id']}/publish", headers=auth)  # now trusted
    # An identical candidate is a near-duplicate → auto-rejected in the same call.
    dup = _mcp(client, key, "add_memory", {"text": "prefer idempotency keys on writes"})
    assert dup["status"] == "rejected"
    assert dup["scoring_source"] == "similarity"
    assert dup["auto_confidence"] is not None and dup["auto_confidence"] >= 0.95
    # It never reaches the human review queue.
    queue = client.get(f"/api/memory/candidates?project_id={pid}", headers=auth).json()
    assert all(r["id"] != dup["id"] for r in queue)


def test_auto_reject_drops_resembles_rejected_on_write(client, auth):
    pid = _proj(client, auth, "AutoRejBad")
    key = _key(client, auth, project_id=pid)
    bad = _mcp(client, key, "add_memory", {"text": "disable auth in dev to move faster"})
    client.post(f"/api/memory/shards/{bad['id']}/reject", headers=auth)
    again = _mcp(client, key, "add_memory", {"text": "disable auth in dev to move faster"})
    assert again["status"] == "rejected"
    assert again["scoring_source"] == "similarity"


def test_auto_reject_off_keeps_candidate(client, auth):
    pid = _proj(client, auth, "AutoRejOff")
    client.patch(f"/api/projects/{pid}", json={"memory_auto_reject": False}, headers=auth)
    key = _key(client, auth, project_id=pid)
    pub = _mcp(client, key, "add_memory", {"text": "always paginate list endpoints"})
    client.post(f"/api/memory/shards/{pub['id']}/publish", headers=auth)
    dup = _mcp(client, key, "add_memory", {"text": "always paginate list endpoints"})
    # Advisory scorer still says reject, but with the toggle off nothing acts.
    assert dup["status"] == "candidate"
    assert dup["scoring_source"] == ""


def test_novel_candidate_is_left_for_review(client, auth):
    """A novel lesson has no strong signal → stays a candidate even with reject on."""
    pid = _proj(client, auth, "AutoNovel")
    key = _key(client, auth, project_id=pid)
    s = _mcp(client, key, "add_memory", {"text": "the flux capacitor prefers 1.21 gigawatts"})
    assert s["status"] == "candidate"


# ---- auto-accept (default off) ----

def test_auto_accept_publishes_high_confidence_recurrence(client, auth):
    pid = _proj(client, auth, "AutoAcc")
    client.patch(f"/api/projects/{pid}", json={"memory_auto_accept": True}, headers=auth)
    key = _key(client, auth, project_id=pid)
    text = "always set a timeout on outbound http"
    statuses = [_mcp(client, key, "add_memory", {"text": text})["status"] for _ in range(3)]
    # Recurrence lifts confidence: by the 3rd identical candidate it crosses the
    # auto-publish bar (>= 0.9) and publishes without a human.
    assert statuses[-1] == "published"


def test_auto_accept_off_by_default_keeps_recurring_candidate(client, auth):
    pid = _proj(client, auth, "AutoAccOff")
    key = _key(client, auth, project_id=pid)
    text = "always set a timeout on outbound http"
    statuses = [_mcp(client, key, "add_memory", {"text": text})["status"] for _ in range(3)]
    # No auto-accept → the recurring lesson waits in the queue for a human.
    assert statuses == ["candidate", "candidate", "candidate"]


# ---- audit + undo ----

def test_auto_action_is_audited(client, auth):
    pid = _proj(client, auth, "AutoAudit")
    key = _key(client, auth, project_id=pid)
    pub = _mcp(client, key, "add_memory", {"text": "cache invalidation needs a version tag"})
    client.post(f"/api/memory/shards/{pub['id']}/publish", headers=auth)
    _mcp(client, key, "add_memory", {"text": "cache invalidation needs a version tag"})
    actions = [e["action"] for e in client.get(f"/api/events?project_id={pid}", headers=auth).json()["results"]]
    assert "auto_reject_shard" in actions


def test_auto_actions_lane_and_undo(client, auth):
    pid = _proj(client, auth, "AutoUndo")
    key = _key(client, auth, project_id=pid)
    pub = _mcp(client, key, "add_memory", {"text": "retry only idempotent requests"})
    client.post(f"/api/memory/shards/{pub['id']}/publish", headers=auth)
    dup = _mcp(client, key, "add_memory", {"text": "retry only idempotent requests"})
    assert dup["status"] == "rejected"

    # The auto-actions lane surfaces it.
    lane = client.get(f"/api/memory/auto-actions?project_id={pid}", headers=auth).json()
    assert any(s["id"] == dup["id"] for s in lane)

    # Undo returns it to the candidate queue and clears the auto markers.
    r = client.post(f"/api/memory/shards/{dup['id']}/undo-auto", headers=auth)
    assert r.status_code == 200
    restored = r.json()
    assert restored["status"] == "candidate"
    assert restored["scoring_source"] == ""
    assert restored["auto_confidence"] is None
    # It's back in review and gone from the lane.
    queue = client.get(f"/api/memory/candidates?project_id={pid}", headers=auth).json()
    assert any(s["id"] == dup["id"] for s in queue)
    lane2 = client.get(f"/api/memory/auto-actions?project_id={pid}", headers=auth).json()
    assert all(s["id"] != dup["id"] for s in lane2)
    # The undo is itself audited.
    actions = [e["action"] for e in client.get(f"/api/events?project_id={pid}", headers=auth).json()["results"]]
    assert "undo_auto_shard" in actions


def test_read_only_member_cannot_undo(client):
    alex = _login(client, "alex@ascme-labs.com")
    key = _key(client, alex, project_id="core")
    pub = _mcp(client, key, "add_memory", {"text": "canary undo authz zzz"})
    client.post(f"/api/memory/shards/{pub['id']}/publish", headers=alex)
    dup = _mcp(client, key, "add_memory", {"text": "canary undo authz zzz"})
    ops = _login(client, "ops@ascme-labs.com")  # read-only on core
    r = client.post(f"/api/memory/shards/{dup['id']}/undo-auto", headers=ops)
    assert r.status_code == 403


# ---- human writes are never triaged ----

def test_human_shard_not_triaged(client, auth):
    """A human write is trusted immediately — auto-triage only judges agent candidates."""
    pid = _proj(client, auth, "HumanNoTriage")
    key = _key(client, auth, project_id=pid)
    bad = _mcp(client, key, "add_memory", {"text": "human override note qwerty"})
    client.post(f"/api/memory/shards/{bad['id']}/reject", headers=auth)
    # Same text, but written by a human via REST → published, not auto-rejected.
    created = client.post("/api/memory/shards",
                          json={"text": "human override note qwerty", "scope": "global", "project_id": pid},
                          headers=auth).json()
    assert created["status"] == "published"
    assert created["scoring_source"] == ""
