"""AL-213: the generated sub-agent fleet stays consistent + AGENTS.md-sourced.

Guards three properties of `scripts/gen_subagents.py`:
  1. The committed files match the generator (nobody hand-edited the output).
  2. The three toolchains (.cursor/.claude/.codex) are byte-identical (portability).
  3. The fleet README's invariants are the *verbatim* AGENTS.md invariants (anti-drift).
"""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GEN = REPO / "scripts" / "gen_subagents.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_subagents", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_fleet_matches_generator():
    gen = _load_generator()
    for rel, expected in gen.render_files().items():
        path = REPO / rel
        assert path.exists(), f"{rel} missing — run scripts/gen_subagents.py"
        assert path.read_text() == expected, f"{rel} stale — run scripts/gen_subagents.py"


def test_three_toolchains_are_identical():
    base_dir = REPO / ".cursor" / "agents"
    base = {p.name: p.read_text() for p in base_dir.glob("*.md")}
    assert base, "no .cursor/agents files generated"
    for tool in ("claude", "codex"):
        other = {p.name: p.read_text() for p in (REPO / f".{tool}" / "agents").glob("*.md")}
        assert other == base, f".{tool}/agents differs from .cursor/agents"


def test_readme_invariants_are_verbatim_from_agents_md():
    gen = _load_generator()
    invariants = gen.extract_section((REPO / "AGENTS.md").read_text(), "Invariants")
    assert invariants, "could not extract Invariants from AGENTS.md"
    readme = (REPO / ".cursor" / "agents" / "README.md").read_text()
    assert invariants in readme, "fleet README invariants drifted from AGENTS.md"
