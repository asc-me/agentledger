"""`graphban link` records the link where the SERVER reads it (AL-281 / PRD-14 D5).

Two records of "is this instance linked to a cloud org" existed and only one was
server-visible. The CLI wrote `~/.graphban/config.json`; `code_sync.link_status()`
resolves the `sync_link` row then the env link and never consults that file. So a
CLI-linked box reported `linked: false` to everything server-side.

That is not cosmetic. AL-284 gates agent-side project creation on exactly this
predicate, so the stale answer makes an authority gate **fail open** — and it fails
open precisely on the instances that ARE linked to an org, which is the case the gate
exists for. These tests pin the direction of that failure.
"""
import pytest

from app.services import code_sync


@pytest.fixture()
def cli_env(tmp_path, monkeypatch):
    """Point the CLI's config at a temp file so a real operator config is never touched."""
    from app import cli

    monkeypatch.setenv("GRAPHBAN_CONFIG", str(tmp_path / "config.json"))
    return cli


def _args(**kw):
    return type("Args", (), {"cloud_url": None, "api_key": None, "project": None,
                             "org": None, **kw})()


def test_linking_via_the_cli_is_visible_to_the_server(client, cli_env):
    """The regression. Before AL-281 this asserted False."""
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        assert code_sync.link_status(db)["linked"] is False
    finally:
        db.close()

    cli_env.cmd_link(_args(cloud_url="https://cloud.example/", api_key="gb_sk_" + "0" * 40,
                           project="core"))

    db = SessionLocal()
    try:
        status = code_sync.link_status(db)
        assert status["linked"] is True, "a CLI-linked instance must not read as unlinked"
        assert status["cloud_url"] == "https://cloud.example"
        assert status["credential_set"] is True
    finally:
        db.close()


def test_the_config_file_is_still_written(client, cli_env, tmp_path):
    """The DB row is what the server reads; the file is what the CLI's own commands read.
    Both, not either."""
    cli_env.cmd_link(_args(cloud_url="https://cloud.example/", api_key="gb_sk_" + "1" * 40))
    cfg = cli_env.load_config()
    assert cfg["cloud_url"] == "https://cloud.example"
    assert cfg["api_key"].startswith("gb_sk_")
    assert (tmp_path / "config.json").stat().st_mode & 0o777 == 0o600


def test_relinking_does_not_blank_the_org_label(client, cli_env):
    """`set_link` overwrites the org label and the label is the UI's to set. A CLI
    re-link that silently cleared it would look like the UI losing data."""
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        code_sync.set_link(db, cloud_url="https://cloud.example", api_key="k", org="Acme Corp")
    finally:
        db.close()

    cli_env.cmd_link(_args(cloud_url="https://cloud.example/", api_key="gb_sk_" + "2" * 40))

    db = SessionLocal()
    try:
        assert code_sync.get_link(db).org == "Acme Corp"
    finally:
        db.close()


def test_an_explicit_org_label_wins(client, cli_env):
    from app.db import SessionLocal

    cli_env.cmd_link(_args(cloud_url="https://cloud.example/", api_key="gb_sk_" + "3" * 40,
                           org="Renamed"))
    db = SessionLocal()
    try:
        assert code_sync.get_link(db).org == "Renamed"
    finally:
        db.close()


def test_a_failed_db_write_does_not_report_success(client, cli_env, monkeypatch):
    """The fail-open case, made loud. If the row can't be written the command must exit
    non-zero — never print 'Linked →' while the server still reads unlinked."""
    def boom(*a, **kw):
        raise RuntimeError("database is gone")

    monkeypatch.setattr(code_sync, "set_link", boom)
    with pytest.raises(SystemExit) as excinfo:
        cli_env.cmd_link(_args(cloud_url="https://cloud.example/", api_key="gb_sk_" + "4" * 40))
    assert "could not record the link" in str(excinfo.value)


def test_status_warns_when_the_two_records_disagree(client, cli_env, capsys):
    """Belt and braces: if they ever diverge again, `status` says so instead of showing
    a confident, wrong answer."""
    from app.db import SessionLocal

    cli_env.cmd_link(_args(cloud_url="https://cloud.example/", api_key="gb_sk_" + "5" * 40))
    db = SessionLocal()
    try:
        code_sync.set_link(db, cloud_url="https://elsewhere.example", api_key="k")
    finally:
        db.close()

    capsys.readouterr()
    cli_env.cmd_status(_args(project="core"))
    out = capsys.readouterr().out
    assert "WARNING" in out and "elsewhere.example" in out, out
