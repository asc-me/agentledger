"""Retagging a project (PRD-13 / AL-258).

The claim the entire design rests on: changing a project's tag is **one UPDATE on one
row**. Keys are rendered rather than stored, so nothing else moves — not the twelve
columns that hold an entity id, not the audit trail, not code-graph state already pushed
to a cloud tenant, not an in-flight agent claim.

`test_retag_changes_nothing_but_the_project_row` is what turns that from an argument into
a checked fact. It snapshots every other table before and after and requires them
byte-identical.
"""
import pytest
from sqlalchemy import text

from app import tagging
from app.db import SessionLocal, engine
from app.services import keys

# Every table that holds an entity id, per the PRD's reference-surface table, plus the
# entity tables themselves. A retag must leave all of them untouched.
# `events` is handled separately: a retag APPENDS its own audit row, so the invariant
# there is "nothing existing was rewritten", not "nothing changed". That distinction is
# the point — the rejected design rewrote audit rows to keep ids consistent, which is
# exactly the falsification this one avoids.
UNTOUCHED = [
    "items", "requests", "prds", "prd_versions", "memory_shards",
    "links", "code_refs", "assistant_threads", "sync_state", "legacy_entity_keys",
]


def _snapshot(table: str) -> list[tuple]:
    """Every row of `table`, ordered deterministically, for a before/after comparison.

    Columns are CAST to text before ordering: Postgres has no ordering operator for
    `json`, and several of these tables carry JSON columns. Casting also makes the
    comparison insensitive to driver-level type differences between the two engines.
    """
    is_sqlite = engine.url.drivername.startswith("sqlite")
    col_sql = (
        "SELECT name FROM pragma_table_info(:t)"
        if is_sqlite
        else "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
    )
    with engine.connect() as conn:
        cols = sorted(r[0] for r in conn.execute(text(col_sql), {"t": table}).fetchall())
        if not cols:
            return []
        projection = ", ".join(f"CAST({c} AS TEXT)" for c in cols)
        ordering = ", ".join(str(i + 1) for i in range(len(cols)))
        return conn.execute(
            text(f"SELECT {projection} FROM {table} ORDER BY {ordering}")  # noqa: S608
        ).fetchall()


def _project(client, auth) -> dict:
    return client.get("/api/projects", headers=auth).json()[0]


def test_retag_changes_nothing_but_the_project_row(client, auth):
    """THE test this slice exists for."""
    project = _project(client, auth)
    before = {t: _snapshot(t) for t in UNTOUCHED}
    before_events = _snapshot("events")

    r = client.post(f"/api/projects/{project['id']}/retag", json={"tag": "ZZ9"}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["tag"] == "ZZ9"

    for table in UNTOUCHED:
        assert _snapshot(table) == before[table], f"retag modified {table}"

    # The audit trail gains exactly one row — the retag — and nothing already in it is
    # rewritten to match the new tag.
    after_events = _snapshot("events")
    assert len(after_events) == len(before_events) + 1
    assert all(row in after_events for row in before_events), "an existing audit row moved"

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT tag, project_id FROM project_tag_history WHERE project_id = :p"),
            {"p": project["id"]},
        ).fetchall()
    assert [(project["tag"], project["id"])] == [tuple(r) for r in rows]


def test_keys_render_under_the_new_tag_immediately(client, auth):
    project = _project(client, auth)
    before = client.get(f"/api/items?project_id={project['id']}", headers=auth).json()[0]["id"]
    number = tagging.parse(before)[2]

    client.post(f"/api/projects/{project['id']}/retag", json={"tag": "ZZ9"}, headers=auth)

    after = client.get(f"/api/items?project_id={project['id']}", headers=auth).json()[0]["id"]
    assert after == f"ZZ9-{number}", after


