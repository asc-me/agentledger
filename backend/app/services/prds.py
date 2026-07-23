"""PRD tracker service (Phase 3): CRUD, version snapshots, item links, AI commands."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from collections import Counter

from app.config import settings
from app.models import Prd, PrdVersion
from app.providers import get_chat_model
from app.services import items as items_svc

STATUSES = ["draft", "review", "approved"]

TEMPLATES: dict[str, str] = {
    "blank": "# {title}\n\n",
    "standard": (
        "# {title}\n\n"
        "## Overview\n\n_What is this and why does it matter?_\n\n"
        "## Goals\n- \n\n"
        "## Non-Goals\n- \n\n"
        "## Key Features\n- \n\n"
        "## Success Metrics\n- \n\n"
        "## Risks & Open Questions\n- \n"
    ),
}


def next_prd_id(db: Session) -> str:
    ids = db.scalars(select(Prd.id)).all()
    nums = [int(m.group(1)) for i in ids if (m := re.match(r"PRD-(\d+)", i))]
    return f"PRD-{(max(nums) + 1) if nums else 1}"


def _bump(version: str) -> str:
    m = re.match(r"v(\d+)\.(\d+)", version or "v0.0")
    if not m:
        return "v0.1"
    return f"v{m.group(1)}.{int(m.group(2)) + 1}"


def list_prds(db: Session, project_id: str | None = None) -> list[Prd]:
    stmt = select(Prd)
    if project_id:
        stmt = stmt.where(Prd.project_id == project_id)
    return list(db.scalars(stmt.order_by(Prd.updated_at.desc())).all())


def get_prd(db: Session, prd_id: str) -> Prd | None:
    return db.get(Prd, prd_id)


def create_prd(
    db: Session,
    *,
    title: str,
    template: str = "standard",
    project_id: str = "core",
    body: str | None = None,
) -> Prd:
    # An imported markdown body wins over the template.
    imported = body is not None
    if imported:
        content = body
        note = "Imported from markdown."
    else:
        content = TEMPLATES.get(template, TEMPLATES["blank"]).format(title=title)
        note = "Initial draft."
    prd = Prd(id=next_prd_id(db), project_id=project_id, title=title, status="draft",
              version="v0.1", body=content, linked=[], updated="just now")
    db.add(prd)
    db.flush()
    db.add(PrdVersion(prd_id=prd.id, version="v0.1", date="just now", note=note, body=content))
    db.commit()
    db.refresh(prd)
    return prd


def update_prd(db: Session, prd_id: str, **fields) -> Prd | None:
    prd = db.get(Prd, prd_id)
    if prd is None:
        return None
    if fields.get("status") is not None and fields["status"] not in STATUSES:
        raise ValueError(f"invalid status: {fields['status']}")
    for key in ("title", "status", "body"):
        if fields.get(key) is not None:
            setattr(prd, key, fields[key])
    prd.updated = "just now"
    db.commit()
    db.refresh(prd)
    return prd


def create_version(db: Session, prd_id: str, note: str = "") -> Prd | None:
    """Snapshot the current body as a new version and bump the version number."""
    prd = db.get(Prd, prd_id)
    if prd is None:
        return None
    prd.version = _bump(prd.version)
    db.add(PrdVersion(prd_id=prd.id, version=prd.version, date="just now",
                      note=note or "Version snapshot.", body=prd.body))
    prd.updated = "just now"
    db.commit()
    db.refresh(prd)
    return prd


def link_item(db: Session, prd_id: str, item_id: str, add: bool = True) -> Prd | None:
    prd = db.get(Prd, prd_id)
    if prd is None:
        return None
    linked = list(prd.linked or [])
    if add and item_id not in linked:
        linked.append(item_id)
    elif not add and item_id in linked:
        linked.remove(item_id)
    prd.linked = linked
    db.commit()
    db.refresh(prd)
    return prd


# ---- AI commands ----
_COMMANDS = {
    "expand": "Expand the section under the cursor into 1-2 well-written paragraphs. Return only the new markdown.",
    "risks": "Generate a '## Risks & Open Questions' markdown section (3-5 bullets) for this PRD. Return only that section.",
    "summarize": "Write a 2-3 sentence executive summary of this PRD as markdown. Return only the summary.",
    "grill": (
        "You are grilling the author to sharpen this PRD before anyone builds it. Ask 5-8 relentless, "
        "specific clarifying questions that surface unstated assumptions, scope boundaries, failure "
        "modes, data shapes, and decisions still open. Strongly prefer LOW-FIDELITY questions "
        "answerable in words (routes, contracts, error behavior, acceptance criteria) over HIGH-FIDELITY "
        "ones that would need a prototype to answer. Return ONLY a markdown bullet list of questions — "
        "no preamble, no answers."
    ),
}


def ai_command(db: Session, prd_id: str, command: str) -> str:
    prd = db.get(Prd, prd_id)
    if prd is None:
        raise ValueError(f"prd not found: {prd_id}")
    if command not in _COMMANDS:
        raise ValueError(f"unknown command: {command}")

    if settings.chat_provider == "stub":
        return _stub_command(command, prd)

    return get_chat_model().chat(
        system="You are a precise PRD writing assistant. Return only the requested markdown snippet.",
        context=prd.body,
        question=_COMMANDS[command],
    )


def _stub_command(command: str, prd: Prd) -> str:
    """Deterministic, offline output so the editor is useful without a provider."""
    if command == "grill":
        secs = parse_sections(prd.body)
        thin = [s for s in secs if len(section_bodies(prd.body).get(s, "").strip()) < 40]
        lines = [
            "- What is the single most important outcome, and how will you know it's met?",
            "- Which cases are explicitly out of scope for the first version?",
            "- What should happen on the failure path (bad input, missing data, timeout)?",
            "- What is the exact shape of the inputs and outputs at the boundary?",
            "- Which of these decisions actually need a prototype to answer, vs. can be settled now?",
        ]
        for s in thin[:3]:
            lines.append(f"- Section **{s}** is thin — what belongs there?")
        return "\n".join(lines) + (
            "\n\n_(Local stub questions. Set CHAT_PROVIDER=ollama|anthropic for a real grill.)_\n"
        )
    if command == "risks":
        return (
            "## Risks & Open Questions\n"
            "- Scope creep beyond the stated non-goals.\n"
            "- Dependencies on linked items may slip the timeline.\n"
            "- Success metrics need a measurement plan.\n"
            "\n_(Generated by the local stub. Set CHAT_PROVIDER=ollama or anthropic for real drafting.)_\n"
        )
    if command == "summarize":
        first = next((ln for ln in prd.body.splitlines() if ln and not ln.startswith("#")), "")
        return f"**Summary:** {prd.title} — {first or 'no overview yet'}. _(stub summary)_\n"
    return (
        "\n_Expanded draft placeholder. Configure a chat provider (CHAT_PROVIDER=ollama|anthropic) "
        "to generate real prose here._\n"
    )


# ---- Spec-to-task traceability & coverage (feature D) ----

_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def parse_sections(body: str) -> list[str]:
    """Level-2 headings (`## …`) — the PRD's sections, in order."""
    return [m.group(1).strip() for m in _SECTION_RE.finditer(body or "")]


