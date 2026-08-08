"""A stored reference to another entity holds its frozen id, never a rendering (GRPH-319).

`keys` already states the rule — *"Reads and writes both"* — and every call site honours
it for the entity it ADDRESSES: `update_item` resolves its own `item_id`. Nothing
resolved the entity a call REFERENCES. `create_item(prd_id=...)` stored the caller's
string verbatim.

That produced two spellings of one PRD on the live database: items written before the
AL→GRPH retag held `PRD-12`, items written after held `GRPH-P12`. Both resolve on read,
so every surface looked right — `_key_of` renders a dangling reference back as itself.
But `coverage` joins on the raw string, and it matched only one of them. Eight of
PRD-12's twenty-two items, including shipped work, were missing from its own coverage.

The bug needs a retag to exist at all, which is why a suite that only ever builds fresh
projects could not have caught it. Every test here retags first.
"""
import pytest
from sqlalchemy import text

from app.db import engine
from app.services import items as items_svc
from app.services import prds as prd_svc
from app.services import projects as projects_svc

_IS_SQLITE = engine.url.drivername.startswith("sqlite")


@pytest.fixture()
def db(client):
    from app.db import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def retagged_prd(db):
    """A PRD whose project has been retagged — so its frozen id and its rendered key are
    different strings, which is the only condition under which any of this can break."""
    prd = prd_svc.create_prd(db, title="Spec", project_id="core",
                             body="# Spec\n\n## Delivery\n\nShip it.\n")
    projects_svc.retag_project(db, "core", "ZZ")
    db.refresh(prd)
    assert prd.key != prd.id, "fixture is inert unless the rendering diverged from the id"
    return prd


# ---- the write path ------------------------------------------------------------------
def test_creating_an_item_by_a_prds_rendered_key_stores_the_frozen_id(db, retagged_prd):
    item = items_svc.create_item(db, title="Work", project_id="core",
                                 prd_id=retagged_prd.key, prd_section="Delivery")
    assert item.prd_id == retagged_prd.id


def test_updating_an_item_by_a_prds_rendered_key_stores_the_frozen_id(db, retagged_prd):
    item = items_svc.create_item(db, title="Work", project_id="core")
    items_svc.update_item(db, item.id, prd_id=retagged_prd.key)
    db.refresh(item)
    assert item.prd_id == retagged_prd.id


def test_a_reference_that_names_nothing_is_kept_not_dropped(db):
    """Storing NULL would destroy the only evidence of what the author meant. A dangling
    reference is repairable by hand; a discarded one is not."""
    item = items_svc.create_item(db, title="Work", project_id="core", prd_id="NOPE-P9")
    assert item.prd_id == "NOPE-P9"


# ---- what the bug actually cost ------------------------------------------------------
def test_coverage_counts_work_linked_by_the_rendered_key(db, retagged_prd):
    """The failure that hid 8 shipped items. Before the fix this section reported
    item_count 0 and `gap: True` — a PRD confidently claiming it had no work at all."""
    items_svc.create_item(db, title="Work", project_id="core",
                          prd_id=retagged_prd.key, prd_section="Delivery")

    section = [s for s in prd_svc.coverage(db, retagged_prd)["sections"]
               if s["section"] == "Delivery"][0]
    assert section["item_count"] == 1
    assert section["gap"] is False


def test_coverage_counts_work_linked_before_and_after_a_retag_as_one_set(db):
    """The live shape: half the items written under the old tag, half under the new. A
    join on the raw string can only ever match one half, and reports the other as absent.
    """
    prd = prd_svc.create_prd(db, title="Spec", project_id="core",
                             body="# Spec\n\n## Delivery\n\nShip it.\n")
    items_svc.create_item(db, title="Before", project_id="core",
                          prd_id=prd.key, prd_section="Delivery")
    projects_svc.retag_project(db, "core", "ZZ")
    db.refresh(prd)
    items_svc.create_item(db, title="After", project_id="core",
                          prd_id=prd.key, prd_section="Delivery")

    section = [s for s in prd_svc.coverage(db, prd)["sections"]
               if s["section"] == "Delivery"][0]
    assert section["item_count"] == 2


def test_coverage_reports_items_under_the_tag_the_project_holds_now(db, retagged_prd):
    """`item_ids` returned the frozen id, so a retagged project reported its work under a
    tag it no longer holds — the same split already fixed once in `get_item_details`."""
    item = items_svc.create_item(db, title="Work", project_id="core",
                                 prd_id=retagged_prd.key, prd_section="Delivery")
    db.refresh(item)

    section = [s for s in prd_svc.coverage(db, retagged_prd)["sections"]
               if s["section"] == "Delivery"][0]
    assert section["item_ids"] == [item.key]
    assert item.key.startswith("ZZ-")


# ---- the backfill, against data ------------------------------------------------------
@pytest.mark.skipif(_IS_SQLITE, reason="Alembic owns the schema on Postgres only")
def test_the_migration_repairs_rows_already_written(client, auth, db, retagged_prd):
    """Fixing the write path leaves 22 rows on the live database still broken, and a data
    migration that quietly does nothing is indistinguishable from one that worked — the
    AL-248 failure. So: write the bad row the old code would have written, re-run the
    migration against it, and assert the row moved.
    """
    from alembic import command
    from alembic.config import Config

    from app.migrate import _BACKEND_ROOT

    item = items_svc.create_item(db, title="Work", project_id="core",
                                 prd_section="Delivery")
    db.commit()
    with engine.begin() as conn:  # exactly what create_item did before the fix
        conn.execute(text("UPDATE items SET prd_id = :k WHERE id = :i"),
                     {"k": retagged_prd.key, "i": item.id})

    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    command.downgrade(cfg, "0046")
    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        assert conn.execute(text("SELECT prd_id FROM items WHERE id = :i"),
                            {"i": item.id}).scalar() == retagged_prd.id


@pytest.mark.skipif(_IS_SQLITE, reason="Alembic owns the schema on Postgres only")
def test_the_migration_leaves_a_reference_that_names_nothing_alone(client, auth, db):
    """The stored string is the only surviving evidence of what the author meant."""
    from alembic import command
    from alembic.config import Config

    from app.migrate import _BACKEND_ROOT

    item = items_svc.create_item(db, title="Orphan", project_id="core")
    db.commit()
    with engine.begin() as conn:
        conn.execute(text("UPDATE items SET prd_id = 'NOPE-P9' WHERE id = :i"),
                     {"i": item.id})

    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    command.downgrade(cfg, "0046")
    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        assert conn.execute(text("SELECT prd_id FROM items WHERE id = :i"),
                            {"i": item.id}).scalar() == "NOPE-P9"
