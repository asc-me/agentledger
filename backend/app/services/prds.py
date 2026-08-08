"""PRD tracker service (Phase 3): CRUD, version snapshots, item links, AI commands."""
from __future__ import annotations

import hashlib
import json
import logging
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from collections import Counter

from app.models import GrillDimension, GrillTurn, Prd, PrdVersion
from app.services import items as items_svc
from app.services import keys
from app.services import events as events_svc
from app.services import platform as platform_svc

logger = logging.getLogger("graphban.prds")

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


def _bump(version: str) -> str:
    m = re.match(r"v(\d+)\.(\d+)", version or "v0.0")
    if not m:
        return "v0.1"
    return f"v{m.group(1)}.{int(m.group(2)) + 1}"


def _promote(version: str) -> str:
    """Approval promotes v0.x to v1.0 (AL-239). `_bump` only ever increments minor, so it
    cannot express "this stopped being a draft" — which is the whole point of the moment.
    An already-major version bumps minor instead: a re-approval is v1.1, not a second v1.0."""
    m = re.match(r"v(\d+)\.(\d+)", version or "v0.0")
    if not m:
        return "v1.0"
    major = int(m.group(1))
    return "v1.0" if major == 0 else f"v{major}.{int(m.group(2)) + 1}"


def list_prds(db: Session, project_id: str | None = None) -> list[Prd]:
    stmt = select(Prd)
    if project_id:
        stmt = stmt.where(Prd.project_id == project_id)
    return list(db.scalars(stmt.order_by(Prd.updated_at.desc())).all())


def get_prd(db: Session, prd_id: str) -> Prd | None:
    return db.get(Prd, keys.resolve_prd(db, prd_id) or prd_id)


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
    # See items.create_item: the id is frozen identity, `number` renders the key.
    prd_id, number = keys.mint(db, project_id, "prd")
    prd = Prd(id=prd_id, number=number, project_id=project_id, title=title, status="draft",
              version="v0.1", body=content, linked=[], updated="just now")
    db.add(prd)
    db.flush()
    db.add(PrdVersion(prd_id=prd.id, version="v0.1", date="just now", note=note, body=content))
    db.commit()
    db.refresh(prd)
    return prd


class ApprovalNotEarned(ValueError):
    """`approved` was set by hand instead of reached by finishing the grill (AL-300)."""


def update_prd(db: Session, prd_id: str, **fields) -> Prd | None:
    prd = db.get(Prd, keys.resolve_prd(db, prd_id) or prd_id)
    if prd is None:
        return None
    if fields.get("status") is not None and fields["status"] not in STATUSES:
        raise ValueError(f"invalid status: {fields['status']}")
    # `approved` is REACHED, not set (PRD-15). Refusing here rather than in the routers
    # covers REST and MCP at once — and this call is precisely how an agent could
    # otherwise freeze an intent baseline (AL-239) that nobody had read.
    #
    # Setting it to the value it already holds is allowed: a client echoing back an
    # unchanged status is not trying to approve anything, and 422-ing that would break
    # every "save the whole object" caller for no safety gain.
    if fields.get("status") == "approved" and prd.status != "approved":
        done = completion(db, prd.id)
        raise ApprovalNotEarned(
            "approved is reached by finishing the grill, not set directly. "
            + (f"Still unanswered: {', '.join(done['outstanding'])}. "
               if done["outstanding"] else "No answers are recorded yet. ")
            + "Answer the open dimensions (or defer one explicitly) and it approves itself."
        )
    # Refuse the edit that introduces the violation, rather than letting the author
    # finish a whole grill and be rejected at the end (GRPH-318).
    if fields.get("body") is not None:
        added = rebaseline_added_sections(db, prd, fields["body"])
        if added:
            raise RebaselineExpandsScope(
                "a rebaseline cannot add sections: " + ", ".join(repr(a) for a in added)
                + ". Rebaselining adjusts a PRD to match reality; new scope belongs in a "
                "sub-PRD or a follow-up PRD linked back to this one."
            )
    for key in ("title", "status", "body"):
        if fields.get(key) is not None:
            setattr(prd, key, fields[key])
    prd.updated = "just now"
    db.commit()
    db.refresh(prd)
    return prd


def create_version(db: Session, prd_id: str, note: str = "") -> Prd | None:
    """Snapshot the current body as a new version and bump the version number."""
    prd = db.get(Prd, keys.resolve_prd(db, prd_id) or prd_id)
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
    prd = db.get(Prd, keys.resolve_prd(db, prd_id) or prd_id)
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
    prd = db.get(Prd, keys.resolve_prd(db, prd_id) or prd_id)
    if prd is None:
        raise ValueError(f"prd not found: {prd_id}")
    if command not in _COMMANDS:
        raise ValueError(f"unknown command: {command}")

    provider, chat = platform_svc.resolve_chat(db, prd.project_id)
    if provider == "stub":
        return _stub_command(command, prd)

    return chat.chat(
        system="You are a precise PRD writing assistant. Return only the requested markdown snippet.",
        context=prd.body,
        question=_COMMANDS[command],
    )


# ---- Interactive grill mode (AL-67) ----

GRILL_CHAT_SYSTEM = (
    "You are grilling the author to sharpen a PRD before anyone builds it. Based on their "
    "latest answer and the current PRD, ask 1-3 focused clarifying questions that surface "
    "unstated assumptions, scope edges, failure modes, contracts, and open decisions. Strongly "
    "prefer LOW-FIDELITY questions answerable in words over HIGH-FIDELITY ones that need a "
    "prototype (when a question is high-fidelity, say so and suggest prototyping it). Acknowledge "
    "a decision in one line, then keep grilling. Be terse. Do NOT rewrite the PRD here — only "
    "interrogate.\n"
    # AL-298: the grill has to be able to STOP. Until PRD-15 this said "keep grilling"
    # with no terminal state, so "all questions answered" could never become true and
    # approval-by-grilling was unreachable by construction.
    "When every one of scope edges, failure modes, contracts, and open decisions has "
    "either a substantive answer or an explicit decision to defer, say so plainly and "
    "stop asking — a finished grill is a result, not a failure to think of more "
    "questions. Deferring is a legitimate answer; hand-waving is not."
)