def test_keys_rendered_under_the_old_tag_still_resolve(client, auth):
    """The reason history is written in the same transaction as the tag move."""
    project = _project(client, auth)
    old_key = client.get(f"/api/items?project_id={project['id']}", headers=auth).json()[0]["id"]

    client.post(f"/api/projects/{project['id']}/retag", json={"tag": "ZZ9"}, headers=auth)

    r = client.get(f"/api/items/{old_key}", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["id"].startswith("ZZ9-")


def test_retag_is_repeatable_and_every_generation_keeps_resolving(client, auth):
    """Three tags deep. Nothing chains, because each history row points at a project and
    the entity ids never moved in the first place."""
    project = _project(client, auth)
    seen = [client.get(f"/api/items?project_id={project['id']}", headers=auth).json()[0]["id"]]

    for tag in ("ZZ9", "YY8", "XX7"):
        client.post(f"/api/projects/{project['id']}/retag", json={"tag": tag}, headers=auth)
        seen.append(client.get(f"/api/items?project_id={project['id']}", headers=auth).json()[0]["id"])

    for key in seen:
        r = client.get(f"/api/items/{key}", headers=auth)
        assert r.status_code == 200, (key, r.text)
        assert r.json()["id"] == seen[-1], f"{key} must resolve to the same entity"


def test_a_retired_tag_can_never_be_reclaimed(client, auth):
    project = _project(client, auth)
    original = project["tag"]
    client.post(f"/api/projects/{project['id']}/retag", json={"tag": "ZZ9"}, headers=auth)

    back = client.post(
        f"/api/projects/{project['id']}/retag", json={"tag": original}, headers=auth
    )
    assert back.status_code == 422
    assert "previously used" in back.json()["detail"]


def test_retagging_to_the_same_tag_is_a_no_op(client, auth):
    """It must not retire the tag into history and thereby forbid its own current value."""
    project = _project(client, auth)
    r = client.post(
        f"/api/projects/{project['id']}/retag", json={"tag": project["tag"]}, headers=auth
    )
    assert r.status_code == 200 and r.json()["tag"] == project["tag"]

    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM project_tag_history")).scalar() == 0


@pytest.mark.parametrize("bad", ["A", "ABCDE", "1AB", ""])
def test_retag_refuses_an_invalid_tag(client, auth, bad):
    project = _project(client, auth)
    r = client.post(f"/api/projects/{project['id']}/retag", json={"tag": bad}, headers=auth)
    assert r.status_code == 422, r.text


def test_retag_refuses_a_tag_another_project_holds(client, auth):
    a, b = client.get("/api/projects", headers=auth).json()[:2]
    r = client.post(f"/api/projects/{a['id']}/retag", json={"tag": b["tag"]}, headers=auth)
    assert r.status_code == 422
    assert "already in use" in r.json()["detail"]


def test_retag_is_audited(client, auth):
    project = _project(client, auth)
    was = project["tag"]
    client.post(f"/api/projects/{project['id']}/retag", json={"tag": "ZZ9"}, headers=auth)

    events = client.get(f"/api/events?project_id={project['id']}", headers=auth).json()
    rows = events["results"] if isinstance(events, dict) else events
    retag = [e for e in rows if e["action"] == "retag_project"]
    assert retag, "a retag must leave an audit trail"
    assert retag[0]["meta"] == {"from": was, "to": "ZZ9"}


def test_retag_requires_write_access(client, auth):
    """Same gate as any other project setting — no new permission tier."""
    project = _project(client, auth)
    other = client.post(
        "/api/auth/login", json={"email": "kate@ascme-labs.com", "password": "graphban"}
    )
    if other.status_code != 200:
        pytest.skip("seed has no read-only user to assert with")
    headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    r = client.post(f"/api/projects/{project['id']}/retag", json={"tag": "ZZ9"}, headers=headers)
    assert r.status_code in (403, 404), r.text


def test_in_flight_claims_survive_a_retag(client, auth):
    """An agent holding a lease keeps working: the id it holds never moved, and the key
    it quotes resolves through history."""
    project = _project(client, auth)
    listed = client.get(f"/api/items?project_id={project['id']}", headers=auth).json()[0]["id"]

    with SessionLocal() as db:
        from app.models import Item
        from app.services import items as items_svc

        stored_id = keys.resolve_item(db, listed)
        row = db.get(Item, stored_id)
        row.status, row.claimed_by, row.claimed_at = "backlog", None, None
        db.commit()
        assert items_svc.claim_item(db, stored_id, "agent-1") is not None

    client.post(f"/api/projects/{project['id']}/retag", json={"tag": "ZZ9"}, headers=auth)

    api_key = client.post(
        "/api/api-keys", json={"name": "leaseholder", "scopes": ["read", "write"]}, headers=auth
    ).json()["plaintext"]
    r = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "heartbeat", "arguments": {"id": listed, "agent_id": "agent-1"}}},
        headers={"X-API-Key": api_key},
    )
    assert r.status_code == 200 and r.json()["result"].get("isError") is not True, r.text
