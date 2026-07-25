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


def _prd_thread(db, entity_id="PRD-3", provider="anthropic"):
    return asst.create_thread(db, project_id="core", entity_type="prd", entity_id=entity_id,
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


# ---- AL-182: the new write tools flow through the same propose-then-approve gate ----
def test_link_items_stages_then_applies(db):
    from app.services import links as links_svc

    thread = _item_thread(db)
    def _link(): return [l for l in links_svc.list_links(db, project_id="core")
                         if l.a == "AL-08" and l.b == "AL-04"]
    res = approval.executor(db, thread, user_id="u1")(
        ToolCall(id="c1", name="link_items", input={"target_id": "AL-04"}))

    assert "awaiting your approval" in res.content
    (pa,) = approval.list_pending(db, thread.id)
    assert pa.tool == "link_items" and "AL-08 → AL-04" in pa.summary
    assert not _link()  # staged, not linked yet

    approval.apply(db, pa.id, user_id="u1")
    assert _link()  # now linked


def test_grill_apply_stages_applies_and_is_revertible(db):
    from app.services import prds as prd_svc

    thread = _prd_thread(db)  # PRD-3
    asst.add_message(db, thread.id, role="user", content="Ship read-only mode first.")
    before = prd_svc.get_prd(db, "PRD-3").body
    execute = approval.executor(db, thread, user_id="u1")

    res = execute(ToolCall(id="c1", name="grill_apply", input={}))
    assert "awaiting your approval" in res.content
    assert prd_svc.get_prd(db, "PRD-3").body == before  # synthesis deferred until approval
    (pa,) = approval.list_pending(db, thread.id)
    assert pa.summary.startswith("Rewrite PRD PRD-3")

    action, _ = approval.apply(db, pa.id, user_id="u1")
    assert action.status == "applied"
    assert "Ship read-only mode first." in prd_svc.get_prd(db, "PRD-3").body
    assert action.prior_value == {"body": before}  # whole-body snapshot captured

    action, _ = approval.revert(db, pa.id, user_id="u1")
    assert action.status == "reverted"
    assert prd_svc.get_prd(db, "PRD-3").body == before  # restored verbatim