GRILL_APPLY_SYSTEM = (
    "You are updating a PRD to fold in the decisions reached during a grilling conversation. "
    "Rewrite the FULL PRD markdown body, integrating the author's answers into the appropriate "
    "`## ` sections and preserving structure and untouched sections. Return ONLY the updated "
    "markdown PRD body — no preamble, no fences."
)


def _transcript(history: list[dict]) -> str:
    lines = []
    for m in history or []:
        who = "Author" if m.get("role") == "user" else "Grill"
        text = (m.get("text") or "").strip()
        if text:
            lines.append(f"{who}: {text}")
    return "\n".join(lines)


def grill_context(prd: Prd, history: list[dict]) -> str:
    """Light-context grounding for a grill: the PRD itself + the conversation so far.
    Deliberately does NOT pull memory/code (that's the heavy-context code-chat path)."""
    parts = [f"PRD under review — {prd.title} ({prd.status}):", prd.body or "(empty)"]
    t = _transcript(history)
    if t:
        parts += ["", "Conversation so far:", t]
    return "\n".join(parts)


# ---- server-owned grill state (AL-296 / PRD-15 D4) ---------------------------------
# PRD-15 derives approval from whether the grill is finished, so the server has to own
# the conversation rather than receive it. These functions are the whole of that
# ownership; the completion standard (AL-297) reads them and adds nothing to the store.

def grill_turns(db: Session, prd_id: str) -> list[GrillTurn]:
    """The persisted conversation, oldest first."""
    return list(db.scalars(
        select(GrillTurn).where(GrillTurn.prd_id == prd_id).order_by(GrillTurn.seq)
    ).all())


def grill_history(db: Session, prd_id: str) -> list[dict]:
    """The conversation in the `{role, text}` shape the prompts and `_transcript` use,
    so a caller can drop the client-supplied transcript entirely."""
    return [{"role": t.role, "text": t.text} for t in grill_turns(db, prd_id)]


def record_grill_turns(
    db: Session, prd_id: str, history: list[dict],
    *, via: str = "", actor: str = "",
) -> int:
    """Append whatever part of `history` isn't recorded yet. Returns how many landed.

    The client posts the FULL transcript every round, so this appends only the suffix
    beyond what's stored — otherwise each round would duplicate every earlier one.

    Deliberately does NOT reconcile a divergent prefix. If a caller sends a shorter or
    edited history (a second tab, a lost session), the stored rounds stand and nothing
    is appended. Rewriting history to match the most recent caller would let a client
    silently erase answers that approval is derived from, which is a worse failure than
    a transcript that lags a confused client.
    """
    stored = db.scalar(
        select(func.count()).select_from(GrillTurn).where(GrillTurn.prd_id == prd_id)
    ) or 0
    added = 0
    for offset, message in enumerate(history[stored:]):
        text = (message.get("text") or "").strip()
        if not text:
            continue  # an empty turn is not a question and not an answer
        role = "user" if message.get("role") == "user" else "agent"
        db.add(GrillTurn(
            prd_id=prd_id,
            seq=stored + offset,
            role=role,
            text=text,
            # Only an ANSWER has a supplier; a question comes from the grill itself.
            via=via if role == "user" else "",
            actor=actor if role == "user" else "",
        ))
        added += 1
    if added:
        db.commit()
    return added


# ---- the completion standard (AL-297 / PRD-15 D1) -----------------------------------
# What "the grill ran out of objections" means. Fixed and named, because if it were left
# to whatever chat model is configured then `approved` would denote something different
# on every instance and PRD-12's baselines would stop being comparable to each other.
#
# The four dimensions are the ones GRILL_CHAT_SYSTEM already asks about, so this codifies
# existing behaviour rather than inventing a checklist.
DIMENSIONS: dict[str, str] = {
    "scope_edges": "What is explicitly out of scope for the first version?",
    "failure_modes": "What happens on the failure path — bad input, missing data, timeout?",
    "contracts": "What is the exact shape of the inputs and outputs at the boundary?",
    "open_decisions": "Which decisions are still open, and which need a prototype to settle?",
}

# `deferred` completes rather than blocks. Authors deferring is normal and healthy; the
# failure this standard exists to catch is an IMPLICIT non-answer being counted as an
# answer, which is precisely what having a separate name for deferral makes visible.
OUTCOMES = ("resolved", "deferred", "unanswered")
_BLOCKING = "unanswered"


def set_dimension(
    db: Session, prd_id: str, dimension: str, outcome: str,
    *, note: str = "", turn_seq: int | None = None, graded_by: str = "",
) -> GrillDimension:
    """Record one dimension's outcome. Idempotent per (prd, dimension) — a later round
    revises the verdict rather than stacking a second one."""
    if dimension not in DIMENSIONS:
        raise ValueError(f"unknown grill dimension: {dimension!r} (expected {sorted(DIMENSIONS)})")
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown grill outcome: {outcome!r} (expected {list(OUTCOMES)})")
    row = db.scalar(
        select(GrillDimension).where(
            GrillDimension.prd_id == prd_id, GrillDimension.dimension == dimension
        )
    )
    if row is None:
        row = GrillDimension(prd_id=prd_id, dimension=dimension, outcome=outcome)
        db.add(row)
    row.outcome = outcome
    row.note = note
    row.turn_seq = turn_seq
    row.graded_by = graded_by
    db.commit()
    db.refresh(row)
    return row


