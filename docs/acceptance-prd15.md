# PRD-15 acceptance walk

A PRD approving itself by being grilled — run against a real stack, not asserted in unit
tests (AL-303). Re-run after changing `services/prds.py`, the grill routes, or either
grill table.

Run in an **isolated compose project**, same reason as PRD-14's walk: the compose project
name is pinned to `agentledger`, so on a machine with local development history
`start.sh` would attach to the real `agentledger_agentledger_pgdata` volume.

```bash
COMPOSE="docker compose -p gb-acceptance" \
  DB_PORT=5455 API_PORT=8011 WEB_PORT=8091 \
  PROJECT_NAME="Grill Acceptance" ./start.sh
```

Everything below ran over MCP with the printed key, on the **shipped stub provider** —
no chat model configured, nobody opening the UI except to defer.

## What must happen

| # | Step | Expected | Result |
| --- | --- | --- | --- |
| 1 | `create_prd` | `draft` | PASS (`GA-P1`) |
| 2 | `grill_prd` | returns questions | PASS |
| 3 | first `answer_grill` | `review`, 3 dimensions outstanding | PASS |
| 4 | three answers | still `review`, `open_decisions` outstanding | PASS |
| 5 | `update_prd(status="approved")` | **refused**, `conflict`, names what's outstanding | PASS |
| 6 | defer `open_decisions` | grill complete | PASS |
| 7 | status | **`approved`, set by nobody** | PASS |
| 8 | ungrilled PRD → approve | refused, stays `draft` | PASS |
| 9 | blank relayed answer | refused (`validation`) | PASS |
| 10 | edit an approved PRD | still `approved`, title changed | PASS |
| 11 | answer provenance | all three marked `agent`-relayed | PASS |
| 12 | stub disclosure | every stub-graded dimension says "substance not assessed" | PASS |

Tear down:

```bash
docker compose -p gb-acceptance down -v
```

## What this walk does NOT cover

**The AL-239 intent baseline.** PRD-15's acceptance says completion should snapshot an
immutable baseline carrying the per-dimension outcomes. AL-239 builds that mechanism and
is parked, so AL-302 — the item wiring completion to it — is still blocked. Nothing here
verifies a baseline exists, because nothing creates one yet.

Everything else in the acceptance criteria is covered above. When AL-239 and AL-302 land,
add a step asserting the snapshot fires at step 7 and carries `open_decisions: deferred`.

## Notes from the run

`graded_by` came back as `{"author", "stub"}` — the deferred dimension is attributed to
the author who deferred it, the other three to the offline stub. That split is the point
of AL-299: on this configuration `approved` means *four answers were recorded and one was
consciously deferred*, not *four answers were judged sound*. The UI badges it and the
notes say so.
