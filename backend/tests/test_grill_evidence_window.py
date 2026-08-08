"""A rebaseline earns approval on its OWN answers (GRPH-322 / PRD-12 / PRD-15).

Found by running a real rebaseline on the live instance, not by any test. PRD-12 reached
`v1.2`, `approved`, with **zero new answers recorded** — every dimension resolved citing
`turn_seq: 7`, the last answer of the v1.0 grill, about a different body.

`request_rebaseline` cleared the dimension verdicts and left the transcript, which is
right: history is append-only. But `classify_grill` read the *whole* transcript, re-graded
the previous grill's answers, and `sync_status` promoted straight back to `approved`.

That defeats the property `request_rebaseline` exists for, in its own words: *"'we edited
the spec to match what we built' has to survive being questioned."* It did not have to —
the previous conversation answered on its behalf, and rebaselining is precisely where
laundering is the named risk.

Every pre-existing rebaseline test supplies fresh answers before classifying, which is why
none of them could catch this. **These tests assert the negative**: classify with nothing
new and expect the PRD to stay in `review`.
"""
import pytest

from app.services import prds as prd_svc

BODY = (
    "# Spec\n\n"
    "## Problem\n\nNothing checks delivery.\n\n"
    "## Baseline\n\nFreeze the spec at approval.\n\n"
    "## Judging\n\nClassify each completed item against the goal.\n"
)


@pytest.fixture()
def db(client):
    from app.db import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _answer(db, prd, text="A substantive answer about scope, failures and contracts."):
    """Append one answer the way a client does — posting the transcript of THIS round."""
    history = prd_svc.grill_history(db, prd.id, since=prd_svc.grill_window(db, prd.id))
    return prd_svc.record_grill_turns(
        db, prd.id, history + [{"role": "user", "text": text}], via="agent", actor="agent:t")


def _resolve_all(db, prd):
    for name in prd_svc.DIMENSIONS:
        prd_svc.set_dimension(db, prd.id, name, "resolved")
    prd_svc.sync_status(db, prd)


@pytest.fixture()
def approved(db):
    prd = prd_svc.create_prd(db, title="Spec", project_id="core", body=BODY)
    for i in range(4):
        _answer(db, prd, f"Original grill answer {i}, about the original spec.")
    _resolve_all(db, prd)
    assert prd.status == "approved"
    return prd


def _rebaseline_requested(db, prd):
    prd_svc.request_rebaseline(db, prd, reason_type="learning",
                               reason="We learned the close rule was wrong.",
                               requested_by="agent:t")
    prd_svc.update_prd(db, prd.id, body=BODY.replace(
        "Classify each completed item against the goal.", "Rewritten after learning."))
    return prd


# ---- the defect ------------------------------------------------------------------------
def test_a_rebaseline_is_not_completed_by_the_previous_grills_answers(db, approved):
    """THE test. Before the fix this reached `approved` at a new baseline version with
    nothing added — the previous conversation graded a spec it had never seen."""
    _rebaseline_requested(db, approved)
    before = [v.version for v in prd_svc.baseline_chain(db, approved.id)]

    prd_svc.classify_grill(db, approved)
    prd_svc.sync_status(db, approved)

    assert approved.status == "review"
    assert [v.version for v in prd_svc.baseline_chain(db, approved.id)] == before


def test_the_dimensions_read_unanswered_not_resolved(db, approved):
    """The honest state. Silently carrying the old verdicts forward would make the
    outstanding list lie about what still needs asking."""
    _rebaseline_requested(db, approved)
    prd_svc.classify_grill(db, approved)

    done = prd_svc.completion(db, approved.id)
    assert done["complete"] is False
    assert sorted(done["outstanding"]) == sorted(prd_svc.DIMENSIONS)


def test_the_answer_floor_counts_only_this_interrogation(db, approved):
    """`completion` refuses to complete a grill with no answers. Counting the previous
    grill's answers is what let that floor pass trivially after a rebaseline."""
    _rebaseline_requested(db, approved)

    assert prd_svc.completion(db, approved.id)["answers"] == 0


# ---- the transcript is history and is not destroyed -------------------------------------
def test_the_earlier_conversation_is_preserved(db, approved):
    """The window moves; the record does not shrink. Deleting the old turns would be the
    easy fix and the wrong one — the chain exists so nothing about how intent moved can be
    erased, and that has to include what was asked."""
    _rebaseline_requested(db, approved)

    assert len(prd_svc.grill_turns(db, approved.id)) == 4
    assert prd_svc.grill_window(db, approved.id) == 4
    state = prd_svc.grill_state(db, approved.id)
    assert len(state["turns"]) == 4      # full history, still readable
    assert state["answers"] == 0          # but none of it is evidence for THIS round
    assert state["grill_from_seq"] == 4


# ---- and a real rebaseline still works --------------------------------------------------
def test_new_answers_do_complete_the_rebaseline(db, approved):
    """The window must not make rebaselining impossible — only unearned."""
    _rebaseline_requested(db, approved)
    for i in range(4):
        _answer(db, approved, f"New answer {i} about the rewritten close rule.")
    _resolve_all(db, approved)

    assert approved.status == "approved"
    assert [v.version for v in prd_svc.baseline_chain(db, approved.id)] == ["v1.0", "v1.1"]


def test_a_client_posting_a_fresh_transcript_has_its_answers_recorded(db, approved):
    """The same bug by a second route, and the one that bit in practice. `record_grill_turns`
    appends the suffix past what it holds; measured against the WHOLE transcript, a client
    starting a new conversation after a rebaseline appends nothing — silently — and the old
    answers stay the only evidence."""
    _rebaseline_requested(db, approved)

    added = prd_svc.record_grill_turns(
        db, approved.id, [{"role": "user", "text": "A fresh answer."}], via="agent", actor="a")

    assert added == 1
    assert prd_svc.completion(db, approved.id)["answers"] == 1
    # seq keeps advancing globally, so ordering and identity are unaffected.
    assert [t.seq for t in prd_svc.grill_turns(db, approved.id)] == [0, 1, 2, 3, 4]


def test_replaying_the_full_history_does_not_duplicate_it(db, approved):
    """A client that posts everything it has ever seen must not re-append the pre-window
    turns — the windowed suffix maths has to stay idempotent against that."""
    _rebaseline_requested(db, approved)
    everything = prd_svc.grill_history(db, approved.id)  # unwindowed, on purpose
    prd_svc.record_grill_turns(db, approved.id, everything, via="agent", actor="a")

    assert len(prd_svc.grill_turns(db, approved.id)) == 4


# ---- a PRD that never rebaselined is unaffected -------------------------------------------
def test_a_first_grill_sees_its_whole_conversation(db):
    prd = prd_svc.create_prd(db, title="Fresh", project_id="core", body=BODY)
    _answer(db, prd, "An answer.")

    assert prd_svc.grill_window(db, prd.id) == 0
    assert prd_svc.completion(db, prd.id)["answers"] == 1