def completion(db: Session, prd_id: str) -> dict:
    """Is this PRD's grill finished, and if not, what is outstanding?

    Two rules, both deliberate:

    - **Completion is zero `unanswered`.** Deferrals do not block.
    - **A grill with no recorded answers is never complete**, whatever any model claims.
      Without this floor an empty conversation could be graded straight to approved,
      which is the one outcome that would make the whole standard theatre.
    """
    rows = {
        d.dimension: d
        for d in db.scalars(select(GrillDimension).where(GrillDimension.prd_id == prd_id)).all()
    }
    dimensions = {
        name: {
            "outcome": rows[name].outcome if name in rows else _BLOCKING,
            "note": rows[name].note if name in rows else "",
            "turn_seq": rows[name].turn_seq if name in rows else None,
            "graded_by": rows[name].graded_by if name in rows else "",
            "question": prompt,
        }
        for name, prompt in DIMENSIONS.items()
    }
    outstanding = sorted(n for n, d in dimensions.items() if d["outcome"] == _BLOCKING)
    answered = db.scalar(
        select(func.count()).select_from(GrillTurn).where(
            GrillTurn.prd_id == prd_id, GrillTurn.role == "user"
        )
    ) or 0
    return {
        "dimensions": dimensions,
        "outstanding": outstanding,
        "deferred": sorted(n for n, d in dimensions.items() if d["outcome"] == "deferred"),
        "answers": answered,
        "complete": bool(answered) and not outstanding,
    }


# ---- concluding the grill (AL-298 / PRD-15 D2) ---------------------------------------
# GRILL_CHAT_SYSTEM tells the model to "keep grilling", so the conversation could never
# end and "all questions answered" was never true. Two paths make it terminable.
#
# The classification is a SEPARATE call from the streamed conversation, not JSON smuggled
# into it. Streaming is for the author to read; classifying is state approval derives
# from, and mixing them would make a malformed token both a broken sentence and a lost
# outcome. Mirrors `memory._llm_judge`: focused prompt, defensive parse, None on failure.
# Built FROM `DIMENSIONS` rather than restating them. The first version of this prompt
# after the citation change described "four fixed dimensions" without naming any of them,
# so the model invented its own from the PRD's subject matter — `intent_baseline`,
# `coverage` — none of which matched, every verdict was discarded, and grading silently
# fell back to the stub. Deriving the list means the prompt cannot drift from the
# standard it is grading against; a test asserts every dimension appears.
GRILL_CLASSIFY_SYSTEM = (
    "You assess whether the AUTHOR HAS BEEN INTERROGATED on exactly these four "
    "dimensions, and no others:\n"
    + "".join(f"  - {name}: {question}\n" for name, question in DIMENSIONS.items())
    + "\nUse these exact keys. Do not invent dimensions from the document's subject "
    "matter.\n\n"
    "CRITICAL: the PRD's own text is the thing under question. It is NEVER evidence that "
    "a question was answered. However thoroughly the document covers a dimension, only "
    "something the AUTHOR SAID in the conversation can resolve it. A well-written PRD "
    "with no answers is `unanswered` on all four.\n\n"
    "For EACH dimension decide: `resolved` (an author answer substantively settled it), "
    "`deferred` (the author deliberately chose not to decide yet — legitimate), or "
    "`unanswered` (never put to them, answered evasively, or addressed only by the "
    "document itself). Hand-waving or 'we'll figure it out later' without explicitly "
    "choosing to defer is `unanswered`.\n\n"
    "For `resolved` and `deferred` you MUST name WHICH author answer settled it, by its "
    "number. If you cannot point at a specific answer, the honest verdict is "
    "`unanswered`.\n\n"
    "Respond with ONLY a compact JSON object whose keys are the four names above, each "
    'value {"outcome": "...", "note": "one short sentence saying what that answer '
    'settled", "answered_by": <answer number>}. Omit answered_by for `unanswered`.'
)


def _numbered_answers(history: list[dict]) -> list[str]:
    """The author's turns, in order. Citations index into this list (1-based)."""
    return [m["text"] for m in history if m.get("role") == "user" and (m.get("text") or "").strip()]


def _classify_context(prd: Prd, history: list[dict]) -> str:
    """Context for classification, which is NOT the context for conversation.

    `grill_context` leads with the PRD body, and that is exactly what went wrong the first
    time this ran for real: the model read a thorough document and reported that the
    author had explained failure modes and contracts, when the author had said nothing
    about either. It graded the artifact instead of the interrogation.

    So the body is labelled here as the thing under question, and the author's answers are
    presented as the only admissible evidence — numbered, so a verdict has to point at
    one."""
    answers = _numbered_answers(history)
    parts = [
        f"PRD UNDER QUESTION — {prd.title}. This document is what is being interrogated. "
        "It is NOT evidence that any question was answered.",
        prd.body or "(empty)",
        "",
        "AUTHOR'S ANSWERS — the only thing that can resolve a dimension:",
    ]
    parts += [f"[answer {i}] {a}" for i, a in enumerate(answers, 1)] or ["(none — the author has not answered anything)"]
    return "\n".join(parts)


def _validated(entry: dict, answers: list[str]) -> dict | None:
    """Accept a verdict only if it points at an author answer that exists.

    That single check buys the property this floor was built for: a model crediting the
    PRD's own prose cannot satisfy it, because the document is not an answer.

    It used to demand a verbatim quote as well. That was dropped — three separate bugs
    came from the validator disagreeing with how models render text (elided middles,
    added terminal stops, non-breaking hyphens for "-"), each rejecting a CORRECT verdict,
    and "text a model produces when quoting" is not a closed set. The quote never caught
    the failure people assume it does either: misattribution survives it, because a real
    quote can be filed under the wrong dimension.

    What replaces it is the note plus the answer number, which a reviewer reads against
    the answer itself. Same reviewability, no string matching.
    """
    outcome = str(entry.get("outcome", "")).strip().lower()
    if outcome not in OUTCOMES:
        return None
    note = str(entry.get("note", "")).strip()
    if outcome == "unanswered":
        return {"outcome": "unanswered", "note": note}

    try:
        idx = int(entry.get("answered_by"))
    except (TypeError, ValueError):
        return {"outcome": "unanswered", "note": "no answer cited for this dimension"}
    if not 1 <= idx <= len(answers):
        return {"outcome": "unanswered", "note": f"cited answer {idx} does not exist"}

    return {"outcome": outcome, "note": note, "answered_by": idx}


