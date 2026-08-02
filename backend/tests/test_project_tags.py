"""Project tags + per-entity numbers (PRD-13 / AL-255).

Two halves. The first is the tag grammar itself, which is pure and cheap to pin. The
second runs the *migration* against seeded data, because the backfill is the part that
can silently do nothing: the normal test path migrates an EMPTY database and then seeds
it, so a broken backfill would never be reached. That is exactly how AL-248 shipped a
no-op migration, so this suite downgrades and re-upgrades a populated database instead
of trusting that "the migration ran".
"""
import pytest
from sqlalchemy import text

from app import tagging
from app.db import engine

_IS_SQLITE = engine.url.drivername.startswith("sqlite")


# ---- the grammar -----------------------------------------------------------------
@pytest.mark.parametrize("tag", ["AL", "GB", "GRPH", "A1", "X9Z2"])
def test_validate_accepts_the_documented_shape(tag):
    assert tagging.validate(tag) == tag


@pytest.mark.parametrize("bad", ["A", "ABCDE", "1AB", "A-B", "", "  ", "A B"])
def test_validate_rejects_everything_else(bad):
    with pytest.raises(ValueError, match="tag must be"):
        tagging.validate(bad)


def test_validate_normalizes_case():
    """Tags are stored uppercase — that is what lets a plain UNIQUE constraint express
    case-insensitive uniqueness on both engines, with no functional index."""
    assert tagging.validate("grph") == "GRPH"
    assert tagging.validate("  al  ") == "AL"


@pytest.mark.parametrize(
    "name,expected",
    [
        ("AgentLedger", "AL"),      # camelCase -> initials
        ("glyphy-board", "GB"),     # hyphenated -> initials
        ("Super-Arc", "SA"),
        ("SolaScriptura", "SS"),
        ("Core Platform", "CP"),
        ("Republiq", "REPU"),       # single token -> leading characters
        ("Infra", "INFR"),
        ("MCPBridge", "MB"),        # acronym stays one token
    ],
)
def test_derive_from_project_names(name, expected):
    assert tagging.derive(name) == expected


@pytest.mark.parametrize("name", ["", "   ", "1", "123", "x", "!!!", "9lives", "a-b-c-d-e-f"])
def test_derive_always_returns_something_valid(name):
    """Derivation must never reject. Every project needs a tag, and an agent
    bootstrapping one shouldn't fail over a missing four-character string."""
    assert tagging.validate(tagging.derive(name))


def test_variants_de_collide_inside_the_length_rule():
    got = [v for v, _ in zip(tagging.variants("GB"), range(4))]
    assert got == ["GB", "GB2", "GB3", "GB4"]
    # A full-length base still has to stay within four characters.
    assert all(len(v) <= 4 for v, _ in zip(tagging.variants("GRPH"), range(20)))


def test_render_covers_all_three_kinds():
    assert tagging.render("GRPH", "item", 12) == "GRPH-12"
    assert tagging.render("GRPH", "request", 33) == "GRPH-R33"
    assert tagging.render("GRPH", "prd", 4) == "GRPH-P4"


@pytest.mark.parametrize("kind,number", [("item", 12), ("request", 33), ("prd", 4)])
def test_parse_round_trips_render(kind, number):
    assert tagging.parse(tagging.render("GRPH", kind, number)) == ("GRPH", kind, number)


def test_parse_is_unambiguous_for_a_tag_containing_digits():
    """The first hyphen delimits the tag, so `A1-R12` is request 12 of project A1 —
    not some parse of 'A' + '1-R12'."""
    assert tagging.parse("A1-R12") == ("A1", "request", 12)
    assert tagging.parse("A1-12") == ("A1", "item", 12)


@pytest.mark.parametrize("junk", ["", "AL", "AL-", "-12", "A-12", "ABCDE-12", "AL-X12", "AL-1.2"])
def test_parse_returns_none_rather_than_raising(junk):
    """None means 'not a current-form key, try the other resolution sources' — it is a
    routing signal for AL-257, not an error."""
    assert tagging.parse(junk) is None


def test_legacy_prd_prefix_parses_as_a_current_form_key():
    """A known, deliberate ambiguity: `PRD` is a legal 3-character tag, so `PRD-12`
    parses as item 12 of a project tagged PRD. Nothing renders that way any more, and
    the legacy table disambiguates the old ids — which is why AL-258 must refuse to let
    any project ever claim a tag that appears there."""
    assert tagging.parse("PRD-12") == ("PRD", "item", 12)
    # `R-33` escapes the ambiguity on its own: `R` fails the two-character minimum.
    assert tagging.parse("R-33") is None


@pytest.mark.parametrize(
    "old,expected", [("AL-01", 1), ("AL-12", 12), ("AL-254", 254), ("PRD-12", 12), ("R-33", 33)]
)
def test_legacy_number_reads_pre_tag_ids(old, expected):
    assert tagging.legacy_number(old) == expected


@pytest.mark.parametrize("junk", ["", "AL-", "12", "AL-x", "nope"])
def test_legacy_number_returns_none_on_junk(junk):
    assert tagging.legacy_number(junk) is None


# ---- the live schema -------------------------------------------------------------
def test_every_seeded_project_has_a_tag(client, auth):
    projects = client.get("/api/projects", headers=auth).json()
    assert projects
    for p in projects:
        row = _project_tag(p["id"])
        assert tagging.validate(row), f"{p['id']} has no valid tag"


