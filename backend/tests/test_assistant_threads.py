"""AL-174: assistant conversation threads — persistence + context assembly.

Service-level tests over a real (seeded) DB: the `client` fixture creates + seeds the
schema via lifespan, then we open a session directly.
"""
import pytest

from app.db import SessionLocal
from app.models import Prd
from app.services import assistant as asst


@pytest.fixture()
def db(client):  # client → schema created + seeded; hand back a live session
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def test_thread_persists_ordered_messages(db):
    thread = asst.create_thread(db, project_id="core", entity_type="prd", entity_id="PRD-1",
                                provider="anthropic", model="claude-opus-4-8")
    asst.add_message(db, thread.id, role="user", content="brainstorm the risks")
    asst.add_message(db, thread.id, role="assistant", content="here are three")
    asst.add_message(db, thread.id, role="user", content="expand the second")

    reloaded = asst.get_thread(db, thread.id)
    assert [m.seq for m in reloaded.messages] == [0, 1, 2]
    assert [m.content for m in reloaded.messages] == [
        "brainstorm the risks", "here are three", "expand the second"]
    assert reloaded.provider == "anthropic" and reloaded.model == "claude-opus-4-8"


def test_add_message_stores_toolcalling_record(db):
    thread = asst.create_thread(db, project_id="core", entity_type="item", entity_id="AL-08")
    asst.add_message(
        db, thread.id, role="assistant",
        tool_calls=[{"id": "call_1", "name": "update_item", "input": {"id": "AL-08", "status": "done"}}],
        tool_results=[{"id": "call_1", "content": "ok", "is_error": False}],
        proposed_actions=[{"tool": "update_item", "args": {"status": "done"}, "status": "pending"}],
    )
    (m,) = asst.get_thread(db, thread.id).messages
    assert m.tool_calls[0]["input"] == {"id": "AL-08", "status": "done"}
    assert m.tool_results[0]["is_error"] is False
    assert m.proposed_actions[0]["status"] == "pending"


def test_list_threads_scopes_by_entity(db):
    a = asst.create_thread(db, project_id="core", entity_type="prd", entity_id="PRD-1")
    asst.create_thread(db, project_id="core", entity_type="item", entity_id="AL-08")

    prd_threads = asst.list_threads(db, project_id="core", entity_type="prd", entity_id="PRD-1")
    assert [t.id for t in prd_threads] == [a.id]
    # unscoped lists both (plus any from other tests' isolation — DB is fresh per test)
    assert len(asst.list_threads(db, project_id="core")) == 2


def test_create_thread_rejects_bad_entity_type(db):
    with pytest.raises(ValueError):
        asst.create_thread(db, project_id="core", entity_type="epic", entity_id="X")


def test_thread_context_grounds_in_prd(db):
    prd = db.get(Prd, "PRD-1")
    thread = asst.create_thread(db, project_id="core", entity_type="prd", entity_id="PRD-1")
    ctx = asst.thread_context(db, thread)
    assert prd.title in ctx
    assert (prd.body or "")[:40] in ctx  # grounded in the actual PRD body


def test_thread_context_grounds_in_item_with_linked_memory(db):
    from app.services import memory as mem_svc

    mem_svc.add_memory(db, text_body="caching lesson: prefer idempotency keys", scope="item",
                       item_id="AL-08", project_id="core", source="lesson from AL-08")
    thread = asst.create_thread(db, project_id="core", entity_type="item", entity_id="AL-08")
    ctx = asst.thread_context(db, thread)
    assert "AL-08" in ctx
    assert "caching lesson: prefer idempotency keys" in ctx