def section_bodies(body: str) -> dict[str, str]:
    """Map each `## section` to the markdown beneath it (until the next `## `)."""
    out: dict[str, str] = {}
    cur, buf = None, []
    for line in (body or "").splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if cur is not None:
                out[cur] = "\n".join(buf).strip()
            cur, buf = m.group(1).strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    return out


def coverage(db: Session, prd: Prd) -> dict:
    """Per-section task rollup + gaps for a PRD."""
    sections = parse_sections(prd.body)
    items = [it for it in items_svc.list_items(db, project_id=prd.project_id) if it.prd_id == prd.id]
    by_section: dict[str, list] = {}
    for it in items:
        by_section.setdefault(it.prd_section or "", []).append(it)
    per = []
    for s in sections:
        its = by_section.get(s, [])
        counts = Counter(it.status for it in its)
        per.append({
            "section": s,
            "item_count": len(its),
            "done": counts.get("done", 0),
            "by_status": dict(counts),
            "gap": len(its) == 0,
            "item_ids": [it.id for it in its],
        })
    total = len(items)
    done = sum(1 for it in items if it.status == "done")
    return {
        "prd_id": prd.id, "title": prd.title, "status": prd.status,
        "sections": per,
        "section_count": len(sections),
        "sections_with_tasks": sum(1 for p in per if not p["gap"]),
        "gaps": [p["section"] for p in per if p["gap"]],
        "total_items": total, "done_items": done,
        "percent_done": round(100 * done / total) if total else 0,
    }


def decompose(db: Session, prd: Prd, create: bool = False) -> dict:
    """Propose one tracked task per un-covered section (gap). With create=True, creates them
    as backlog items linked to the PRD + section, so the spec drives the tracker."""
    cov = coverage(db, prd)
    bodies = section_bodies(prd.body)
    proposals = [
        {"section": p["section"], "title": f"Implement: {p['section']}",
         "description": bodies.get(p["section"], "").strip()}
        for p in cov["sections"] if p["gap"]
    ]
    created = []
    if create:
        for pr in proposals:
            item = items_svc.create_item(
                db, title=pr["title"], description=pr["description"],
                project_id=prd.project_id, status="backlog", tags=["prd"],
                prd_id=prd.id, prd_section=pr["section"],
                reporter={"name": "Spec", "handle": "prd", "avatar": "#c9b8ff"},
            )
            created.append(item.id)
    return {"prd_id": prd.id, "proposals": proposals, "created": created}
