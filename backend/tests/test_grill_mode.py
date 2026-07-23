"""AL-67: interactive grill mode — SSE interrogation + fold-decisions-into-PRD."""


def _login(client, email="alex@ascme-labs.com"):
    r = client.post("/api/auth/login", json={"email": email, "password": "agentledger"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _prd(client, auth, **body):
    return client.post("/api/prds", json={"template": "standard", "project_id": "core", **body},
                       headers=auth).json()


# ---- grill stream ----

def test_grill_stream_yields_deltas_and_done(client, auth):
    prd = _prd(client, auth, title="Streamed")
    r = client.post(f"/api/prds/{prd['id']}/grill/stream", json={"message": "", "history": []}, headers=auth)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    text = r.text
    assert "event: delta" in text
    assert "event: done" in text
    assert "?" in text  # the opening turn asks questions


def test_grill_stream_missing_prd_404(client, auth):
    r = client.post("/api/prds/PRD-9999/grill/stream", json={"message": "hi", "history": []}, headers=auth)
    assert r.status_code == 404


# ---- grill apply (fold decisions in) ----

def test_grill_apply_folds_decisions_into_body(client, auth):
    prd = _prd(client, auth, title="Applied")
    history = [
        {"role": "agent", "text": "What is out of scope?"},
        {"role": "user", "text": "Mobile is out of scope for v1."},
        {"role": "agent", "text": "What's the failure mode on bad input?"},
        {"role": "user", "text": "Reject with a typed validation error."},
    ]
    r = client.post(f"/api/prds/{prd['id']}/grill/apply", json={"history": history}, headers=auth)
    assert r.status_code == 200
    body = r.json()["body"]
    assert "Mobile is out of scope" in body
    assert "typed validation error" in body
    assert body.startswith(prd["body"].rstrip()[:20])  # preserves the original PRD


def test_grill_apply_no_answers_is_noop(client, auth):
    prd = _prd(client, auth, title="Empty grill")
    r = client.post(f"/api/prds/{prd['id']}/grill/apply",
                    json={"history": [{"role": "agent", "text": "a question?"}]}, headers=auth)
    assert r.json()["body"] == prd["body"]


# ---- authz: reading a foreign PRD's grill is refused ----

def test_grill_foreign_prd_hidden(client, auth):
    web_prd = client.post("/api/prds", json={"title": "W", "project_id": "web"}, headers=auth).json()
    ops = _login(client, "ops@ascme-labs.com")  # no access to web
    r = client.post(f"/api/prds/{web_prd['id']}/grill/apply", json={"history": []}, headers=ops)
    assert r.status_code == 404  # existence-hiding
