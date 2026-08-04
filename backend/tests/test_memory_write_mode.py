"""Memory write modes: the agent write→read loop (AL-280 / PRD-14 D1).

The bug this closes: an agent's `add_memory` landed as `candidate`, `search_memory`
returned only `published`, and NO configuration made the round trip work. Setting
`memory_auto_accept: true` didn't help, because `_score_shard` only suggests `accept` on
`support >= 2` or corroboration against an already-published shard — a first-of-its-kind
fact always scored `review`. Under the default stub embedder, rephrasings of one fact
score ~0.4 similarity, far under every threshold, so the corroboration path never fired
offline at all.

The tests that matter here are the round trips: write, then read back through the same
API an agent would use, with no human action and no `include_candidates` escape hatch.
"""
import pytest

from app.services import memory as mem_svc


def _mcp(client, api_key: str, tool: str, args: dict):
    import json

    r = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": tool, "arguments": args}},
        headers={"X-API-Key": api_key},
    )
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result.get("isError") is not True, result
    return json.loads(result["content"][0]["text"])


@pytest.fixture()
def project(client, auth):
    """A fresh project + a write-scoped agent key pinned to it."""
    r = client.post("/api/projects", json={"name": "Write Mode", "tag": "WM"}, headers=auth)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = client.post("/api/api-keys",
                    json={"name": "agent", "project_id": pid, "scopes": ["read", "write"]},
                    headers=auth)
    assert r.status_code == 201, r.text
    return pid, r.json()["plaintext"]


def _set_mode(client, auth, pid, mode, **extra):
    r = client.patch(f"/api/projects/{pid}",
                     json={"memory_write_mode": mode, **extra}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


# ---- the loop -----------------------------------------------------------------------
def test_trusted_closes_the_write_read_loop(client, auth, project):
    """The whole point. One novel fact, written and read back by the agent alone."""
    pid, key = project
    _set_mode(client, auth, pid, "trusted")

    written = _mcp(client, key, "add_memory",
                   {"text": "Deploys must pass GIT_SHA through to compose."})
    assert written["status"] == "published", written

    found = _mcp(client, key, "search_memory", {"query": "GIT_SHA deploy"})
    assert [r["id"] for r in found["results"]] == [written["id"]], found


def test_review_keeps_a_novel_write_invisible(client, auth, project):
    """The AL-49 boundary, unchanged and still the default for new projects."""
    pid, key = project
    row = next(p for p in client.get("/api/projects", headers=auth).json() if p["id"] == pid)
    assert row["memory_write_mode"] == "review"

    written = _mcp(client, key, "add_memory", {"text": "A novel fact nobody has vouched for."})
    assert written["status"] == "candidate", written
    assert _mcp(client, key, "search_memory", {"query": "novel fact"})["results"] == []


def test_auto_still_refuses_a_novel_write(client, auth, project):
    """`auto` is what `memory_auto_accept: true` meant, and it must not become a synonym
    for `trusted` — an uncorroborated fact stays a candidate under it."""
    pid, key = project
    _set_mode(client, auth, pid, "auto")

    written = _mcp(client, key, "add_memory", {"text": "An uncorroborated novel claim."})
    assert written["status"] == "candidate", written


# ---- vetoes still run under trusted --------------------------------------------------
def test_trusted_still_rejects_a_near_duplicate(client, auth, project):
    """`auto_reject` is orthogonal to the mode. Without this, a trusted project fills up
    with restatements of one fact and the store degrades into noise."""
    pid, key = project
    _set_mode(client, auth, pid, "trusted", memory_auto_reject=True)

    text = "The Postgres volume key is frozen and must never be renamed."
    first = _mcp(client, key, "add_memory", {"text": text})
    assert first["status"] == "published"

    dup = _mcp(client, key, "add_memory", {"text": text})
    assert dup["status"] == "rejected", dup
    assert _mcp(client, key, "search_memory", {"query": "volume key"})["returned"] == 1


def test_trusted_without_auto_reject_publishes_the_duplicate(client, auth, project):
    """The veto is a switch, not a law — turning it off is allowed and observable, which
    is what makes the previous test meaningful rather than incidental."""
    pid, key = project
    _set_mode(client, auth, pid, "trusted", memory_auto_reject=False)

    text = "An exactly repeated note."
    assert _mcp(client, key, "add_memory", {"text": text})["status"] == "published"
    assert _mcp(client, key, "add_memory", {"text": text})["status"] == "published"


# ---- provenance ----------------------------------------------------------------------
def test_a_trusted_publish_is_labeled_and_undoable(client, auth, project):
    """Nothing human or judge assessed these, so a human arriving later needs to find
    exactly this set. `scoring_source` carries the provenance and puts them in the
    auto-actions lane; AL-282 builds on the same label."""
    pid, key = project
    _set_mode(client, auth, pid, "trusted")
    written = _mcp(client, key, "add_memory", {"text": "Published with nobody watching."})

    lane = client.get(f"/api/memory/auto-actions?project_id={pid}", headers=auth).json()
    assert [s["id"] for s in lane] == [written["id"]], lane
    assert lane[0]["scoring_source"] == "trusted"

    r = client.post(f"/api/memory/shards/{written['id']}/undo-auto", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "candidate"


# ---- migration intent ----------------------------------------------------------------
def test_the_mode_is_validated_at_the_boundary(client, auth, project):
    """A typo must 422 rather than silently reverting the project to `review`."""
    pid, _ = project
    r = client.patch(f"/api/projects/{pid}", json={"memory_write_mode": "trused"}, headers=auth)
    assert r.status_code == 422, r.text


def test_an_unknown_stored_mode_falls_back_to_review(client, auth, project):
    """Defence in depth for a hand-edited row: an unrecognized mode must fail CLOSED to
    the human boundary, never open to publishing."""
    from app.db import SessionLocal
    from app.models import Project

    pid, key = project
    db = SessionLocal()
    try:
        db.get(Project, pid).memory_write_mode = "nonsense"
        db.commit()
        assert mem_svc._triage_prefs(db, pid)[0] == "review"
    finally:
        db.close()

    assert _mcp(client, key, "add_memory", {"text": "Should stay a candidate."})["status"] == "candidate"


def test_project_less_shards_default_to_review():
    """A shard with no project has no owner to have chosen a mode."""
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        assert mem_svc._triage_prefs(db, None) == ("review", True, False)
    finally:
        db.close()
