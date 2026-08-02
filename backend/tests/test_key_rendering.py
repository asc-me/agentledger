"""Every surface renders keys; none emits a stored id (PRD-13 / AL-256).

A user-visible key is rendered from the project's *current* tag. The stored id is frozen
at issue time, so on a renamed project the two differ — and any surface still emitting
the stored id would hand a caller a string that looks like a key but encodes a tag the
project no longer has. Worse for agents than for humans: it goes into memory and PR
titles and outlives the rename by months.

The sweep below checks **identifier-shaped fields only**. Prose is deliberately exempt:
PRD bodies, version snapshots, and shard text keep whatever was typed, and resolution
handles them. Rewriting them would falsify a frozen record to fix a cosmetic mismatch.
"""
import json

import pytest
from sqlalchemy import text

from app import tagging
from app.db import SessionLocal, engine

# Fields that hold an entity reference anywhere in a response, at any depth.
_ID_FIELDS = {
    "id", "prd_id", "item_id", "linked_to", "linked", "a", "b",
    "ref_id", "entity_id", "target_id", "item_ids", "unblocks", "blocked_by",
}


def _identifier_values(node, field=None):
    """Every value sitting in an identifier-shaped field, at any depth."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _identifier_values(v, k)
    elif isinstance(node, list):
        for v in node:
            yield from _identifier_values(v, field)
    elif isinstance(node, str) and field in _ID_FIELDS:
        yield node


@pytest.fixture()
def stored_ids(client):
    """Every frozen id in the database — none of these may appear in a response."""
    with SessionLocal() as db:
        from app.models import Item, Prd, Request

        return {
            row.id
            for model in (Item, Request, Prd)
            for row in db.query(model).all()
        }


def _retag_core(client, auth) -> str:
    """Move `core` off its derived tag so stored id and rendered key must differ."""
    from datetime import datetime, timezone

    project_id = client.get("/api/projects", headers=auth).json()[0]["id"]
    with engine.begin() as conn:
        old = conn.execute(
            text("SELECT tag FROM projects WHERE id = :i"), {"i": project_id}
        ).scalar()
        conn.execute(
            text("INSERT INTO project_tag_history (tag, project_id, held_until)"
                 " VALUES (:t, :p, :u)"),
            {"t": old, "p": project_id, "u": datetime.now(timezone.utc)},
        )
        conn.execute(text("UPDATE projects SET tag = 'ZZ9' WHERE id = :i"), {"i": project_id})
    return project_id


REST_SURFACES = [
    "/api/items?project_id=core",
    "/api/requests?project_id=core",
    "/api/prds?project_id=core",
    "/api/memory/shards?project_id=core",
    "/api/links?project_id=core",
    "/api/dashboard?project_id=core",
    "/api/events?project_id=core",
    "/api/roadmap?project_id=core",
]


@pytest.mark.parametrize("path", REST_SURFACES)
def test_no_rest_surface_emits_a_stored_id(client, auth, stored_ids, path):
    _retag_core(client, auth)
    # A 404 here means the path is wrong, not that the surface is exempt — skipping on
    # it would silently drop a surface from the sweep and read as "covered".
    r = client.get(path, headers=auth)
    assert r.status_code == 200, (path, r.text)

    leaked = sorted(set(_identifier_values(r.json())) & stored_ids)
    assert not leaked, f"{path} emitted stored id(s) instead of rendered keys: {leaked}"


def test_item_detail_and_patch_render(client, auth, stored_ids):
    _retag_core(client, auth)
    listed = client.get("/api/items?project_id=core", headers=auth).json()[0]["id"]
    assert listed.startswith("ZZ9-"), listed

    detail = client.get(f"/api/items/{listed}", headers=auth).json()
    assert not set(_identifier_values(detail)) & stored_ids
    patched = client.patch(f"/api/items/{listed}", json={"effort": 3}, headers=auth).json()
    assert patched["id"] == listed


def test_reference_fields_render_too(client, auth):
    """The back door: an item's own key can look right while `prd_id` still carries the
    frozen id. Reference fields have to render or a retag leaks through them."""
    _retag_core(client, auth)
    prds = client.get("/api/prds?project_id=core", headers=auth).json()
    linked = [k for p in prds for k in p["linked"]]
    assert linked, "seed must link at least one item to a PRD"
    for key in linked:
        assert tagging.parse(key) == ("ZZ9", "item", tagging.parse(key)[2])


MCP_TOOLS = [
    ("get_backlog", {}),
    ("search_items", {"query": ""}),
    ("list_projects", {}),
    ("get_context", {}),
    ("search_memory", {"query": "memory"}),
]


@pytest.mark.parametrize("tool,args", MCP_TOOLS)
def test_no_mcp_tool_emits_a_stored_id(client, auth, stored_ids, tool, args):
    """Agents are the worse case: a leaked key lands in memory and outlives the rename."""
    _retag_core(client, auth)
    api_key = client.post(
        "/api/api-keys", json={"name": "render", "scopes": ["read"]}, headers=auth
    ).json()["plaintext"]

    r = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": tool, "arguments": args}},
        headers={"X-API-Key": api_key},
    )
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result.get("isError") is not True, (tool, result)

    payload = json.loads(result["content"][0]["text"])
    leaked = sorted(set(_identifier_values(payload)) & stored_ids)
    assert not leaked, f"{tool} emitted stored id(s): {leaked}"


def test_prose_is_deliberately_not_rewritten(client, auth):
    """The other half of the contract. A frozen snapshot keeps whatever was typed —
    rewriting it to match today's tag would falsify the record versioning exists to
    protect. Resolution is what makes those stale strings still work."""
    _retag_core(client, auth)
    with SessionLocal() as db:
        from app.models import Prd

        prd = db.query(Prd).first()
        prd.body = "This references CP-1 and AL-08 in prose."
        db.commit()
        prd_key = prd.key

    body = client.get(f"/api/prds/{prd_key}", headers=auth).json()["body"]
    assert "AL-08" in body and "CP-1" in body
