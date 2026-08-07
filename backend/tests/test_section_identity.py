"""Section identity, rename detection, and mechanical drift (AL-240 / PRD-12).

Baselines hash per section so invalidation is scoped to what actually changed. Whole-body
hashing would invalidate every classification beneath a typo fix — making the correct
behaviour painful and the wrong one convenient, which is how a feature gets routed around.

That makes section IDENTITY load-bearing. If identity were the title, renaming a section
would read as **dropped + added** in the close report, handing a PM a false "this was
dropped" entry in the one artifact they are meant to act on. So a body that survives under
a new title is a rename, and its classifications survive with it.
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


A = "## Scope\n\nOut of scope: hosted mode.\n\n## Failures\n\nRetry once, then surface.\n"


# ---- the failure this exists to prevent -------------------------------------------------
def test_a_rename_is_not_a_drop(db):
    """The whole point. A PM reading "Scope was dropped" acts on it — and would be acting
    on a heading edit."""
    renamed = A.replace("## Scope", "## Scope and boundaries")
    d = prd_svc.diff_sections(A, renamed)

    assert d["renamed"] == [("Scope", "Scope and boundaries")]
    assert d["removed"] == [] and d["added"] == []


def test_a_typo_fix_does_not_invalidate_its_neighbours(db):
    """Per-section hashing, stated as the behaviour that matters: editing one section
    leaves every other section's classifications intact."""
    edited = A.replace("Retry once, then surface.", "Retry once, then surface the error.")
    d = prd_svc.diff_sections(A, edited)

    assert d["modified"] == ["Failures"]
    assert d["unchanged"] == ["Scope"]


def test_reflowing_text_is_not_a_content_change(db):
    """Whitespace is normalised — rewrapping a paragraph did not change the intent."""
    reflowed = A.replace("Out of scope: hosted mode.", "Out of scope:\n  hosted   mode.")
    assert prd_svc.diff_sections(A, reflowed)["unchanged"] == ["Failures", "Scope"]


def test_wording_changes_are_content_changes(db):
    """The line normalisation must not cross. Wording IS the intent; a spec that changed
    its words changed."""
    reworded = A.replace("Out of scope: hosted mode.", "Out of scope: hosted mode and CI.")
    assert prd_svc.diff_sections(A, reworded)["modified"] == ["Scope"]


# ---- real additions and removals still register ------------------------------------------
def test_a_new_section_is_an_addition(db):
    added = A + "\n## Contracts\n\nJSON-RPC over POST.\n"
    d = prd_svc.diff_sections(A, added)
    assert d["added"] == ["Contracts"] and d["renamed"] == []


def test_a_deleted_section_is_a_removal(db):
    without = "## Scope\n\nOut of scope: hosted mode.\n"
    d = prd_svc.diff_sections(A, without)
    assert d["removed"] == ["Failures"] and d["renamed"] == []


def test_a_duplicated_body_under_a_new_title_is_not_a_rename(db):
    """The original title is still present, so nothing moved — this is a copy, and
    calling it a rename would silently drop the addition from the report."""
    copied = A + "\n## Failures (copy)\n\nRetry once, then surface.\n"
    d = prd_svc.diff_sections(A, copied)
    assert d["added"] == ["Failures (copy)"] and d["renamed"] == []


def test_rename_and_edit_together_reports_as_remove_plus_add(db):
    """The ambiguity this design cannot escape, pinned rather than hidden.

    A section renamed AND rewritten has nothing anchoring it, so it is indistinguishable
    from a drop plus an add. Reporting it as remove + add is the honest reading: guessing
    a match would sometimes hide a genuinely dropped section, which is the worse error.

    Closing this needs stable per-section IDs assigned at baseline time — AL-240's stated
    fallback, worth building only if this proves insufficient in practice."""
    both = A.replace("## Scope\n\nOut of scope: hosted mode.",
                     "## Boundaries\n\nOut of scope: hosted mode and CI.")
    d = prd_svc.diff_sections(A, both)

    assert d["renamed"] == []
    assert d["removed"] == ["Scope"] and d["added"] == ["Boundaries"]


# ---- drift against the governing baseline -------------------------------------------------
def _approved(db, body):
    prd = prd_svc.create_prd(db, title="Spec", project_id="core", body=body)
    prd_svc.record_grill_turns(db, prd.id, [{"role": "agent", "text": "Q?"},
                                            {"role": "user", "text": "An answer."}])
    for name in prd_svc.DIMENSIONS:
        prd_svc.set_dimension(db, prd.id, name, "resolved")
    prd_svc.sync_status(db, prd)
    return prd


def test_an_unapproved_prd_is_not_reported_as_zero_drift(db):
    """"No drift" and "nothing to drift from" are different facts. Reporting the second
    as the first is the misleading green this whole PRD exists to stop."""
    prd = prd_svc.create_prd(db, title="Draft", project_id="core", body=A)
    out = prd_svc.baseline_drift(db, prd)
    assert out["governed"] is False
    assert "drifted_sections" not in out


def test_an_untouched_approved_prd_has_no_drift(db):
    prd = _approved(db, A)
    out = prd_svc.baseline_drift(db, prd)
    assert out["governed"] is True and out["drifted_sections"] == 0


def test_a_post_approval_edit_shows_as_drift(db):
    """The baseline does not move, so the edit is measurable — which is the entire
    mechanism AL-239's load-bearing rule was protecting."""
    prd = _approved(db, A)
    prd_svc.update_prd(db, prd.id, body=A.replace("hosted mode.", "hosted mode and CI."))

    out = prd_svc.baseline_drift(db, prd)
    assert out["modified"] == ["Scope"] and out["drifted_sections"] == 1
    assert out["baseline_version"] == "v1.0"


def test_a_rename_does_not_count_as_drift(db):
    """The intent did not move, only its label. Counting it would make the drift total
    noise wearing a serious face — the AL-96 trust failure repeating."""
    prd = _approved(db, A)
    prd_svc.update_prd(db, prd.id, body=A.replace("## Scope", "## Scope and boundaries"))

    out = prd_svc.baseline_drift(db, prd)
    assert out["renamed"] == [("Scope", "Scope and boundaries")]
    assert out["drifted_sections"] == 0


def test_drift_is_readable_over_the_api(client, auth, db):
    prd = _approved(db, A)
    prd_svc.update_prd(db, prd.id, body=A + "\n## Extra\n\nNew scope.\n")

    out = client.get(f"/api/prds/{prd.id}/drift", headers=auth).json()
    assert out["governed"] is True and out["added"] == ["Extra"]
    assert out["drifted_sections"] == 1
