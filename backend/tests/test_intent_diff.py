"""The approver sees what a rebaseline changes (GRPH-317 / PRD-12).

PRD-12 is blunt about why this exists: without it "the human ratifies a decision already
made in chat without seeing its effect on the spec, and it is rubber-stamping with an
audit trail."

That failure was live until now. The v1.0 → v1.1 rebaseline of PRD-12 itself was approved
with no diff surface at all — the review happened in conversation, which is exactly the
substitute the PRD warns about.
"""
import pytest

from app.services import prds as prd_svc

BODY = ("# Spec\n\n## Scope\n\nOut of scope: hosted mode.\n\n"
        "## Failures\n\nRetry once, then surface.\n\n## Contracts\n\nJSON-RPC over POST.\n")


@pytest.fixture()
def db(client):
    from app.db import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def pending(db):
    """An approved PRD with a rebaseline requested — the state this surface exists for."""
    prd = prd_svc.create_prd(db, title="Spec", project_id="core", body=BODY)
    # A distinct answer per round. Re-posting the previous one records nothing (GRPH-322):
    # a rebaseline is graded only on answers given after it was requested.
    window = prd_svc.grill_window(db, prd.id)
    prior = prd_svc.grill_history(db, prd.id, since=window)
    prd_svc.record_grill_turns(db, prd.id, prior + [
        {"role": "user", "text": f"An answer, round {len(prd_svc.baseline_chain(db, prd.id))}."}])
    for name in prd_svc.DIMENSIONS:
        prd_svc.set_dimension(db, prd.id, name, "resolved")
    prd_svc.sync_status(db, prd)
    prd_svc.request_rebaseline(db, prd, reason_type="correction",
                               reason="The close rule bricks a default install.",
                               requested_by="agent:loop")
    return prd


def _sections(diff):
    return {s["title"]: s for s in diff["sections"]}


# ---- what the approver must be able to see ----------------------------------------------
def test_a_modified_section_shows_its_lines(db, pending):
    """Naming the section is not enough — "Scope changed" tells an approver nothing about
    whether the change was a typo or a reversal."""
    prd_svc.update_prd(db, pending.id,
                       body=BODY.replace("hosted mode.", "hosted mode and CI gating."))
    out = prd_svc.intent_diff(db, pending)

    scope = _sections(out)["Scope"]
    assert scope["state"] == "modified"
    assert {"op": "-", "text": "Out of scope: hosted mode."} in scope["lines"]
    assert {"op": "+", "text": "Out of scope: hosted mode and CI gating."} in scope["lines"]


def test_a_removed_section_carries_its_old_text(db, pending):
    """The most consequential thing an approver can miss. A bare "Contracts: removed"
    makes it impossible to judge whether losing it matters."""
    prd_svc.update_prd(db, pending.id, body=BODY.split("## Contracts")[0])
    out = prd_svc.intent_diff(db, pending)

    removed = _sections(out)["Contracts"]
    assert removed["state"] == "removed"
    assert {"op": "-", "text": "JSON-RPC over POST."} in removed["lines"]


def test_a_rename_shows_both_titles(db, pending):
    """Otherwise it reads as a section vanishing and an unrelated one appearing."""
    prd_svc.update_prd(db, pending.id, body=BODY.replace("## Scope", "## Scope and boundaries"))
    out = prd_svc.intent_diff(db, pending)

    renamed = _sections(out)["Scope and boundaries"]
    assert renamed["state"] == "renamed" and renamed["was"] == "Scope"


def test_unchanged_sections_are_named_but_not_expanded(db, pending):
    """A diff that reprints the whole spec is one nobody reads, which defeats it as
    surely as showing nothing."""
    prd_svc.update_prd(db, pending.id, body=BODY.replace("Retry once", "Retry twice"))
    out = prd_svc.intent_diff(db, pending)

    assert _sections(out)["Scope"]["state"] == "unchanged"
    assert "lines" not in _sections(out)["Scope"]
    assert out["changed"] == 1


def test_the_reason_travels_with_the_diff(db, pending):
    """The approver needs the stated reason next to its actual effect — that pairing is
    what makes "we just clarified it" checkable against a rewrite."""
    out = prd_svc.intent_diff(db, pending)
    assert out["pending"]["reason_type"] == "correction"
    assert "bricks a default install" in out["pending"]["reason"]
    assert out["baseline_version"] == "v1.0"


# ---- when it should say nothing -----------------------------------------------------------
def test_a_prd_with_no_baseline_is_not_governed(db):
    """Nothing to diff against. Distinct from "nothing changed", and reporting it as the
    latter would be the misleading green this PRD exists to stop."""
    prd = prd_svc.create_prd(db, title="Draft", project_id="core", body=BODY)
    out = prd_svc.intent_diff(db, prd)
    assert out["governed"] is False and out["sections"] == []


def test_no_pending_rebaseline_means_nothing_is_being_approved(db, pending):
    """Divergence outside a rebaseline is DRIFT — reportable, but not a decision anyone is
    making here. The surface must not nag about it."""
    # A rebaseline is graded only on answers given after it was requested (GRPH-322), so
    # the new interrogation has to actually be answered before it can complete.
    prd_svc.record_grill_turns(db, pending.id, [{"role": "user", "text": "Answered again."}])
    for name in prd_svc.DIMENSIONS:
        prd_svc.set_dimension(db, pending.id, name, "resolved")
    prd_svc.sync_status(db, pending)  # completes the grill, clearing the pending request
    assert pending.pending_rebaseline is None

    prd_svc.update_prd(db, pending.id, body=BODY.replace("Retry once", "Retry twice"))

    assert prd_svc.intent_diff(db, pending)["pending"] is None


def test_the_diff_is_readable_over_the_api(client, auth, db, pending):
    prd_svc.update_prd(db, pending.id, body=BODY.replace("hosted mode.", "hosted mode and CI."))
    out = client.get(f"/api/prds/{pending.id}/intent-diff", headers=auth).json()

    assert out["governed"] is True and out["changed"] == 1
    scope = [s for s in out["sections"] if s["title"] == "Scope"][0]
    assert any(l["op"] == "+" for l in scope["lines"])