def _classify_dimensions(db: Session, prd: Prd, history: list[dict]) -> dict | None:
    """Ask the project's chat model to grade the four dimensions. Returns
    {dimension: {outcome, note, ...}}, or None when no real model is configured or the
    reply can't be parsed — the caller then falls back to the stub rule rather than
    guessing."""
    provider, chat = platform_svc.resolve_chat(db, prd.project_id)
    if provider == "stub":
        return None
    answers = _numbered_answers(history)
    if not answers:
        return None  # nothing citable exists; the floor in `completion` catches this too
    try:
        raw = chat.chat(
            system=GRILL_CLASSIFY_SYSTEM,
            context=_classify_context(prd, history),
            question="Classify the four dimensions. Name the answer number that settled "
                     "each one. Return only the JSON object.",
            # Deterministic: an identical transcript must yield an identical verdict.
            # Measured before this was set — three runs of the same input on the same
            # model gave two different completion states, so whether a PRD approved
            # depended on when the classifier happened to run.
            temperature=0,
        )
    except Exception:  # noqa: BLE001 — a model outage must not break the grill
        logger.exception("grill classify: chat call failed")
        return None
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    out: dict[str, dict] = {}
    for name in DIMENSIONS:
        entry = data.get(name)
        if not isinstance(entry, dict):
            continue
        verdict = _validated(entry, answers)
        if verdict is not None:
            out[name] = verdict
    return out or None


def _grader_id(db: Session, prd: Prd) -> str:
    """Which provider is standing behind these verdicts."""
    try:
        return platform_svc.resolve_chat(db, prd.project_id)[0] or "stub"
    except Exception:  # noqa: BLE001 — provenance must never break a grill
        return "unknown"


def _stub_classification(answers: int) -> dict:
    """The offline bar, and it is deliberately mechanical: the first `answers` dimensions
    count as resolved, in order.

    A stub cannot assess substance, so pretending it can would be worse than admitting
    it doesn't. The alternative — leaving the stub unable to conclude — would mean no PRD
    could ever be approved on the shipped default configuration, which breaks the
    zero-browser install. AL-299 records that the stub set the bar, so a reader can see
    which standard was actually applied.
    """
    names = list(DIMENSIONS)
    return {
        name: {"outcome": "resolved", "note": "stub: answer recorded, substance not assessed"}
        for name in names[:answers]
    }


def classify_grill(db: Session, prd: Prd) -> dict:
    """Grade the grill so far and record the outcomes. Returns the completion payload.

    Never downgrades an explicit `deferred` — an author's decision to leave something
    open is theirs, and a later round should not quietly convert it back into an open
    question just because the model didn't see the deferral restated."""
    history = grill_history(db, prd.id)
    answers = sum(1 for t in history if t["role"] == "user")
    verdicts = _classify_dimensions(db, prd, history)
    if verdicts is None:
        # No usable verdict. The stub's mechanical rule applies ONLY when the stub is
        # genuinely what this instance has — falling back to it after a REAL model failed
        # would quietly grade with a weaker bar than the one that just refused to answer,
        # and stamp `graded_by=stub` on a project that pays for a model. Nothing is
        # recorded; the next round tries again.
        if _grader_id(db, prd) != "stub":
            logger.warning("grill classify: unusable verdict for %s; leaving dimensions "
                           "unchanged rather than applying the offline bar", prd.id)
            return completion(db, prd.id)
        graded, grader = _stub_classification(answers), "stub"
    else:
        graded, grader = verdicts, _grader_id(db, prd)

    existing = {
        d.dimension: d.outcome
        for d in db.scalars(select(GrillDimension).where(GrillDimension.prd_id == prd.id)).all()
    }
    last_seq = len(history) - 1 if history else None
    for name, verdict in graded.items():
        if existing.get(name) == "deferred" and verdict["outcome"] != "deferred":
            continue
        note = verdict.get("note", "")
        if verdict.get("answered_by"):
            note = f"{note} — from answer {verdict['answered_by']}"
        set_dimension(db, prd.id, name, verdict["outcome"],
                      note=note, turn_seq=last_seq, graded_by=grader)
    # Approval is a consequence of the grill, so it lands here rather than waiting for
    # someone to notice the standard is met (AL-300).
    sync_status(db, prd)
    return completion(db, prd.id)


def section_digest(body: str) -> dict[str, str]:
    """`{section title: sha256 of its body}` — the unit invalidation is scoped to.

    Per section, not per body, because whole-body hashing would invalidate every
    classification beneath a typo fix. That makes the correct behaviour painful and the
    wrong one convenient, which is how a feature gets routed around.

    Whitespace is normalised so reflowing a paragraph is not a content change. Nothing
    else is: wording IS the intent, and a spec that changed its words changed.
    """
    return {
        title: hashlib.sha256(" ".join(text.split()).encode()).hexdigest()
        for title, text in section_bodies(body).items()
    }


