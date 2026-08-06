"""Read surfaces keep working after a retag (PRD-13 follow-up).

PRD-13's retag test proves the WRITE side: one UPDATE on one row, and the other ten
reference-bearing tables byte-identical. It never read an item back by its new key,
because until 2026-08-06 no project had actually been retagged.

Doing it on the live instance exposed two gaps in `get_item_details`, both invisible
until a project's rendered key stops matching its stored id:

- it returned the STORED id while every other read surface rendered, so one tool
  reported `AL-303` while `search_items` reported `GRPH-303` for the same item;
- it queried linked shards and requests with the CALLER'S string instead of the
  resolved id, so looking an item up by its new key silently returned no linked
  memory at all. Not an error — an empty list, which reads as "this item has none".

The tests below retag mid-test and then read, which is the step the original suite
was missing.
"""
import pytest

from app.services import items as items_svc
from app.services import memory as mem_svc
from app.services import projects as projects_svc
from app.services import requests as req_svc


@pytest.fixture()
def db(client):
    from app.db import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def item_with_links(db):
    """An item carrying a linked shard and a linked request — the state that made the
    bug visible. An item with no links passes either way."""
    item = items_svc.create_item(db, title="Has links", project_id="core")
    mem_svc.add_memory(db, text_body="A note about this item.", scope="item",
                       item_id=item.id, project_id="core", status="published")
    req = req_svc.create_request(db, title="Related ask", type_="feature", project_id="core")
    req_svc.link_request(db, req.id, item.id)
    return item


def _retag(db, new="ZZ"):
    return projects_svc.retag_project(db, "core", new)


# ---- the rendering gap ---------------------------------------------------------------
def test_details_render_the_current_key_not_the_stored_id(db, item_with_links):
    """One tool reporting AL-303 while another reports GRPH-303 for the same item is the
    kind of split that makes an agent think it has two items."""
    stored = item_with_links.id
    _retag(db)

    details = items_svc.get_item_details(db, stored)
    assert details["id"] != stored, "details still returned the frozen stored id"
    assert details["id"].startswith("ZZ-"), details["id"]


def test_a_linked_request_renders_too(db, item_with_links):
    _retag(db)
    details = items_svc.get_item_details(db, item_with_links.id)
    assert details["linked_requests"], "the fixture's linked request vanished"
    assert details["linked_requests"][0]["id"].startswith("ZZ-")


# ---- the resolution gap: the one that lost data --------------------------------------
def test_links_survive_a_lookup_by_the_NEW_key(db, item_with_links):
    """The regression proper. Before the fix this returned an empty list — no error, no
    warning, just an item that appeared to have no memory attached."""
    stored = item_with_links.id
    _retag(db)
    new_key = items_svc.get_item_details(db, stored)["id"]

    by_new = items_svc.get_item_details(db, new_key)
    assert len(by_new["linked_shards"]) == 1, "linked memory lost when looked up by the new key"
    assert len(by_new["linked_requests"]) == 1


def test_every_form_of_the_key_returns_the_same_record(db, item_with_links):
    """Old tag, new tag, and the stored id all name one item, so they must all answer
    identically — including the links."""
    stored = item_with_links.id
    _retag(db)
    new_key = items_svc.get_item_details(db, stored)["id"]

    views = [items_svc.get_item_details(db, k) for k in (stored, new_key)]
    assert views[0] == views[1], "the same item read differently depending on the key used"


def test_an_unknown_key_is_still_not_found(db, item_with_links):
    """Resolution must not become so permissive that anything resolves."""
    _retag(db)
    assert items_svc.get_item_details(db, "ZZ-9999") is None
