"""AL-96: PRD sections are classified before they become work.

Found by dogfooding: decompose_prd proposed "Implement: Problem" / "Implement: Goals"
and prd_coverage reported those prose sections as gaps, so a fully-covered PRD read as
half-covered. Framing sections describe the work; they aren't work.
"""
import pytest

from app.services.prds import is_implementable_section

BODY = """## Problem

Users can't do the thing.

## Goals

- Let them do the thing.

## Non-goals (v1)

- Not doing the other thing.

## Widget API

Build the widget endpoints.

## Auditing

Record every widget change.

## Success criteria

- Users do the thing.
"""


@pytest.mark.parametrize("title", [
    "Problem", "Goals", "Non-goals", "Non-goals (v1)", "NON GOALS", "non_goals",
    "Success criteria", "Success Metrics", "Out of scope", "Background", "Context",
    "Overview", "Motivation", "Summary", "Open questions", "Appendix", "Glossary",
    "References", "Prior art",
])
def test_prose_sections_are_not_implementable(title):
    assert is_implementable_section(title) is False


@pytest.mark.parametrize("title", [
    "Widget API", "Auditing", "Registration model", "Admin console",
    "Admin visibility (isolation boundary)", "Platform invites",
    "Additional-org requests & entitlement", "Data model", "Migration",
])
def test_buildable_sections_are_implementable(title):
    assert is_implementable_section(title) is True


def _make_prd(client, auth):
    r = client.post("/api/prds", json={"title": "Widget PRD", "body": BODY, "project_id": "core"},
                    headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_decompose_skips_prose_sections(client, auth):
    """The headline fix: only buildable sections become proposals."""
    prd_id = _make_prd(client, auth)
    proposals = client.post(f"/api/prds/{prd_id}/decompose", headers=auth).json()["proposals"]
    sections = [p["section"] for p in proposals]
    assert sections == ["Widget API", "Auditing"]
    assert not any("Implement: Problem" == p["title"] for p in proposals)


def test_decompose_can_opt_into_prose(client, auth):
    """Escape hatch for a PRD that genuinely uses a framing heading for scope."""
    prd_id = _make_prd(client, auth)
    proposals = client.post(f"/api/prds/{prd_id}/decompose?include_prose=true",
                            headers=auth).json()["proposals"]
    sections = [p["section"] for p in proposals]
    assert "Problem" in sections and "Widget API" in sections


def test_coverage_does_not_report_prose_as_gaps(client, auth):
    prd_id = _make_prd(client, auth)
    cov = client.get(f"/api/prds/{prd_id}/coverage", headers=auth).json()
    assert set(cov["gaps"]) == {"Widget API", "Auditing"}
    assert cov["section_count"] == 6          # every heading, for continuity
    assert cov["implementable_sections"] == 2  # the buildable denominator
    prose = next(s for s in cov["sections"] if s["section"] == "Problem")
    assert prose["implementable"] is False and prose["gap"] is False


def test_full_coverage_reads_as_no_gaps(client, auth):
    """A PRD whose buildable sections are all tracked has zero gaps — previously the
    prose sections kept it looking permanently incomplete."""
    prd_id = _make_prd(client, auth)
    created = client.post(f"/api/prds/{prd_id}/decompose?create=true", headers=auth).json()["created"]
    assert len(created) == 2
    cov = client.get(f"/api/prds/{prd_id}/coverage", headers=auth).json()
    assert cov["gaps"] == []
    assert cov["sections_with_tasks"] == cov["implementable_sections"] == 2


def test_decompose_create_makes_only_real_tasks(client, auth):
    prd_id = _make_prd(client, auth)
    client.post(f"/api/prds/{prd_id}/decompose?create=true", headers=auth)
    titles = [i["title"] for i in client.get("/api/items?project_id=core", headers=auth).json()
              if i.get("prd_id") == prd_id]
    assert sorted(titles) == ["Implement: Auditing", "Implement: Widget API"]