def diff_sections(old_body: str, new_body: str) -> dict:
    """What changed between two specs, at section granularity.

    Returns `{unchanged, modified, renamed, added, removed}`. `renamed` carries
    `(old_title, new_title)` pairs.

    Rename detection is the whole point. If identity were the title, renaming a section
    would invalidate every classification beneath it AND read as **dropped + added** in
    the close report — handing a PM a false "this was dropped" entry in the one artifact
    they are meant to act on. So a body whose hash survives under a different title is a
    rename, and its classifications survive with it.

    The ambiguity this cannot escape: a section that was BOTH renamed and edited is
    indistinguishable from a drop plus an add, because nothing anchors it. It is reported
    as removed + added, which is the honest reading — pretending to match it would be
    guessing, and a wrong guess hides a real dropped section. AL-240's fallback of stable
    per-section IDs assigned at baseline time is what closes that, and it is only worth
    building if this proves insufficient in practice.
    """
    old, new = section_digest(old_body), section_digest(new_body)
    old_by_hash = {h: t for t, h in old.items()}

    unchanged = sorted(t for t in new if t in old and old[t] == new[t])
    modified = sorted(t for t in new if t in old and old[t] != new[t])

    renamed, added = [], []
    for title in sorted(set(new) - set(old)):
        prior = old_by_hash.get(new[title])
        if prior is not None and prior not in new:
            renamed.append((prior, title))   # same body, new title
        else:
            added.append(title)

    renamed_from = {a for a, _ in renamed}
    removed = sorted(set(old) - set(new) - renamed_from)
    return {"unchanged": unchanged, "modified": modified,
            "renamed": renamed, "added": added, "removed": removed}


def intent_diff(db: Session, prd: Prd) -> dict:
    """What a rebaseline would actually change, section by section (GRPH-317).

    PRD-12 is blunt about why this exists: without it "the human ratifies a decision
    already made in chat without seeing its effect on the spec, and it is rubber-stamping
    with an audit trail." The approver has to see the change, not be told there is one.

    Per SECTION, not whole-body, for the same reason baselines hash that way: a
    whole-body diff drowns a real scope change in the noise of a typo fix, and a reader
    who has to hunt for the important line will stop reading. Only sections that actually
    changed carry line detail; unchanged ones are named and left alone.

    `governed: False` when there is no baseline — nothing to diff against, which is a
    different statement from "nothing changed".
    """
    base = baseline_of(db, prd.id)
    if base is None:
        return {"governed": False, "baseline_version": None, "sections": [], "pending": None}

    d = diff_sections(base.body, prd.body)
    old_bodies, new_bodies = section_bodies(base.body), section_bodies(prd.body)
    renamed_from = {new: old for old, new in d["renamed"]}

    sections = []
    for title in parse_sections(prd.body):
        if title in d["modified"]:
            state = "modified"
        elif title in renamed_from:
            state = "renamed"
        elif title in d["added"]:
            state = "added"
        else:
            state = "unchanged"
        entry = {"title": title, "state": state}
        if state == "renamed":
            entry["was"] = renamed_from[title]
        if state in ("modified", "added"):
            before = old_bodies.get(renamed_from.get(title, title), "") if state == "modified" else ""
            entry["lines"] = _line_diff(before, new_bodies.get(title, ""))
        sections.append(entry)

    # A removed section has no place in the new body's order, so it is appended — but it
    # carries its old text, because "this was deleted" is the single most consequential
    # thing an approver can miss.
    for title in d["removed"]:
        sections.append({"title": title, "state": "removed",
                         "lines": _line_diff(old_bodies.get(title, ""), "")})

    return {
        "governed": True,
        "baseline_version": base.version,
        "pending": prd.pending_rebaseline,
        "sections": sections,
        "changed": len(d["modified"]) + len(d["added"]) + len(d["removed"]) + len(d["renamed"]),
    }


def _line_diff(before: str, after: str) -> list[dict]:
    """Line-level changes, as `{op, text}` with op in `+ - =`.

    Context lines are kept so a change reads in place rather than as a pile of orphaned
    additions. Nothing is truncated: a diff that hides part of the change is worse than
    a long one, because the reader believes they have seen everything."""
    import difflib

    out = []
    for line in difflib.ndiff(before.splitlines(), after.splitlines()):
        op, text = line[:2], line[2:]
        if op == "+ ":
            out.append({"op": "+", "text": text})
        elif op == "- ":
            out.append({"op": "-", "text": text})
        elif op == "  ":
            out.append({"op": "=", "text": text})
        # "? " hint lines are difflib's intra-line markers — noise for a human reader.
    return out


def baseline_drift(db: Session, prd: Prd) -> dict:
    """How the living body has diverged from the GOVERNING baseline.

    This is the mechanical half of drift and the half that works with no chat provider
    at all: it counts structural change against agreed intent and expresses no opinion
    about whether that change was good.

    A PRD with no baseline returns `governed: False` rather than a zero. Zero drift and
    "never had agreed intent to drift from" are different facts, and reporting the second
    as the first is exactly the misleading green PRD-12 exists to stop.
    """
    base = baseline_of(db, prd.id)
    if base is None:
        return {"governed": False, "baseline_version": None}
    d = diff_sections(base.body, prd.body)
    return {
        "governed": True,
        "baseline_version": base.version,
        **d,
        # Renames are deliberately NOT counted: the intent did not move, only its label.
        "drifted_sections": len(d["modified"]) + len(d["added"]) + len(d["removed"]),
    }


def baseline_of(db: Session, prd_id: str) -> PrdVersion | None:
    """The agreed spec for this PRD, or None if it has never been approved. The latest
    baseline wins — a re-approval supersedes, and the earlier ones stay as history."""
    return db.scalars(
        select(PrdVersion)
        .where(PrdVersion.prd_id == prd_id, PrdVersion.is_baseline.is_(True))
        .order_by(PrdVersion.created_at.desc(), PrdVersion.id.desc())
    ).first()


