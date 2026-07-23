"""AL-69: grill decisions become candidate memory shards (the preservation
principle) — flowing through the AL-49 review boundary and AL-50 clustering."""


HISTORY = [
    {"role": "agent", "text": "What is out of scope for v1?"},
    {"role": "user", "text": "Mobile and offline mode are out of scope for v1."},
    {"role": "agent", "text": "Failure mode on bad input?"},
    {"role": "user", "text": "Reject with a typed validation error and a repair hint."},
    {"role": "user", "text": "ok"},  # too short → not a decision
]


def _login(client, email="alex@ascme-labs.com"):
    r = client.post("/api/auth/login", json={"email": email, "password": "agentledger"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _prd(client, auth):
    return client.post("/api/prds", json={"title": "Decisions", "project_id": "core"}, headers=auth).json()


def test_grill_apply_captures_decisions_as_candidates(client, auth):
    prd = _prd(client, auth)
    r = client.post(f"/api/prds/{prd['id']}/grill/apply", json={"history": HISTORY}, headers=auth).json()
    assert r["decisions_captured"] == 2  # the two substantive answers, not "ok"

    # They're candidate shards, origin agent:grill, sourced to the PRD — and hidden
    # from the default retrieval path until a human publishes them (AL-49).
    cands = client.get("/api/memory/candidates?project_id=core", headers=auth).json()
    grill = [c for c in cands if c["source"] == f"grill: {prd['id']}"]
    assert len(grill) == 2
    assert all(c["status"] == "candidate" and c["origin"] == "agent:grill" for c in grill)
    assert any("Mobile and offline" in c["text"] for c in grill)


def test_reapply_is_deduped(client, auth):
    prd = _prd(client, auth)
    client.post(f"/api/prds/{prd['id']}/grill/apply", json={"history": HISTORY}, headers=auth)
    second = client.post(f"/api/prds/{prd['id']}/grill/apply", json={"history": HISTORY}, headers=auth).json()
    assert second["decisions_captured"] == 0  # same answers → no duplicates
    cands = client.get("/api/memory/candidates?project_id=core", headers=auth).json()
    assert len([c for c in cands if c["source"] == f"grill: {prd['id']}"]) == 2


def test_capture_is_audited(client, auth):
    prd = _prd(client, auth)
    client.post(f"/api/prds/{prd['id']}/grill/apply", json={"history": HISTORY}, headers=auth)
    actions = [e["action"] for e in client.get("/api/events?project_id=core", headers=auth).json()["results"]]
    assert "grill_capture" in actions


def test_no_answers_captures_nothing(client, auth):
    prd = _prd(client, auth)
    r = client.post(f"/api/prds/{prd['id']}/grill/apply",
                    json={"history": [{"role": "agent", "text": "a question?"}]}, headers=auth).json()
    assert r["decisions_captured"] == 0
