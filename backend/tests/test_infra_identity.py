"""Infra identifiers: what the rename may touch, and what it must not (AL-264).

The dividing line is the one PRD-13 arrived at the hard way — **an identifier that
existing data is keyed by is identity, not branding.** Package names and health strings
are labels and rename freely. The Postgres volume key, the compose project name, and the
`POSTGRES_*` defaults are keyed to data that already exists on deployed instances.

These are guard tests, aimed squarely at a future cosmetic sweep (tier 4) doing a
find-and-replace across the repo. Getting any of them "consistent" would orphan a volume
or lock an instance out of its own database, and both failures present as data loss
rather than as a rename bug.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
COMPOSE = (REPO / "docker-compose.yml").read_text()
DEPLOY_DOC = (REPO / "docs" / "deploy.md").read_text()


# ---- renamed: labels, nothing keyed by them ---------------------------------------
def test_health_reports_the_new_service_name(client):
    assert client.get("/health").json()["service"] == "graphban-api"


def test_packages_are_renamed():
    assert 'name = "graphban-api"' in (REPO / "backend" / "pyproject.toml").read_text()
    assert '"name": "graphban-web"' in (REPO / "web" / "package.json").read_text()


def test_the_ephemeral_test_database_is_renamed():
    """Created fresh per CI run and per local Postgres pass, so nothing is keyed by it."""
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text()
    assert "graphban_test" in ci and "agentledger_test" not in ci
    agents = (REPO / "AGENTS.md").read_text()
    assert "graphban_test" in agents and "agentledger_test" not in agents


# ---- frozen: deployed data is keyed by these --------------------------------------
def test_compose_pins_its_project_name():
    """`docker compose` otherwise derives the project name from the DIRECTORY, and names
    volumes `<project>_<volume-key>`. Live that is `agentledger_agentledger_pgdata`, so
    renaming the repo directory would silently create an empty volume and the database
    would read as wiped. Pinning it is what makes the directory safe to rename."""
    assert "\nname: agentledger\n" in COMPOSE, (
        "docker-compose.yml must pin `name:` — without it the compose project name "
        "tracks the directory name and the Postgres volume moves with it"
    )


def test_the_volume_key_is_not_renamed():
    assert "agentledger_pgdata:" in COMPOSE, (
        "renaming the volume key orphans the existing volume; Postgres comes up empty "
        "and it reads as data loss, not as a rename"
    )


@pytest.mark.parametrize("var", ["POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"])
def test_postgres_defaults_are_not_renamed(var):
    """Baked into a volume at initdb. Moving them breaks any self-host that never wrote a
    `.env` — `password authentication failed for user "agentledger"`, which docs/deploy.md
    documents as a deploy-breaking failure."""
    assert f"${{{var}:-agentledger}}" in COMPOSE, f"{var} default must stay `agentledger`"
    assert f"{var}=agentledger" in (REPO / ".env.example").read_text()


# ---- the runbook has to name the SAME frozen identifiers ---------------------------
# Added after the tier-4 cosmetic sweep renamed them in docs/deploy.md while leaving the
# box untouched: the runbook told an operator to `cd ~/graphban` and `psql -U graphban`,
# neither of which exists. Freezing the values in compose is not enough if the document
# people actually follow says something else — the section explaining which identifiers
# must never be renamed had its own identifiers renamed, and nothing noticed for days.

def test_the_runbook_uses_the_real_postgres_role_and_database():
    """Every psql invocation in the runbook must use the frozen role/db. A doc that names
    a role which does not exist fails at the worst moment — mid-recovery."""
    for bad in ("psql -U graphban", "-d graphban "):
        assert bad not in DEPLOY_DOC, (
            f"docs/deploy.md uses {bad!r}; the live role and database are `agentledger` "
            "(frozen at initdb — see the tests above)"
        )
    assert "psql -U agentledger -d agentledger" in DEPLOY_DOC


def test_the_runbook_targets_the_real_deploy_directory():
    """`~/graphban` does not exist on the box. Following it would rsync into a fresh
    directory with no `.env`, and compose would come up on default ports — the exact
    port-conflict failure documented a few lines below it."""
    assert "~/graphban" not in DEPLOY_DOC, (
        "docs/deploy.md points at ~/graphban; the server directory is ~/agentledger"
    )
    assert "ubuntu-srv:~/agentledger/" in DEPLOY_DOC


def test_the_runbook_quotes_the_compose_project_name_correctly():
    """It claims compose pins a project name; that claim has to match the pin, or the
    volume-orphaning explanation around it is nonsense."""
    assert "pins `name: agentledger`" in DEPLOY_DOC