def freeze_baseline(db: Session, prd: Prd) -> PrdVersion:
    """Snapshot the spec as agreed, and promote the version (AL-239).

    Called at approval — since PRD-15, when the grill concludes. Records the
    per-dimension outcomes alongside the body so a deferral is visible on the baseline
    itself.

    Idempotent per body: re-approving an unchanged spec returns the existing baseline
    rather than stacking duplicates, so a status recomputation can never quietly mint a
    second "original intent".
    """
    existing = baseline_of(db, prd.id)
    pending = prd.pending_rebaseline or {}
    # An unchanged body re-approving is a no-op — EXCEPT when a rebaseline was requested,
    # where the point may be that the intent was reaffirmed after being questioned. Even
    # then an identical body earns no new baseline; there is nothing new to freeze.
    if existing is not None and existing.body == prd.body:
        if pending:
            prd.pending_rebaseline = None
            db.commit()
        return existing

    done = completion(db, prd.id)
    prd.version = _promote(prd.version)
    row = PrdVersion(
        prd_id=prd.id,
        version=prd.version,
        date="just now",
        note=("Rebaseline — new intent, superseding the previous baseline."
              if existing is not None else "Intent baseline — the spec as approved."),
        body=prd.body,
        is_baseline=True,
        grill_outcomes={n: {"outcome": d["outcome"], "note": d["note"]}
                        for n, d in done["dimensions"].items()},
        # The chain. N+1 points BACK at N; N is never touched.
        supersedes_id=existing.id if existing is not None else None,
        rebaseline_reason_type=pending.get("reason_type", ""),
        rebaseline_reason=pending.get("reason", ""),
        requested_by=pending.get("requested_by", ""),
    )
    db.add(row)
    prd.pending_rebaseline = None
    prd.updated = "just now"
    db.commit()
    db.refresh(row)
    return row


def invalidate_approval(db: Session, prd: Prd, *, reason: str) -> Prd:
    """Un-approve a PRD whose approval rested on assumptions now known to be wrong.

    Normally approval is one-way: `sync_status` never demotes, because a spec that was
    genuinely agreed stays agreed. This is the exception, and it exists because the
    alternative is worse — if the STANDARD that granted an approval turns out to be
    broken, leaving the approval standing means the baseline everything is measured
    against was never really earned, and no later work can tell.

    So: an approval is only as good as the process that granted it. When the process is
    found wanting, the approval goes with it.

    Clears the dimension verdicts (they were reached under the old standard and would
    otherwise survive as unearned passes), drops the PRD back to `review`, and removes the
    baseline that approval froze. The grill TURNS are deliberately kept — the author
    really did answer those questions, and re-grilling should not make them retype it.

    Audited as a system event, because silently un-approving something is exactly the
    kind of act that has to leave a trace.
    """
    for row in db.scalars(select(GrillDimension).where(GrillDimension.prd_id == prd.id)).all():
        db.delete(row)
    for row in db.scalars(
        select(PrdVersion).where(PrdVersion.prd_id == prd.id, PrdVersion.is_baseline.is_(True))
    ).all():
        db.delete(row)
    prd.status = "review" if grill_state(db, prd.id)["answers"] else "draft"
    prd.version = "v0.1"
    prd.updated = "just now"
    db.commit()
    db.refresh(prd)
    events_svc.record(
        db, actor_type="system", actor_label="grill", surface="system",
        action="invalidate_prd_approval", target_type="prd", target_id=prd.id,
        project_id=prd.project_id, meta={"reason": reason},
    )
    return prd


REBASELINE_REASONS = ("learning", "scope-change", "correction")


def baseline_chain(db: Session, prd_id: str) -> list[PrdVersion]:
    """Every baseline this PRD has had, oldest first. Never one row — the chain IS the
    record, and reading it is how you tell a spec that was corrected from one that kept
    moving."""
    return list(db.scalars(
        select(PrdVersion)
        .where(PrdVersion.prd_id == prd_id, PrdVersion.is_baseline.is_(True))
        .order_by(PrdVersion.created_at, PrdVersion.id)
    ).all())


class RebaselineExpandsScope(ValueError):
    """A pending rebaseline would add sections. That is a new PRD, not a rebaseline."""


def rebaseline_added_sections(db: Session, prd: Prd, body: str | None = None) -> list[str]:
    """Sections in `body` that the governing baseline has no counterpart for.

    Empty unless a rebaseline is pending — an ordinary post-approval edit may add
    whatever it likes, because it is drift and drift is the thing being measured, not
    forbidden.

    Uses `diff_sections`, so a RENAME does not read as an addition (AL-240). Without that
    this rule would block the most ordinary correction there is: retitling a section
    while fixing it.
    """
    if not prd.pending_rebaseline:
        return []
    base = baseline_of(db, prd.id)
    if base is None:
        return []
    return diff_sections(base.body, body if body is not None else prd.body)["added"]


def request_rebaseline(
    db: Session, prd: Prd, *, reason_type: str, reason: str, requested_by: str,
) -> Prd:
    """Ask for new frozen intent. Does NOT create a baseline — it re-opens the grill.

    Approval is the grill, not an authority check (PRD-12 v1.0, answer 1): a rebaseline
    is a new statement of intent, so it earns approval the way the original did, by being
    interrogated until the completion standard is met. That is also the better answer to
    laundering than a click would be — "we edited the spec to match what we built" has to
    survive being questioned, and the questions and answers are recorded.

    So this clears the dimension verdicts and drops the PRD to `review`. The EXISTING
    baseline is left completely alone: it is still the governing intent until a new one
    is earned, and anything built in the meantime is still measured against it.

    The reason is stored on the PRD's pending state and carried onto the new baseline
    when the grill completes. It is the requester's own words on purpose — an agent
    mid-work is often where new intent surfaces, and that reasoning dies with the context
    window unless something writes it down.
    """
    if reason_type not in REBASELINE_REASONS:
        raise ValueError(
            f"reason_type must be one of {list(REBASELINE_REASONS)}, got {reason_type!r}"
        )
    if not (reason or "").strip():
        raise ValueError("a rebaseline needs a stated reason in the requester's own words")
    if prd.status == "closed":
        raise ValueError("a closed PRD can never be rebaselined; open a successor PRD instead")
    if baseline_of(db, prd.id) is None:
        raise ValueError("this PRD has no baseline to supersede; it has never been approved")

    prd.pending_rebaseline = {
        "reason_type": reason_type,
        "reason": reason.strip(),
        "requested_by": requested_by,
    }
    for row in db.scalars(select(GrillDimension).where(GrillDimension.prd_id == prd.id)).all():
        db.delete(row)
    prd.status = "review"
    prd.updated = "just now"
    db.commit()
    db.refresh(prd)
    events_svc.record(
        db, actor_type="agent" if requested_by.startswith("agent:") else "user",
        actor_label=requested_by, surface="mcp",
        action="request_rebaseline", target_type="prd", target_id=prd.id,
        project_id=prd.project_id, meta={"reason_type": reason_type, "reason": reason.strip()},
    )
    return prd


