"""AL-177: propose-then-approve — writes stage, apply executes + audits + is reversible."""
import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Event, Item
from app.providers.toolcall import ToolCall
from app.services import assistant as asst
from app.services import assistant_approval as approval


@pytest.fixture()
def db(client):
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _item_thread(db, provider="anthropic"):
    return asst.create_thread(db, project_id="core", entity_type="item", entity_id="AL-08",
                              provider=provider)


def test_write_is_staged_not_executed(db):
    thread = _item_thread(db)
    before = db.get(Item, "AL-08").status
    execute = approval.executor(db, thread, user_id="u1")

    res = execute(ToolCall(id="c1", name="update_item", input={"status": "review"}))

    assert "awaiting your approval" in res.content and not res.is_error
    assert db.get(Item, "AL-08").status == before  # NOT mutated
    pending = approval.list_pending(db, thread.id)
    assert len(pending) == 1 and pending[0].tool == "update_item" and pending[0].status == "pending"


def test_read_executes_immediately(db):
    thread = _item_thread(db)
    res = approval.executor(db, thread, user_id="u1")(ToolCall(id="c1", name="get_item_details", input={}))
    assert not res.is_error and "AL-08" in res.content
    assert approval.list_pending(db, thread.id) == []  # reads don't stage


def test_apply_executes_captures_prior_and_audits(db):
    thread = _item_thread(db)
    before = db.get(Item, "AL-08").status
    execute = approval.executor(db, thread, user_id="u1")
    execute(ToolCall(id="c1", name="update_item", input={"status": "review"}))
    (pa,) = approval.list_pending(db, thread.id)

    action, msg = approval.apply(db, pa.id, user_id="u1")

    assert action.status == "applied"
    assert db.get(Item, "AL-08").status == "review"      # now executed
    assert action.prior_value == {"status": before}      # prior captured for revert
    ev = db.scalars(select(Event).where(Event.action == "assistant_apply")).first()
    assert ev.meta["origin"] == "assistant:anthropic" and ev.meta["tool"] == "update_item"


def test_reject_drops_without_mutation(db):
    thread = _item_thread(db)
    before = db.get(Item, "AL-08").status
    approval.executor(db, thread, user_id="u1")(
        ToolCall(id="c1", name="update_item", input={"status": "done"}))
    (pa,) = approval.list_pending(db, thread.id)

    approval.reject(db, pa.id)

    assert db.get(approval.AssistantProposedAction, pa.id).status == "rejected"
    assert db.get(Item, "AL-08").status == before
    assert approval.list_pending(db, thread.id) == []


def test_revert_restores_prior_value(db):
    thread = _item_thread(db)
    orig = db.get(Item, "AL-08").status
    execute = approval.executor(db, thread, user_id="u1")
    execute(ToolCall(id="c1", name="update_item", input={"status": "review"}))
    (pa,) = approval.list_pending(db, thread.id)
    approval.apply(db, pa.id, user_id="u1")
    assert db.get(Item, "AL-08").status == "review"

    action, msg = approval.revert(db, pa.id, user_id="u1")

    assert action.status == "reverted"
    assert db.get(Item, "AL-08").status == orig  # restored


def test_apply_is_idempotent_against_double_click(db):
    thread = _item_thread(db)
    approval.executor(db, thread, user_id="u1")(
        ToolCall(id="c1", name="update_item", input={"status": "review"}))
    (pa,) = approval.list_pending(db, thread.id)
    approval.apply(db, pa.id, user_id="u1")
    _, msg = approval.apply(db, pa.id, user_id="u1")  # second apply
    assert "already applied" in msg


def test_read_only_user_cannot_stage_a_write(db):
    thread = _item_thread(db)
    before = db.get(Item, "AL-08").status
    # u3 (Ops Lee) is read-only on core.
    res = approval.executor(db, thread, user_id="u3")(
        ToolCall(id="c1", name="update_item", input={"status": "done"}))
    assert res.is_error and "not authorized" in res.content
    assert approval.list_pending(db, thread.id) == []  # nothing staged
    assert db.get(Item, "AL-08").status == before
