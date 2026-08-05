"""PRD status is derived from the grill, not chosen (AL-300 / PRD-15 D5).

Approval stops being something anyone sets and becomes something a PRD reaches:

    draft    — never grilled, or no answers recorded
    review   — grilled, answers recorded, dimensions still unanswered
    approved — the completion standard is met

The refusal is the visible half and the derivation is the important half. Today
`update_prd(status="approved")` is a single unguarded call — which is exactly how an
agent could freeze an intent baseline (AL-239) that nobody had read.
"""
import json

import pytest

from app.services import prds as prd_svc


@pytest.fixture()
def prd(client, auth):
    r = client.post("/api/prds", json={"title": "Derived", "project_id": "core"}, headers=auth)
    return r.json()["id"]


@pytest.fixture()
def agent_key(client, auth):
    r = client.post("/api/api-keys", json={"name": "loop", "scopes": ["read", "write"]},
                    headers=auth)
    return r.json()["plaintext"]


def _mcp(client, api_key, tool, args):
    r = client.post("/api/mcp",
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": tool, "arguments": args}},
                    headers={"X-API-Key": api_key})
    result = r.json()["result"]
    if result.get("isError"):
        return {"__ERR__": result["structuredContent"]["error"]}
    return json.loads(result["content"][0]["text"])


def _status(client, auth, prd_id):
    return client.get(f"/api/prds/{prd_id}", headers=auth).json()["status"]


def _answer(client, key, prd_id, text="A substantive answer."):
    return _mcp(client, key, "answer_grill", {"prd_id": prd_id, "answer": text})


# ---- the derivation ------------------------------------------------------------------
def test_a_fresh_prd_is_draft(client, auth, prd):
    assert _status(client, auth, prd) == "draft"


def test_answering_moves_it_to_review(client, auth, agent_key, prd):
    """Engagement without completion. The PRD is being worked on, and that is visible
    without anyone setting a status."""
    _answer(client, agent_key, prd)
    assert _status(client, auth, prd) == "review"


def test_finishing_the_grill_approves_it(client, auth, agent_key, prd):
    """The whole PRD in one test: nobody visits a settings screen, nobody clicks
    anything, and the spec ends up approved because it was interrogated."""
    for _ in range(len(prd_svc.DIMENSIONS)):
        _answer(client, agent_key, prd)
    assert _status(client, auth, prd) == "approved"


def test_a_deferral_can_be_what_completes_it(client, auth, agent_key, prd):
    """Deferring is a legitimate answer, so it has to be able to finish a grill —
    otherwise "we are consciously not deciding X" would block approval forever."""
    for _ in range(len(prd_svc.DIMENSIONS) - 1):
        _answer(client, agent_key, prd)
    assert _status(client, auth, prd) == "review"

    r = client.post(f"/api/prds/{prd}/grill/defer",
                    json={"dimension": "open_decisions", "reason": "pricing after beta"},
                    headers=auth)
    assert r.status_code == 200, r.text
    assert _status(client, auth, prd) == "approved"


# ---- the refusal ----------------------------------------------------------------------
def test_an_agent_cannot_set_approved(client, auth, agent_key, prd):
    """The call this item exists to close."""
    err = _mcp(client, agent_key, "update_prd", {"prd_id": prd, "status": "approved"})
    assert err["__ERR__"]["code"] == "conflict", err
    assert _status(client, auth, prd) == "draft"


def test_the_refusal_names_what_is_outstanding(client, auth, agent_key, prd):
    """A bare denial is not actionable. The agent has to learn what to go ask about."""
    _answer(client, agent_key, prd)
    err = _mcp(client, agent_key, "update_prd", {"prd_id": prd, "status": "approved"})
    message = err["__ERR__"]["message"]
    assert "grill" in message
    # Whatever remains must be named by name, not summarised as "some dimensions".
    assert any(d in message for d in prd_svc.DIMENSIONS), message


def test_a_human_cannot_set_approved_either(client, auth, prd):
    """Not a permission gate — nobody sets it, regardless of credential. A 409 rather
    than a 422: the request is well-formed and allowed, the PRD just is not there yet."""
    r = client.patch(f"/api/prds/{prd}", json={"status": "approved"}, headers=auth)
    assert r.status_code == 409, r.text
    assert _status(client, auth, prd) == "draft"


def test_draft_and_review_are_still_settable(client, auth, prd):
    """Only `approved` is derived. Parking a PRD back in draft is ordinary editing."""
    r = client.patch(f"/api/prds/{prd}", json={"status": "review"}, headers=auth)
    assert r.status_code == 200 and r.json()["status"] == "review"


def test_the_schema_says_approved_is_not_settable(client):
    """`approved` stays in the ENUM on purpose. Removing it makes the dispatcher's
    generic schema check fire first, so an agent gets a bare "invalid status" instead of
    the guard's message naming what is still outstanding — a worse experience for the
    sake of a tidier enum. The description carries the rule instead."""
    from app.mcp_server import TOOLS

    tool = next(t for t in TOOLS if t["name"] == "update_prd")
    status = tool["inputSchema"]["properties"]["status"]
    assert "approved" in status["enum"]
    assert "NOT settable" in status["description"]


def test_re_sending_an_unchanged_approved_status_is_allowed(client, auth, agent_key, prd):
    """A client echoing back the whole object is not trying to approve anything, and
    422-ing that would break every save-the-whole-record caller for no safety gain."""
    for _ in range(len(prd_svc.DIMENSIONS)):
        _answer(client, agent_key, prd)
    assert _status(client, auth, prd) == "approved"

    r = client.patch(f"/api/prds/{prd}", json={"status": "approved", "title": "Renamed"},
                     headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Renamed"


# ---- history is not recomputed ---------------------------------------------------------
def test_an_already_approved_prd_is_never_demoted(client, auth, db_session, prd):
    """PRD-13 and friends were approved under the old manual model and were genuinely
    agreed. Recomputing history would silently retract that — derivation governs
    transitions from here forward, not backwards."""
    row = prd_svc.get_prd(db_session, prd)
    row.status = "approved"          # as if approved before PRD-15 existed
    db_session.commit()

    prd_svc.sync_status(db_session, row)
    assert row.status == "approved", "a pre-PRD-15 approval must survive"


def test_a_prd_nobody_grilled_stays_draft(client, auth, db_session, prd):
    """There is nothing to derive from, so derivation must not invent a transition."""
    prd_svc.sync_status(db_session, prd_svc.get_prd(db_session, prd))
    assert _status(client, auth, prd) == "draft"


@pytest.fixture()
def db_session(client):
    from app.db import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
