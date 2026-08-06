"""Key resolution across a retag (PRD-13 / AL-257).

`GRPH-12` is a *rendering* of (project tag, kind, number), not a stored value, so every
path that accepts an id from outside has to translate — and keep translating keys that
were rendered under a tag the project no longer holds.

The fixture that matters is `retagged`. A missed resolution call site is completely
invisible on a fresh instance: nothing has ever been renamed, so the stored id and the
rendered key are the same string and every test passes. These tests move a tag first
and only then exercise the API, which is the only arrangement that can catch it.

AL-258 owns the real retag; `_retag` here does exactly what it will do — move the tag,
record the old one in history — so these tests pin the contract that slice must meet.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.db import SessionLocal, engine
from app.services import keys


def _tag(project_id: str) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT tag FROM projects WHERE id = :i"), {"i": project_id}
        ).scalar()


def _retag(project_id: str, new_tag: str) -> str:
    """What AL-258 will do: move the tag, append the old one to history. Returns the old."""
    old = _tag(project_id)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO project_tag_history (tag, project_id, held_until)"
                " VALUES (:t, :p, :u)"
            ),
            {"t": old, "p": project_id, "u": datetime.now(timezone.utc)},
        )
        conn.execute(
            text("UPDATE projects SET tag = :t WHERE id = :i"), {"t": new_tag, "i": project_id}
        )
    return old


@pytest.fixture()
def retagged(client, auth):
    """A seeded project whose tag has moved, plus one of its items.

    Yields (project_id, old_key, new_key, stored_id) — the three strings that must all
    resolve to the same entity, and the stored id that must never change.
    """
    # Responses render the key now (AL-256), so the API no longer hands back a stored
    # id — resolve to get one.
    rendered = client.get("/api/items?project_id=core", headers=auth).json()[0]["id"]

    with SessionLocal() as db:
        from app.models import Item

        stored_id = keys.resolve_item(db, rendered)
        row = db.get(Item, stored_id)
        project_id, number = row.project_id, row.number

    old_tag = _retag(project_id, "ZZ9")
    yield project_id, f"{old_tag}-{number}", f"ZZ9-{number}", stored_id


# ---- the resolver itself ----------------------------------------------------------
def test_resolves_a_current_form_key(client, auth):
    rendered = client.get("/api/items?project_id=core", headers=auth).json()[0]["id"]
    with SessionLocal() as db:
        from app.models import Item

        row = db.get(Item, keys.resolve_item(db, rendered))
        assert keys.resolve_item(db, f"{_tag(row.project_id)}-{row.number}") == row.id


def test_resolves_a_key_rendered_under_a_retired_tag(retagged):
    _project_id, old_key, new_key, stored_id = retagged
    with SessionLocal() as db:
        assert keys.resolve_item(db, new_key) == stored_id, "current tag must resolve"
        assert keys.resolve_item(db, old_key) == stored_id, "retired tag must still resolve"


def test_resolves_a_stored_id_directly(client, auth):
    """The identity rung. Internal callers and anything the grammar can't express.

    The stored id has to come from the database, not the API — output renders now, so a
    response never contains one."""
    with SessionLocal() as db:
        from app.models import Item

        stored_id = db.query(Item).first().id
        assert keys.resolve_item(db, stored_id) == stored_id


def test_resolves_legacy_request_and_prd_ids(client, auth):
    """`R-` and `PRD-` were entity-kind markers, not project tags, so tag history can
    never express them — this is precisely why the legacy table has to exist."""
    with SessionLocal() as db:
        from app.models import Prd, Request

        req_id = db.query(Request).first().id   # e.g. R-33 — a pre-tag stored id
        prd_id = db.query(Prd).first().id       # e.g. PRD-1
        assert keys.resolve_request(db, req_id) == req_id
        assert keys.resolve_prd(db, prd_id) == prd_id


def test_kind_is_enforced_so_numbers_cannot_cross_entities(client, auth):
    """Asking for a PRD must never return an item that happens to share a number."""
    with SessionLocal() as db:
        from app.models import Item

        stored_id = db.query(Item).first().id
        assert keys.resolve_item(db, stored_id) == stored_id
        assert keys.resolve_prd(db, stored_id) is None
        assert keys.resolve_request(db, stored_id) is None


@pytest.mark.parametrize("junk", ["", "   ", "NOPE-1", "ZZ9-99999", "not a key", "AL-", "---"])
def test_unknown_keys_resolve_to_none(client, auth, junk):
    with SessionLocal() as db:
        assert keys.resolve_item(db, junk) is None


# ---- read paths across a retag ----------------------------------------------------
def test_rest_get_accepts_a_pre_retag_key(client, auth, retagged):
    _p, old_key, new_key, stored_id = retagged
    for key in (old_key, new_key, stored_id):
        r = client.get(f"/api/items/{key}", headers=auth)
        assert r.status_code == 200, (key, r.text)
        # Every accepted form resolves to the same entity and comes back rendered under
        # the CURRENT tag — never as the stored id it was reached by.
        assert r.json()["id"] == new_key


def test_unknown_key_is_404_not_500(client, auth):
    """A malformed or unknown key is 'no such entity', not a crash."""
    r = client.get("/api/items/NOPE-4242", headers=auth)
    assert r.status_code == 404, r.text


def test_mcp_get_item_details_accepts_a_pre_retag_key(client, retagged):
    _p, old_key, _new, stored_id = retagged  # noqa: F841 — _new is asserted below
    key = client.post(
        "/api/api-keys", json={"name": "resolver", "scopes": ["read"]},
        headers=_login(client),
    ).json()["plaintext"]

    r = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "get_item_details", "arguments": {"id": old_key}}},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "error" not in body, body
    assert body["result"].get("isError") is not True, body["result"]
    # The old key RESOLVED — that is what this test is about. The response renders the
    # CURRENT key, like every other read surface; asserting the stored id here pinned
    # the one place that didn't (fixed alongside this change).
    import json as _json
    details = _json.loads(body["result"]["content"][0]["text"])
    assert details["id"] == _new, details["id"]
    assert details["id"] != stored_id


# ---- WRITE paths across a retag ---------------------------------------------------
# The half a reads-only audit would miss. An agent that claimed AL-12 keeps calling
# heartbeat with AL-12; if writes don't resolve, its lease silently breaks at retag.
def test_rest_patch_accepts_a_pre_retag_key(client, auth, retagged):
    _p, old_key, _new, _stored = retagged
    r = client.patch(f"/api/items/{old_key}", json={"title": "renamed via old key"}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == _new  # written via the retired key, returned under the new tag
    assert r.json()["title"] == "renamed via old key"


def test_claim_heartbeat_and_release_accept_a_pre_retag_key(client, retagged):
    """The lease lifecycle end to end, driven entirely by a key that no longer renders."""
    _p, old_key, _new, stored_id = retagged  # noqa: F841 — _new is asserted below
    api_key = client.post(
        "/api/api-keys", json={"name": "leaser", "scopes": ["read", "write"]},
        headers=_login(client),
    ).json()["plaintext"]

    def call(tool, args):
        r = client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": tool, "arguments": args}},
            headers={"X-API-Key": api_key},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "error" not in body, body
        # A refused tool call is result.isError, NOT a JSON-RPC error — asserting only
        # the envelope let this pass with resolution disabled.
        assert body["result"].get("isError") is not True, (tool, body["result"])
        return body

    # heartbeat requires an existing lease, so establish one against the STORED id —
    # the point of the test is that the old key drives the calls that follow.
    with SessionLocal() as db:
        from app.models import Item
        from app.services import items as items_svc

        row = db.get(Item, stored_id)  # the seed item may already be in flight
        row.status, row.claimed_by, row.claimed_at = "backlog", None, None
        db.commit()
        assert items_svc.claim_item(db, stored_id, "agent-1") is not None

    call("update_item", {"id": old_key, "status": "next"})
    call("heartbeat", {"id": old_key, "agent_id": "agent-1"})
    call("release_item", {"id": old_key, "agent_id": "agent-1"})

    # Assert the WRITES LANDED, not merely that the calls returned.
    with SessionLocal() as db:
        from app.models import Item

        row = db.get(Item, stored_id)
        assert row is not None, "the stored id must not have moved"
        assert row.claimed_by is None, "release_item must have cleared the lease"
        assert row.status == "next"


def test_reorder_accepts_pre_retag_keys(client, auth, retagged):
    """The SPA sends back whatever it was given, so drag-reorder is a write path too."""
    _p, old_key, _new, _stored = retagged
    old_tag = old_key.split("-")[0]

    # Pick an item that is NOT already first, so "moved to position 0" actually proves
    # something — reorder returns the whole list either way, so a membership assertion
    # would pass even when the reorder silently did nothing.
    items = client.get("/api/items?project_id=core", headers=auth).json()
    with SessionLocal() as db:
        from app.models import Item

        target_id = keys.resolve_item(db, items[-1]["id"])  # output renders now (AL-256)
        row = db.get(Item, target_id)
        assert row.sort_order != 0, "need an item that is not already at position 0"
        target_key = f"{old_tag}-{row.number}"

    r = client.patch("/api/items/reorder", json={"ordered_ids": [target_key]}, headers=auth)
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        from app.models import Item

        assert db.get(Item, target_id).sort_order == 0


def test_retag_never_moves_a_stored_id(client, auth, retagged):
    """The claim the whole design rests on."""
    project_id, _old, _new, stored_id = retagged
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id FROM items WHERE project_id = :p"), {"p": project_id}
        ).fetchall()
    assert stored_id in {r[0] for r in rows}


def _login(client) -> dict:
    r = client.post(
        "/api/auth/login", json={"email": "alex@ascme-labs.com", "password": "graphban"}
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
