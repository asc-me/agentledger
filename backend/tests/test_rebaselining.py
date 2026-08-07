"""Rebaselining: an append-only chain, approved by grilling (AL-241 / PRD-12).

Specs legitimately change mid-delivery. The problem is that *learning*, *scope change*
and *laundering* are content-identical when you only look at the end state: "we
discovered the spec was wrong" and "we edited the spec to match what we built" produce
the same diff. Only sequencing and a stated reason tell them apart, which is why the
chain, the typed reason and the requester's own words are all mandatory rather than
nice to have.

Approval is the grill, not an authority check (PRD-12 v1.0, answer 1). A rebaseline is a
new statement of intent, so it earns approval the way the original did — by being
interrogated. That handles laundering better than a click, because "we edited the spec to
match what we built" has to survive being questioned, on the record.
"""
import pytest

from app.services import prds as prd_svc


@pytest.fixture()
def db(client):
    from app.db import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def approved(db):
    """A PRD that has earned its first baseline the honest way."""
    prd = prd_svc.create_prd(db, title="Spec", project_id="core",
                             body="# Spec\n\nThe original intent.\n")
    _grill_to_approval(db, prd)
    return prd


def _grill_to_approval(db, prd):
    prd_svc.record_grill_turns(db, prd.id, [{"role": "agent", "text": "Q?"},
                                            {"role": "user", "text": "A substantive answer."}])
    for name in prd_svc.DIMENSIONS:
        prd_svc.set_dimension(db, prd.id, name, "resolved")
    return prd_svc.sync_status(db, prd)


def _request(db, prd, **kw):
    return prd_svc.request_rebaseline(db, prd, **{
        "reason_type": "learning", "reason": "We learned the judge is inert on a default install.",
        "requested_by": "agent:loop", **kw})


# ---- the append-only guarantee ---------------------------------------------------------
def test_a_rebaseline_never_destroys_the_one_it_supersedes(db, approved):
    """The property the whole design rests on. If N+1 could erase N, rebaselining would
    become the tidiest way to remove an awkward record — and drift would be whatever the
    last edit said it was."""
    first = prd_svc.baseline_of(db, approved.id)
    first_id, first_body = first.id, first.body

    _request(db, approved)
    prd_svc.update_prd(db, approved.id, body="# Spec\n\nRevised intent.\n")
    _grill_to_approval(db, approved)

    chain = prd_svc.baseline_chain(db, approved.id)
    assert len(chain) == 2
    assert chain[0].id == first_id and chain[0].body == first_body, "the original was altered"
    assert chain[1].supersedes_id == first_id, "the new baseline does not point back"


def test_the_newest_baseline_governs(db, approved):
    _request(db, approved)
    prd_svc.update_prd(db, approved.id, body="# Spec\n\nRevised intent.\n")
    _grill_to_approval(db, approved)

    assert "Revised intent." in prd_svc.baseline_of(db, approved.id).body


def test_a_rebaseline_bumps_the_minor_version(db, approved):
    """v1.0 -> v1.1. Major never increments again in a PRD's life: post-close changes
    become a new PRD, so a second v1.0 would be meaningless."""
    assert approved.version == "v1.0"
    _request(db, approved)
    prd_svc.update_prd(db, approved.id, body="# Spec\n\nRevised.\n")
    _grill_to_approval(db, approved)
    assert approved.version == "v1.1"


# ---- the reason is what separates learning from laundering ------------------------------
def test_the_reason_travels_onto_the_new_baseline(db, approved):
    """An agent mid-work is often where new intent surfaces, and that reasoning dies with
    the context window unless something writes it down."""
    _request(db, approved, reason_type="correction",
             reason="The close rule bricks a default install because the judge is stubbed.")
    prd_svc.update_prd(db, approved.id, body="# Spec\n\nRevised.\n")
    _grill_to_approval(db, approved)

    newest = prd_svc.baseline_of(db, approved.id)
    assert newest.rebaseline_reason_type == "correction"
    assert "bricks a default install" in newest.rebaseline_reason
    assert newest.requested_by == "agent:loop"


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_a_rebaseline_without_a_reason_is_refused(db, approved, bad):
    with pytest.raises(ValueError, match="reason"):
        _request(db, approved, reason=bad or "")


def test_the_reason_type_is_typed(db, approved):
    """A chain reads at a glance: a run of `correction` is a spec that was wrong, a run of
    `scope-change` is a project that moved. Free text would lose that."""
    with pytest.raises(ValueError, match="reason_type"):
        _request(db, approved, reason_type="because")


# ---- approval is the grill ---------------------------------------------------------------
def test_requesting_does_not_approve_anything(db, approved):
    """The request re-opens the interrogation; it does not grant the thing being asked
    for. Otherwise "agent requests rebaseline" would be self-service intent."""
    _request(db, approved)
    assert approved.status == "review"
    assert prd_svc.completion(db, approved.id)["outstanding"] == sorted(prd_svc.DIMENSIONS)


def test_the_old_baseline_still_governs_while_the_grill_is_open(db, approved):
    """Work in flight has to be measured against SOMETHING. Clearing the baseline at
    request time would leave a window with no governing intent at all."""
    _request(db, approved)
    prd_svc.update_prd(db, approved.id, body="# Spec\n\nProposed but not yet agreed.\n")

    governing = prd_svc.baseline_of(db, approved.id)
    assert "The original intent." in governing.body
    assert "Proposed but not yet agreed." not in governing.body


def test_an_unchanged_body_earns_no_new_baseline(db, approved):
    """Re-approving identical text after questioning is a reaffirmation, not new intent —
    there is nothing new to freeze, and a duplicate would inflate the chain."""
    _request(db, approved)
    _grill_to_approval(db, approved)

    assert len(prd_svc.baseline_chain(db, approved.id)) == 1
    assert approved.pending_rebaseline is None, "the pending request must still be cleared"


# ---- refusals ----------------------------------------------------------------------------
def test_a_prd_with_no_baseline_cannot_be_rebaselined(db):
    """Nothing to supersede. This would otherwise be a way to mint a baseline without
    ever having been approved."""
    prd = prd_svc.create_prd(db, title="Never approved", project_id="core", body="# x\n")
    with pytest.raises(ValueError, match="never been approved"):
        _request(db, prd)


def test_the_request_is_audited(db, approved):
    from app.models import Event

    _request(db, approved, reason="Because the judge is inert by default.")
    ev = db.query(Event).filter(Event.action == "request_rebaseline").all()
    assert len(ev) == 1 and "inert by default" in str(ev[0].meta)


def test_the_chain_is_readable_over_the_api(client, auth, db, approved):
    _request(db, approved)
    prd_svc.update_prd(db, approved.id, body="# Spec\n\nRevised.\n")
    _grill_to_approval(db, approved)

    chain = client.get(f"/api/prds/{approved.id}/baselines", headers=auth).json()
    assert [c["version"] for c in chain] == ["v1.0", "v1.1"]
    assert chain[0]["supersedes_id"] is None
    assert chain[1]["supersedes_id"] == chain[0]["id"]