def sync_status(db: Session, prd: Prd) -> Prd:
    """Move the PRD's status to match its grill (AL-300 / PRD-15 D5).

        draft    — never grilled, or no answers recorded
        review   — grilled, answers recorded, dimensions still unanswered
        approved — the completion standard is met

    Called after every classification, so approval happens as a consequence of the work
    rather than as a separate act somebody has to remember.

    Two things it deliberately does NOT do:

    - **Never demote an `approved` PRD.** The ones approved under the old manual model
      (PRD-13 among them) were genuinely agreed, and recomputing history would silently
      retract that. Derivation governs transitions from here forward.
    - **Never move a PRD nobody has grilled.** A `draft` with no answers stays `draft`;
      there is nothing to derive from.
    """
    if prd.status == "approved":
        return prd
    done = completion(db, prd.id)
    target = "approved" if done["complete"] else ("review" if done["answers"] else "draft")
    # A rebaseline that expands scope cannot earn approval, however well it was grilled
    # (GRPH-318). Checked BEFORE the status moves, so the PRD is never left approved with
    # no baseline — `freeze_baseline` refusing after the fact would produce exactly that.
    if target == "approved":
        added = rebaseline_added_sections(db, prd)
        if added:
            logger.warning("rebaseline for %s adds sections %s; refusing approval", prd.id, added)
            target = "review"
    if target != prd.status:
        prd.status = target
        prd.updated = "just now"
        db.commit()
        db.refresh(prd)
        # Approval is the moment the spec was agreed, so the baseline freezes HERE
        # rather than waiting for anyone to remember (AL-239, and what AL-302 described).
        if target == "approved":
            freeze_baseline(db, prd)
    return prd


def grill_state(db: Session, prd_id: str) -> dict:
    """What the server knows about this PRD's grill, with no client involved. The shape
    AL-297 hangs per-dimension outcomes off, and what proves this item works: a fresh
    session can answer it."""
    turns = grill_turns(db, prd_id)
    done = completion(db, prd_id)
    return {
        "prd_id": prd_id,
        "turns": [{"seq": t.seq, "role": t.role, "text": t.text,
                   "via": t.via, "actor": t.actor} for t in turns],
        "questions": sum(1 for t in turns if t.role == "agent"),
        "answers": sum(1 for t in turns if t.role == "user"),
        "grilled": any(t.role == "user" for t in turns),
        # The completion standard, so one call answers both "what was said" and
        # "is it finished" — AL-300 derives status from exactly this.
        "dimensions": done["dimensions"],
        "outstanding": done["outstanding"],
        "deferred": done["deferred"],
        "complete": done["complete"],
    }


def capture_grill_decisions(db: Session, prd: Prd, history: list[dict]) -> list:
    """Preserve the author's decisions from a grill as candidate memory shards
    (AL-69). Every answer becomes a `candidate` shard (origin `agent:grill`) that
    flows through Memory Review (AL-49) and clustering (AL-50) — so a decision
    can't evaporate when context is cleared (the preservation principle). Deduped
    by (source, text) so re-applying doesn't pile up copies."""
    from app.services import memory as mem_svc

    source = f"grill: {prd.id}"
    existing = {
        s.text
        for s in mem_svc.list_shards(db, project_id=prd.project_id, status="candidate")
        if s.source == source
    }
    created = []
    for m in history or []:
        text = (m.get("text") or "").strip()
        if m.get("role") != "user" or len(text) < 8 or text in existing:
            continue
        shard = mem_svc.add_memory(
            db, text_body=text, scope="global", source=source,
            project_id=prd.project_id, status="candidate", origin="agent:grill",
        )
        existing.add(text)
        created.append(shard)
    return created


def grill_apply(db: Session, prd_id: str, history: list[dict]) -> str:
    """Synthesize an updated PRD body that folds in the decisions from a grill
    transcript (the handoff). Returns the proposed body; the caller saves it."""
    prd = get_prd(db, prd_id)
    if prd is None:
        raise ValueError(f"prd not found: {prd_id}")
    # Snapshot BEFORE proposing a wholesale rewrite (AL-239). `GRILL_APPLY_SYSTEM` asks
    # the model to return the FULL body, so whatever comes back replaces everything —
    # and until now nothing preserved what was there. An ordinary snapshot, not a
    # baseline: this records what the author had, not what anyone agreed to.
    if (prd.body or "").strip():
        db.add(PrdVersion(prd_id=prd.id, version=prd.version, date="just now",
                          note="Before folding in grill decisions.", body=prd.body))
        db.commit()
    provider, chat = platform_svc.resolve_chat(db, prd.project_id)
    if provider == "stub":
        answers = [m.get("text", "").strip() for m in history if m.get("role") == "user"]
        answers = [a for a in answers if a]
        if not answers:
            return prd.body
        block = "## Decisions from grilling\n" + "\n".join(f"- {a}" for a in answers) + "\n"
        return prd.body.rstrip() + "\n\n" + block
    return chat.chat(
        system=GRILL_APPLY_SYSTEM,
        context=grill_context(prd, history),
        question="Return the updated PRD markdown body incorporating the decisions above.",
    )


