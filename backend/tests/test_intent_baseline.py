"""The agreed spec is frozen at approval (AL-239 / PRD-12 slice A).

Everything PRD-12 does downstream — drift detection, the close report, both judges —
compares shipped work against "what we agreed to build". That phrase only means
something if there is an immutable record of it, taken at the moment of agreement.

Since PRD-15, the moment of agreement is grill completion, so the baseline freezes
itself. Nobody has to remember.

The load-bearing rule is the one that looks like a bug until you see why: a post-approval
edit does NOT move the baseline. If it did, the delivered spec and the agreed spec would
be the same object, drift would be definitionally zero, and PRD-12 would report perfect
alignment forever while measuring nothing.
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
def prd(db):
    return prd_svc.create_prd(db, title="Spec", project_id="core", body="# Spec\n\nOriginal intent.\n")


def _approve(db, prd):
    """Drive the PRD to approved the way a real one gets there — by finishing its grill."""
    prd_svc.record_grill_turns(db, prd.id, [{"role": "agent", "text": "Q?"},
                                            {"role": "user", "text": "A substantive answer."}])
    for name in prd_svc.DIMENSIONS:
        prd_svc.set_dimension(db, prd.id, name, "resolved")
    return prd_svc.sync_status(db, prd)


# ---- the baseline exists, and only at approval ---------------------------------------
def test_a_draft_has_no_agreed_spec(db, prd):
    """Nothing has been agreed, so there must be nothing to cite. A baseline conjured
    before approval would let a judge measure against a spec no one signed off."""
    assert prd_svc.baseline_of(db, prd.id) is None


def test_approval_freezes_the_baseline_by_itself(db, prd):
    _approve(db, prd)
    base = prd_svc.baseline_of(db, prd.id)
    assert base is not None and base.is_baseline is True
    assert "Original intent." in base.body


def test_approval_promotes_the_version_out_of_draft(db, prd):
    """`_bump` only increments minor, so it cannot express "this stopped being a draft" —
    which is exactly what the moment means."""
    assert prd.version == "v0.1"
    _approve(db, prd)
    assert prd.version == "v1.0"
    assert prd_svc.baseline_of(db, prd.id).version == "v1.0"


# ---- the rule the whole feature rests on ---------------------------------------------
def test_a_post_approval_edit_does_NOT_move_the_baseline(db, prd):
    """The load-bearing rule. If an edit moved the baseline, drift would always be zero
    and PRD-12 would look healthy while measuring nothing."""
    _approve(db, prd)
    baseline_id = prd_svc.baseline_of(db, prd.id).id

    prd_svc.update_prd(db, prd.id, body="# Spec\n\nSomething else entirely.\n")
    prd_svc.sync_status(db, prd)  # a recomputation must not re-freeze either

    base = prd_svc.baseline_of(db, prd.id)
    assert base.id == baseline_id, "a later edit produced a NEW baseline"
    assert "Original intent." in base.body, "the agreed spec was overwritten by a later edit"
    assert "Something else entirely." not in base.body
    assert "Something else entirely." in db.get(type(prd), prd.id).body  # the edit DID land


def test_an_ordinary_snapshot_is_not_a_baseline(db, prd):
    """Snapshots pile up freely during drafting; exactly one of them is the agreement."""
    _approve(db, prd)
    prd_svc.create_version(db, prd.id, note="just a checkpoint")

    baselines = [v for v in db.get(type(prd), prd.id).versions if v.is_baseline]
    assert len(baselines) == 1


def test_re_approving_an_unchanged_spec_does_not_stack_baselines(db, prd):
    """A status recomputation must never quietly mint a second "original intent"."""
    _approve(db, prd)
    first = prd_svc.baseline_of(db, prd.id)
    prd_svc.sync_status(db, prd)
    prd_svc.sync_status(db, prd)
    assert prd_svc.baseline_of(db, prd.id).id == first.id


# ---- what was deferred rides along ----------------------------------------------------
def test_the_baseline_records_what_was_deferred(db, prd):
    """A dimension the author consciously left open is the one case where later
    divergence was foreseen. A drift report that cannot tell it from an unplanned change
    would cry wolf on the thing everyone already agreed about."""
    prd_svc.record_grill_turns(db, prd.id, [{"role": "agent", "text": "Q?"},
                                            {"role": "user", "text": "An answer."}])
    for name in prd_svc.DIMENSIONS:
        prd_svc.set_dimension(db, prd.id, name, "resolved")
    prd_svc.set_dimension(db, prd.id, "contracts", "deferred", note="wire format after the spike")
    prd_svc.sync_status(db, prd)

    outcomes = prd_svc.baseline_of(db, prd.id).grill_outcomes
    assert outcomes["contracts"]["outcome"] == "deferred"
    assert "spike" in outcomes["contracts"]["note"]
    assert outcomes["scope_edges"]["outcome"] == "resolved"


# ---- the destructive path AL-239 names by name ----------------------------------------
def test_grill_apply_cannot_silently_destroy_the_body(db, prd):
    """`GRILL_APPLY_SYSTEM` asks the model for the FULL body, so whatever comes back
    replaces everything. Until now nothing preserved what was there first.

    The body is EDITED first on purpose: `create_prd` already snapshots the initial
    text, so asserting against the original would pass whether or not grill_apply
    snapshotted anything. Caught by sabotage — the first version of this test did
    exactly that and stayed green with the snapshot removed."""
    edited = "# Spec\n\nWork done since creation, not yet snapshotted anywhere.\n"
    prd_svc.update_prd(db, prd.id, body=edited)
    assert edited not in [v.body for v in db.get(type(prd), prd.id).versions]

    prd_svc.grill_apply(db, prd.id, [{"role": "user", "text": "A decision."}])

    bodies = [v.body for v in db.get(type(prd), prd.id).versions]
    assert edited in bodies, "the pre-rewrite body was not snapshotted"


def test_grill_apply_after_approval_leaves_the_baseline_alone(db, prd):
    """The snapshot it takes is an ordinary one — it records what the author had, not a
    new agreement."""
    _approve(db, prd)
    prd_svc.grill_apply(db, prd.id, [{"role": "user", "text": "A later decision."}])

    baselines = [v for v in db.get(type(prd), prd.id).versions if v.is_baseline]
    assert len(baselines) == 1
    assert "Original intent." in baselines[0].body


# ---- fetchable, because every judgement has to cite it ---------------------------------
def test_the_baseline_is_readable_over_the_api(client, auth, db, prd):
    """"Measured against v1.0" is only meaningful if v1.0 can be fetched."""
    assert client.get(f"/api/prds/{prd.id}/baseline", headers=auth).json() is None
    _approve(db, prd)

    got = client.get(f"/api/prds/{prd.id}/baseline", headers=auth).json()
    assert got["is_baseline"] is True
    assert got["version"] == "v1.0"
    assert "Original intent." in got["body"]
