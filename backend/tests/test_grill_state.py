"""The grill is server state, not a client transcript (AL-296 / PRD-15 D4).

The grill used to live entirely in the caller: it posted the whole conversation to
`/grill/stream` and `/grill/apply`, and nothing was retained. Fine while the grill was
advisory — not fine now that PRD-15 derives approval from whether it is finished, because
"has this PRD been grilled?" would be answerable only by whoever held the transcript.

The tests worth having here are about what the SERVER can answer on its own, and about
the append rule, which is the one place this can silently lose an answer.
"""
import json

import pytest


@pytest.fixture()
def prd(client, auth):
    r = client.post("/api/prds", json={"title": "Grill State", "project_id": "core"},
                    headers=auth)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _stream(client, auth, prd_id, message="", history=None):
    """Drive one grill round. The SSE body must be consumed for the generator to finish
    — the reply is only recorded after the last chunk."""
    with client.stream("POST", f"/api/prds/{prd_id}/grill/stream",
                       json={"message": message, "history": history or []},
                       headers=auth) as r:
        assert r.status_code == 200, r.text
        for _ in r.iter_lines():
            pass


def _state(client, auth, prd_id) -> dict:
    r = client.get(f"/api/prds/{prd_id}/grill", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


# ---- the point of the item ----------------------------------------------------------
def test_the_server_knows_the_grill_without_a_client_transcript(client, auth, prd):
    """Impossible before this item: nothing was stored, so this endpoint could only ever
    have reported an empty conversation."""
    assert _state(client, auth, prd)["grilled"] is False

    _stream(client, auth, prd)  # opening round: the grill asks
    _stream(client, auth, prd, message="Scope stops at the local instance.",
            history=[{"role": "agent", "text": "opening questions"}])

    state = _state(client, auth, prd)
    assert state["grilled"] is True
    assert state["answers"] == 1
    assert state["questions"] >= 1
    assert any("local instance" in t["text"] for t in state["turns"])


def test_the_questions_the_grill_asked_are_recorded_too(client, auth, prd):
    """AL-297 classifies what was PUT TO the author, which the answers alone can't show.
    So the streamed reply is accumulated and stored, not just the caller's side."""
    _stream(client, auth, prd)
    turns = _state(client, auth, prd)["turns"]
    assert [t["role"] for t in turns] == ["agent"]
    assert turns[0]["text"].strip() != ""


# ---- the append rule ----------------------------------------------------------------
def test_resending_the_whole_history_does_not_duplicate_it(client, auth, prd):
    """Clients post the FULL transcript every round. Appending it wholesale would
    duplicate every earlier turn and inflate the answer count approval depends on."""
    _stream(client, auth, prd, message="First answer.")
    after_first = _state(client, auth, prd)

    # Same history again, plus one new answer — the normal client behaviour.
    _stream(client, auth, prd, message="Second answer.",
            history=[{"role": t["role"], "text": t["text"]} for t in after_first["turns"]])

    texts = [t["text"] for t in _state(client, auth, prd)["turns"]]
    assert texts.count("First answer.") == 1, texts
    assert texts.count("Second answer.") == 1, texts


def test_a_short_or_edited_history_never_erases_stored_turns(client, auth, prd):
    """A second tab, or a session that lost state, sends a stale history. Rewriting the
    store to match the latest caller would let a client silently delete answers that
    approval is derived from — a worse failure than a transcript that lags."""
    _stream(client, auth, prd, message="An answer that must survive.")
    before = _state(client, auth, prd)

    _stream(client, auth, prd, message="", history=[])  # a caller with no state

    after = _state(client, auth, prd)
    assert any("must survive" in t["text"] for t in after["turns"])
    assert after["answers"] == before["answers"]


def test_empty_turns_are_not_recorded(client, auth, prd):
    """An empty turn is neither a question nor an answer, and counting it would let a
    stream of blanks look like engagement."""
    _stream(client, auth, prd, message="   ",
            history=[{"role": "user", "text": ""}, {"role": "agent", "text": "  "}])
    assert _state(client, auth, prd)["answers"] == 0


def test_seq_is_contiguous_and_ordered(client, auth, prd):
    _stream(client, auth, prd, message="One.")
    _stream(client, auth, prd, message="Two.",
            history=[{"role": t["role"], "text": t["text"]}
                     for t in _state(client, auth, prd)["turns"]])
    seqs = [t["seq"] for t in _state(client, auth, prd)["turns"]]
    assert seqs == sorted(seqs) == list(range(len(seqs)))


# ---- interaction with what already existed ------------------------------------------
def test_grill_apply_records_turns_it_was_handed(client, auth, prd):
    """The apply route is the backstop for a stream that died before writing its reply."""
    r = client.post(f"/api/prds/{prd}/grill/apply",
                    json={"history": [{"role": "agent", "text": "What is out of scope?"},
                                      {"role": "user", "text": "Anything hosted."}]},
                    headers=auth)
    assert r.status_code == 200, r.text
    state = _state(client, auth, prd)
    assert state["answers"] == 1 and state["questions"] == 1


def test_capture_grill_decisions_still_writes_memory_shards(client, auth, prd):
    """The two records do different jobs and both must survive: shards hold the durable
    CONTENT of a decision and flow through Memory review; turns hold the STRUCTURE that
    says whether the conversation is finished."""
    r = client.post(f"/api/prds/{prd}/grill/apply",
                    json={"history": [{"role": "user", "text": "We only support Postgres."}]},
                    headers=auth)
    assert r.json()["decisions_captured"] == 1, r.text

    shards = client.get("/api/memory/candidates?project_id=core", headers=auth).json()
    assert any("only support Postgres" in s["text"] for s in shards), shards