def test_created_project_gets_a_derived_unique_tag(client, auth):
    a = client.post("/api/projects", json={"name": "Graph Widgets"}, headers=auth)
    b = client.post("/api/projects", json={"name": "Graph Widgets"}, headers=auth)
    assert a.status_code == 201 and b.status_code == 201, (a.text, b.text)

    ta, tb = _project_tag(a.json()["id"]), _project_tag(b.json()["id"])
    assert ta == "GW"       # derived from the name
    assert tb == "GW2"      # de-collided, still inside the length rule
    assert tagging.validate(tb)


def test_two_projects_cannot_hold_the_same_tag(client, auth):
    """Enforced by the database, not only by the derivation helper — a direct write
    that skips `_unique_tag` must still be refused."""
    from sqlalchemy.exc import IntegrityError

    from app.db import SessionLocal
    from app.models import Project

    existing = _project_tag(client.get("/api/projects", headers=auth).json()[0]["id"])
    db = SessionLocal()
    try:
        db.add(Project(id="collider", name="Collider", tag=existing))
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


@pytest.mark.parametrize(
    "path,payload,key",
    [
        ("/api/items", {"title": "numbered item"}, "id"),
        ("/api/prds", {"title": "numbered prd"}, "id"),
    ],
)
def test_created_entities_carry_a_number_matching_their_id(client, auth, path, payload, key):
    """Interim invariant (AL-259 replaces minting): `number` is the digits of the id,
    which is the same rule the backfill applied to every pre-existing row."""
    project_id = client.get("/api/projects", headers=auth).json()[0]["id"]
    r = client.post(path, json={**payload, "project_id": project_id}, headers=auth)
    assert r.status_code in (200, 201), r.text
    eid = r.json()[key]

    table = "items" if path.endswith("items") else "prds"
    with engine.connect() as conn:
        number = conn.execute(
            text(f"SELECT number FROM {table} WHERE id = :i"), {"i": eid}  # noqa: S608
        ).scalar()
    assert number == tagging.legacy_number(eid)


def test_every_seeded_entity_has_a_number(client, auth):
    """A NULL here would mean the mint path or the backfill missed a table."""
    with engine.connect() as conn:
        for table in ("items", "requests", "prds"):
            missing = conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE number IS NULL")  # noqa: S608
            ).scalar()
            assert missing == 0, f"{table} has {missing} row(s) with no number"


def _project_tag(project_id: str) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT tag FROM projects WHERE id = :i"), {"i": project_id}
        ).scalar()


# ---- the migration, against data -------------------------------------------------
@pytest.mark.skipif(_IS_SQLITE, reason="Alembic owns the schema on Postgres only")
def test_backfill_derives_tags_and_numbers_from_existing_rows(client, auth):
    """THE test this module exists for.

    The normal path migrates an EMPTY database and *then* seeds it, so 0038's backfill
    never touches a row and a broken one would pass every other test in the suite —
    the exact shape of the AL-248 defect. So: downgrade a populated database, then
    upgrade it again, and assert the backfill actually reconstructed everything.
    """
    from alembic import command

    from app.migrate import _BACKEND_ROOT
    from alembic.config import Config

    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))

    with engine.connect() as conn:
        before = {
            r[0]: (r[1], r[2])
            for r in conn.execute(text("SELECT id, name, tag FROM projects")).fetchall()
        }
        item_ids = [r[0] for r in conn.execute(text("SELECT id FROM items")).fetchall()]
    assert before and item_ids, "fixture must have seeded data for this to prove anything"

    command.downgrade(cfg, "0037")  # strips tag, number, and legacy_entity_keys
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM information_schema.columns"
                 " WHERE table_name='projects' AND column_name='tag'")
        ).scalar() == 0

    command.upgrade(cfg, "head")  # re-runs 0038 against POPULATED tables

    with engine.connect() as conn:
        for pid, (name, _old_tag) in before.items():
            tag = conn.execute(
                text("SELECT tag FROM projects WHERE id = :i"), {"i": pid}
            ).scalar()
            assert tagging.validate(tag)
            # Derived from the name, not carried over — modulo de-collision.
            assert tag.startswith(tagging.derive(name)[: len(tag)]) or tag == tagging.derive(name)

        for table in ("items", "requests", "prds"):
            rows = conn.execute(text(f"SELECT id, number FROM {table}")).fetchall()  # noqa: S608
            for eid, number in rows:
                assert number == tagging.legacy_number(eid), f"{table}.{eid} -> {number}"

        seeded = conn.execute(text("SELECT count(*) FROM legacy_entity_keys")).scalar()
        total = sum(
            conn.execute(text(f"SELECT count(*) FROM {t}")).scalar()  # noqa: S608
            for t in ("items", "requests", "prds")
        )
        assert seeded == total, "every pre-tag id must stay resolvable"

        # The legacy row points at a FROZEN id, so no chain can form on a later retag.
        one = conn.execute(
            text("SELECT old_key, entity_id FROM legacy_entity_keys WHERE old_key = :k"),
            {"k": item_ids[0]},
        ).fetchone()
        assert one and one[0] == one[1] == item_ids[0]


@pytest.mark.skipif(_IS_SQLITE, reason="Alembic owns the schema on Postgres only")
def test_backfill_never_rewrites_a_stored_id(client, auth):
    """The central claim of the design: identity is frozen. If a retag or a backfill
    can move `items.id`, every one of the nine unenforced reference columns is at risk."""
    from alembic import command

    from app.migrate import _BACKEND_ROOT
    from alembic.config import Config

    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))

    with engine.connect() as conn:
        before = sorted(r[0] for r in conn.execute(text("SELECT id FROM items")).fetchall())

    command.downgrade(cfg, "0037")
    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        after = sorted(r[0] for r in conn.execute(text("SELECT id FROM items")).fetchall())
    assert after == before