def _stub_command(command: str, prd: Prd) -> str:
    """Deterministic, offline output so the editor is useful without a provider."""
    if command == "grill":
        secs = parse_sections(prd.body)
        thin = [s for s in secs if len(section_bodies(prd.body).get(s, "").strip()) < 40]
        # One question per dimension, in DIMENSIONS order, so the offline grill asks
        # exactly what the completion standard grades (AL-298). Previously a fixed list
        # that overlapped the dimensions by coincidence.
        lines = [f"- {q}" for q in DIMENSIONS.values()]
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

# High-fidelity signal: work whose answer needs a prototype to see/feel, not words
# (AL-68). Heuristic over the section title + body; a human can always override.
_HIGH_FIDELITY_RE = re.compile(
    r"\b(ui|ux|visual|design|layout|interaction|animation|feel|look|screen|"
    r"mockup|wireframe|prototype|gesture|responsive|styling|aesthetic|onboarding flow)\b",
    re.IGNORECASE,
)


def classify_fidelity(text: str) -> str:
    """`high` when the text is about how something looks/feels/behaves (needs a
    prototype), else `low` (specifiable in words now)."""
    return "high" if _HIGH_FIDELITY_RE.search(text or "") else "low"


def parse_sections(body: str) -> list[str]:
    """Level-2 headings (`## …`) — the PRD's sections, in order."""
    return [m.group(1).strip() for m in _SECTION_RE.finditer(body or "")]


# Conventional PRD sections that FRAME the work rather than being work themselves.
# Treating every `## ` heading as implementable made decompose propose non-tasks
# ("Implement: Problem") and made coverage report false gaps, which trains you to
# ignore the metric (AL-96). Compared on an alphanumeric-only key so punctuation,
# casing, and a trailing "(v1)" don't matter.
_PROSE_SECTIONS = {
    "problem", "background", "context", "overview", "motivation", "summary",
    "goal", "goals", "nongoal", "nongoals", "outofscope",
    "successcriteria", "successmetrics", "openquestions",
    "appendix", "glossary", "references", "priorart",
    # planning / risk framing — describe the work or its rollout, not buildable work (AL-198)
    "risks", "risksandopenquestions", "risksopenquestions",
    "risksandmitigations", "risksmitigations",
    "phasing", "phases", "rollout", "rolloutplan", "milestones", "timeline", "faq", "faqs",
}


def _section_key(title: str) -> str:
    """Normalize a heading for classification: drop parentheticals, then keep only
    alphanumerics — so "Non-goals (v1)", "Non Goals", and "nongoals" all agree."""
    return re.sub(r"[^a-z0-9]+", "", re.sub(r"\(.*?\)", " ", title or "").lower())


def is_implementable_section(title: str) -> bool:
    """Whether a section describes work to build (vs. framing prose)."""
    return _section_key(title) not in _PROSE_SECTIONS


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
        # High-fidelity work still open in this section = prototype-first questions
        # a spec can't close in words yet (AL-68).
        open_high = sum(1 for it in its if it.fidelity == "high" and it.status != "done")
        implementable = is_implementable_section(s)
        per.append({
            "section": s,
            "implementable": implementable,
            "item_count": len(its),
            "done": counts.get("done", 0),
            "by_status": dict(counts),
            # Framing prose is never a gap — only buildable sections can lack work (AL-96).
            "gap": implementable and len(its) == 0,
            "high_fidelity": sum(1 for it in its if it.fidelity == "high"),
            "open_high_fidelity": open_high,
            "item_ids": [it.id for it in its],
        })
    total = len(items)
    done = sum(1 for it in items if it.status == "done")
    buildable = [p for p in per if p["implementable"]]
    return {
        "prd_id": prd.id, "title": prd.title, "status": prd.status,
        "sections": per,
        # `section_count` stays the total for continuity; coverage is measured against
        # the buildable subset so prose can't drag the ratio down.
        "section_count": len(sections),
        "implementable_sections": len(buildable),
        "sections_with_tasks": sum(1 for p in buildable if not p["gap"]),
        "gaps": [p["section"] for p in buildable if p["gap"]],
        "total_items": total, "done_items": done,
        "percent_done": round(100 * done / total) if total else 0,
        # Prototype-first work outstanding across the whole PRD.
        "open_high_fidelity": sum(1 for it in items if it.fidelity == "high" and it.status != "done"),
    }


def decompose(db: Session, prd: Prd, create: bool = False, include_prose: bool = False) -> dict:
    """Propose one tracked task per un-covered section (gap). With create=True, creates them
    as backlog items linked to the PRD + section, so the spec drives the tracker.

    Framing sections (Problem, Goals, Non-goals, Success criteria, …) are skipped — they
    describe the work, they aren't work (AL-96). Pass ``include_prose=True`` when a PRD
    genuinely uses one of those headings for buildable scope."""
    cov = coverage(db, prd)
    bodies = section_bodies(prd.body)
    proposals = []
    for p in cov["sections"]:
        if not include_prose and not p["implementable"]:
            continue
        if p["item_count"]:  # already covered by tracked work
            continue
        body = bodies.get(p["section"], "").strip()
        # A section about how something looks/feels needs a prototype first (AL-68).
        fidelity = classify_fidelity(f"{p['section']} {body}")
        proposals.append({
            "section": p["section"],
            "title": f"Implement: {p['section']}",
            "description": body,
            "fidelity": fidelity,
        })
    created = []
    if create:
        for pr in proposals:
            item = items_svc.create_item(
                db, title=pr["title"], description=pr["description"],
                project_id=prd.project_id, status="backlog",
                tags=["prd", "prototype"] if pr["fidelity"] == "high" else ["prd"],
                fidelity=pr["fidelity"],
                prd_id=prd.id, prd_section=pr["section"],
                reporter={"name": "Spec", "handle": "prd", "avatar": "#c9b8ff"},
            )
            created.append(item.id)
    return {"prd_id": prd.id, "proposals": proposals, "created": created}
