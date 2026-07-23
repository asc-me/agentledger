"""AL-46: code is the single owner of the tool catalog; docs must not silently
drift (review finding F5). These ratchets fail the moment docs/mcp.md and the
live TOOLS list disagree — the durable fix, not a one-time sweep.
"""
import re
from pathlib import Path

from app.mcp_server import LIVE_TOOL_COUNT, TOOLS

_DOCS = Path(__file__).resolve().parents[2] / "docs" / "mcp.md"


def _doc_tool_rows() -> list[str]:
    """Tool names from the `| `name` | ... |` table under the 'The N tools'
    heading (only that section — other backtick tables exist in the file)."""
    names, in_section = [], False
    for line in _DOCS.read_text().splitlines():
        if re.match(r"##\s+The \d+ tools", line):
            in_section = True
            continue
        if in_section:
            m = re.match(r"\|\s*`([a-z_]+)`\s*\|", line)
            if m:
                names.append(m.group(1))
            elif names and not line.startswith("|"):
                break  # the (contiguous) tool table has ended
    return names


def test_docs_table_covers_every_tool_exactly_once():
    doc_names = _doc_tool_rows()
    code_names = [t["name"] for t in TOOLS]
    assert set(doc_names) == set(code_names), (
        f"docs/mcp.md drift — only in code: {set(code_names) - set(doc_names)}; "
        f"only in docs: {set(doc_names) - set(code_names)}"
    )
    assert len(doc_names) == LIVE_TOOL_COUNT


def test_docs_heading_states_the_live_count():
    assert f"## The {LIVE_TOOL_COUNT} tools" in _DOCS.read_text(), (
        f"the 'The N tools' heading in docs/mcp.md must say {LIVE_TOOL_COUNT}"
    )


def test_mcp_enums_reference_service_constants():
    # The schema must reuse the service-owned enums, not inline copies.
    from app.services import links as links_svc
    from app.services import requests as req_svc

    by_name = {t["name"]: t for t in TOOLS}
    link_enum = by_name["link_items"]["inputSchema"]["properties"]["type"]["enum"]
    req_enum = by_name["report_agentledger_issue"]["inputSchema"]["properties"]["type"]["enum"]
    assert link_enum == links_svc.LINK_TYPES
    assert req_enum == req_svc.REQUEST_TYPES
