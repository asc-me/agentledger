"""The completion standard: four dimensions, three outcomes (AL-297 / PRD-15 D1).

"The grill ran out of objections" cannot mean whatever the configured chat model happens
to feel, or `approved` denotes something different on every instance and PRD-12's
baselines stop being comparable to each other. This is that standard, and the rules that
make it non-negotiable.

AL-298 wires the model to produce these classifications. Here the outcomes are set
directly, so the STANDARD is tested independently of whatever ends up judging against it
— which is the point of defining it separately.
"""
import pytest

from app.services import prds as prd_svc


@pytest.fixture()
def prd(client, auth):
    r = client.post("/api/prds", json={"title": "Standard", "project_id": "core"}, headers=auth)
    return r.json()["id"]


@pytest.fixture()
def db(client):
    from app.db import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _answer(db, prd_id, text="A substantive answer."):
    """The floor requires a real answer on record, so most tests need one."""
    prd_svc.record_grill_turns(db, prd_id, [{"role": "agent", "text": "Q?"},
                                            {"role": "user", "text": text}])


def _resolve_all(db, prd_id, outcome="resolved"):
    for name in prd_svc.DIMENSIONS:
        prd_svc.set_dimension(db, prd_id, name, outcome)


# ---- the standard itself -------------------------------------------------------------
def test_the_four_dimensions_are_fixed(db):
    """Not configurable per PRD or per project. A per-type bar would mean `approved`
    denotes different things on different specs, which is exactly what makes cross-PRD
    drift reporting meaningless."""
    assert list(prd_svc.DIMENSIONS) == [
        "scope_edges", "failure_modes", "contracts", "open_decisions",
    ]
    assert prd_svc.OUTCOMES == ("resolved", "deferred", "unanswered")


def test_a_dimension_nobody_asked_about_is_unanswered(db, prd):
    """Absence is the honest default: nobody put the question. That is not the same as
    an author declining to answer it, which is why `deferred` is a separate outcome."""
    done = prd_svc.completion(db, prd)
    assert set(done["outstanding"]) == set(prd_svc.DIMENSIONS)
    assert done["complete"] is False


def test_completion_is_zero_unanswered(db, prd):
    _answer(db, prd)
    _resolve_all(db, prd)
    assert prd_svc.completion(db, prd)["complete"] is True


def test_one_unanswered_dimension_blocks_and_is_named(db, prd):
    """The caller has to be able to say what remains — a bare 'not complete' is not
    actionable, and AL-300 surfaces exactly this in its refusal."""
    _answer(db, prd)
    _resolve_all(db, prd)
    prd_svc.set_dimension(db, prd, "failure_modes", "unanswered")

    done = prd_svc.completion(db, prd)
    assert done["complete"] is False
    assert done["outstanding"] == ["failure_modes"]


# ---- deferral, the load-bearing outcome ----------------------------------------------
def test_a_deferred_dimension_completes(db, prd):
    """Real specs leave things open. "We are consciously not deciding X yet" is itself a
    decision, so it must not block — the failure this standard catches is an IMPLICIT
    non-answer counted as an answer, not an explicit deferral."""
    _answer(db, prd)
    _resolve_all(db, prd)
    prd_svc.set_dimension(db, prd, "open_decisions", "deferred",
                          note="pricing model deferred until after the beta")

    done = prd_svc.completion(db, prd)
    assert done["complete"] is True
    assert done["deferred"] == ["open_decisions"]


def test_a_deferral_keeps_its_reason_and_its_turn(db, prd):
    """The reason rides onto the baseline (AL-302), where later drift on that point reads
    as expected rather than as a surprise. A deferral with no reason recorded would be
    indistinguishable from a shrug."""
    _answer(db, prd)
    prd_svc.set_dimension(db, prd, "contracts", "deferred",
                          note="wire format settled after the prototype", turn_seq=1)
    d = prd_svc.completion(db, prd)["dimensions"]["contracts"]
    assert d["outcome"] == "deferred"
    assert "prototype" in d["note"]
    assert d["turn_seq"] == 1


# ---- the floor ------------------------------------------------------------------------
def test_a_grill_with_no_answers_is_never_complete(db, prd):
    """The one rule no model can override. Without it an empty conversation could be
    graded straight to approved, which would make the whole standard theatre."""
    _resolve_all(db, prd)  # every dimension marked resolved...
    done = prd_svc.completion(db, prd)
    assert done["answers"] == 0
    assert done["outstanding"] == []
    assert done["complete"] is False, "no recorded answer must never complete"


def test_questions_alone_do_not_count_as_engagement(db, prd):
    """A grill that asked four questions and got nothing back is not a grilled PRD."""
    prd_svc.record_grill_turns(db, prd, [{"role": "agent", "text": "Q1?"},
                                         {"role": "agent", "text": "Q2?"}])
    _resolve_all(db, prd)
    assert prd_svc.completion(db, prd)["complete"] is False


# ---- writing outcomes ------------------------------------------------------------------
def test_an_outcome_is_revised_not_stacked(db, prd):
    """A later round changes the verdict on a dimension; two rows for one dimension would
    make 'what is the outcome' ambiguous."""
    _answer(db, prd)
    prd_svc.set_dimension(db, prd, "scope_edges", "unanswered")
    prd_svc.set_dimension(db, prd, "scope_edges", "resolved", note="local instance only")
    d = prd_svc.completion(db, prd)["dimensions"]["scope_edges"]
    assert d["outcome"] == "resolved" and d["note"] == "local instance only"


@pytest.mark.parametrize("bad", [("nonsense", "resolved"), ("scope_edges", "maybe")])
def test_unknown_dimensions_and_outcomes_are_refused(db, prd, bad):
    """Fail loudly rather than silently recording a value nothing will ever read —
    a typo'd dimension would leave the real one `unanswered` forever."""
    with pytest.raises(ValueError):
        prd_svc.set_dimension(db, prd, bad[0], bad[1])


# ---- exposed where the caller needs it -------------------------------------------------
def test_the_grill_endpoint_reports_completion(client, auth, db, prd):
    """One call answers both "what was said" and "is it finished" — AL-300 derives status
    from exactly this payload."""
    _answer(db, prd)
    _resolve_all(db, prd)
    prd_svc.set_dimension(db, prd, "contracts", "deferred", note="after the prototype")

    state = client.get(f"/api/prds/{prd}/grill", headers=auth).json()
    assert state["complete"] is True
    assert state["deferred"] == ["contracts"]
    assert state["dimensions"]["scope_edges"]["outcome"] == "resolved"
    assert state["outstanding"] == []
