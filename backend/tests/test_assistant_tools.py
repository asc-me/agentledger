"""AL-173: assistant tool surface — advertising, scoping, authz, dispatch."""
import json

import pytest

from app.db import SessionLocal
from app.models import Item
from app.providers.toolcall import ToolCall
from app.services import assistant_tools as at


@pytest.fixture()
def db(client):
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _ctx(db, entity_type, entity_id, user_id="u1"):  # u1 = owner (write) on core
    return at.ToolContext(db=db, user_id=user_id, project_id="core",
                          entity_type=entity_type, entity_id=entity_id)


def test_available_tools_are_entity_scoped(db):
    item_tools = {s.name for s in at.available_tools(_ctx(db, "item", "AL-08"))}
    prd_tools = {s.name for s in at.available_tools(_ctx(db, "prd", "PRD-1"))}
    assert "update_item" in item_tools and "update_prd" not in item_tools
    assert "update_prd" in prd_tools and "update_item" not in prd_tools
    # reads + project-scoped writes are available on both
    assert {"get_item_details", "search_items", "search_memory", "create_item", "add_memory"} <= item_tools


def test_dispatch_read_returns_item(db):
    r = at.dispatch(_ctx(db, "item", "AL-08"), ToolCall(id="c1", name="get_item_details", input={}))
    assert not r.is_error
    assert json.loads(r.content)["id"] == "AL-08"


def test_dispatch_update_item_is_scoped_to_the_thread_entity(db):
    r = at.dispatch(_ctx(db, "item", "AL-08"),
                    ToolCall(id="c1", name="update_item", input={"status": "review"}))
    assert not r.is_error and "AL-08" in r.content
    assert db.get(Item, "AL-08").status == "review"


def test_update_item_unavailable_on_a_prd_thread(db):
    r = at.dispatch(_ctx(db, "prd", "PRD-1"),
                    ToolCall(id="c1", name="update_item", input={"status": "done"}))
    assert r.is_error and "not available" in r.content


def test_add_memory_enters_as_a_candidate_scoped_to_the_item(db):
    from app.services import memory as mem_svc

    r = at.dispatch(_ctx(db, "item", "AL-08"),
                    ToolCall(id="c1", name="add_memory", input={"text": "assistant lesson xyz"}))
    assert not r.is_error and "candidate" in r.content
    shard = next(s for s in mem_svc.list_shards(db, project_id="core", status="candidate")
                 if s.text == "assistant lesson xyz")
    assert shard.item_id == "AL-08" and shard.origin == "assistant"


def test_dispatch_unknown_tool_is_error(db):
    r = at.dispatch(_ctx(db, "item", "AL-08"), ToolCall(id="c1", name="delete_everything", input={}))
    assert r.is_error and "unknown tool" in r.content


def test_writes_require_writable_authz(db):
    # u3 (Ops Lee) is read-only on core.
    ro = _ctx(db, "item", "AL-08", user_id="u3")
    w = at.dispatch(ro, ToolCall(id="c1", name="update_item", input={"status": "done"}))
    assert w.is_error and "not authorized" in w.content
    assert db.get(Item, "AL-08").status != "done"  # nothing changed
    # a read is fine for the same user
    rd = at.dispatch(ro, ToolCall(id="c2", name="search_items", input={"query": "pgvector"}))
    assert not rd.is_error


def test_tool_kind_seam_for_the_approval_flow(db):
    assert at.tool_kind("search_items") == "read"
    assert at.tool_kind("update_item") == "write"
    assert at.tool_kind("nope") is None
