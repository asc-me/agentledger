"""First-run provisioning (AL-283 / PRD-14 D3).

Issuing the first credential is the purest AUTHORITY gate there is, and it was the one
thing blocking a zero-browser install: signup and key minting are both JWT/UI-only, and
an agent cannot bootstrap itself into existing. PRD-14's answer is not to relax the gate
but to satisfy it out of band — an operator runs a script on the box they already own.

So the tests that matter are the REFUSALS. A bootstrap path that mints a credential
without authenticating anyone is only safe where "no users yet" really does imply "the
person running this owns the deployment", and these pin every case where it doesn't.
"""
import pytest
from sqlalchemy import select

from app import bootstrap
from app.models import ApiKey, Membership, Project, User


@pytest.fixture()
def db(client):
    """A migrated but EMPTY instance — the only fixture here that wants one, since
    provisioning is defined by "this database has no users".

    `client` seeds the prototype dataset, so every table is cleared in REVERSE
    dependency order. Deleting a hand-picked few (users, projects, keys) passes on
    SQLite and fails on Postgres, which enforces foreign keys immediately: seeded items
    still reference `projects.core`. Let the metadata supply the order rather than
    guessing it."""
    from app.db import Base, SessionLocal

    session = SessionLocal()
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    try:
        yield session
    finally:
        session.close()


# ---- the happy path -----------------------------------------------------------------
def test_provisioning_yields_a_working_agent_credential(client, db, monkeypatch):
    monkeypatch.setattr(bootstrap.settings, "seed_on_start", False)
    out = bootstrap.provision(db, project_name="My Repo")
    assert out["provisioned"] is True

    # The credential is the deliverable: it must authenticate MCP with no further setup.
    r = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "get_context", "arguments": {}}},
        headers={"X-API-Key": out["api_key"]},
    )
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result.get("isError") is not True, result
    assert out["project_id"] in result["structuredContent"]["writable_projects"]


def test_the_operator_can_sign_in_with_what_was_printed(client, db, monkeypatch):
    """An account nobody can log into is a dead end — the human is the reviewer at the
    quality gates eventually, so the printed credential has to actually work."""
    monkeypatch.setattr(bootstrap.settings, "seed_on_start", False)
    out = bootstrap.provision(db, project_name="My Repo", email="me@example.com")
    r = client.post("/api/auth/login",
                    json={"email": "me@example.com", "password": out["password"]})
    assert r.status_code == 200, r.text


def test_the_operator_owns_the_project(client, db, monkeypatch):
    """Without the owner Membership the project would be invisible to its own creator."""
    monkeypatch.setattr(bootstrap.settings, "seed_on_start", False)
    out = bootstrap.provision(db, project_name="My Repo")
    m = db.scalars(select(Membership).where(Membership.project_id == out["project_id"])).all()
    assert [(x.role, x.access) for x in m] == [("owner", "write")]


def test_the_tag_is_derived_and_valid(client, db, monkeypatch):
    """PRD-13's grammar is satisfied for free — no operator has to invent a tag."""
    from app import tagging

    monkeypatch.setattr(bootstrap.settings, "seed_on_start", False)
    out = bootstrap.provision(db, project_name="Graphban Web")
    # `validate` RAISES on a bad tag and returns the normalized value, so compare against
    # it — an `is None or True` style assertion here would be a tautology that can't fail.
    assert tagging.validate(out["project_tag"]) == out["project_tag"] == "GW"


def test_a_generated_password_is_not_guessable(client, db, monkeypatch):
    """Decided by building it (the item was high-fidelity for this reason): a random
    password beats passwordless-local, because a box that later gets exposed shouldn't
    have an open door on it."""
    monkeypatch.setattr(bootstrap.settings, "seed_on_start", False)
    first = bootstrap.provision(db, project_name="A")["password"]
    assert len(first) >= 20
    assert first not in ("graphban", "password", "admin", "operator@localhost")


# ---- the refusals -------------------------------------------------------------------
def test_a_second_run_changes_nothing(client, db, monkeypatch):
    """Re-running must not mint a second operator or a second credential."""
    monkeypatch.setattr(bootstrap.settings, "seed_on_start", False)
    bootstrap.provision(db, project_name="My Repo")
    before = len(db.scalars(select(ApiKey)).all()), len(db.scalars(select(User)).all())

    again = bootstrap.provision(db, project_name="My Repo")
    assert again["provisioned"] is False
    assert "already has users" in again["reason"]
    assert (len(db.scalars(select(ApiKey)).all()), len(db.scalars(select(User)).all())) == before


def test_it_refuses_on_a_hosted_instance(client, db, monkeypatch):
    """The one that would be a security hole. On a multi-tenant deployment, "no users
    yet" says nothing about whether the caller owns it."""
    monkeypatch.setattr(bootstrap.settings, "hosted_mode", True)
    with pytest.raises(bootstrap.BootstrapRefused, match="HOSTED"):
        bootstrap.provision(db, project_name="My Repo")
    assert db.scalars(select(User)).all() == []


def test_it_refuses_when_seeding_is_on(client, db, monkeypatch):
    """Both key off zero users and seeding runs during lifespan startup, so seeding wins
    the race and the operator silently gets the prototype dataset instead of their own
    project. Refuse rather than pick one."""
    monkeypatch.setattr(bootstrap.settings, "hosted_mode", False)
    monkeypatch.setattr(bootstrap.settings, "seed_on_start", True)
    with pytest.raises(bootstrap.BootstrapRefused, match="SEED_ON_START"):
        bootstrap.provision(db, project_name="My Repo")
    assert db.scalars(select(User)).all() == []


def test_the_refusals_are_checked_before_anything_is_written(client, db, monkeypatch):
    """A refusal must leave NO partial state — half a provisioned instance is worse than
    none, because the zero-users guard would then consider it already set up."""
    monkeypatch.setattr(bootstrap.settings, "hosted_mode", True)
    with pytest.raises(bootstrap.BootstrapRefused):
        bootstrap.provision(db, project_name="My Repo")
    assert db.scalars(select(User)).all() == []
    assert db.scalars(select(Project)).all() == []
    assert db.scalars(select(ApiKey)).all() == []
