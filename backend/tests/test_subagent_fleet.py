"""AL-213: the generated sub-agent fleet stays consistent + AGENTS.md-sourced.

Guards `scripts/gen_subagents.py`:
  1. The committed files match the generator (nobody hand-edited the output).
  2. Each toolchain gets its **native** format — Cursor & Claude Code Markdown with
     their own frontmatter, Codex a valid TOML role file — while the prompt body is
     shared across all three (one source, native output per tool).
  3. Read-only intent maps to each tool's native control.
  4. The fleet README's invariants are the *verbatim* AGENTS.md invariants (anti-drift).
"""
import importlib.util
import tomllib
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


def test_each_toolchain_gets_its_native_format():
    gen = _load_generator()
    files = gen.render_files()

    # Cursor: Markdown + Cursor frontmatter (model/readonly/is_background).
    cur = files[".cursor/agents/al-implementer.md"]
    assert cur.startswith("---\n")
    assert "model: composer-2" in cur and "readonly: false" in cur and "is_background:" in cur

    # Claude Code: Markdown + Claude frontmatter — native model, and NONE of the
    # Cursor-only fields (which Claude Code would not understand).
    cl = files[".claude/agents/al-implementer.md"]
    assert cl.startswith("---\n")
    assert "model: haiku" in cl
    assert "readonly:" not in cl and "is_background:" not in cl and "composer-2" not in cl

    # Codex: a TOML role file, not Markdown — no stale .md emitted for Codex.
    assert ".codex/agents/al-implementer.md" not in files
    cx = files[".codex/agents/al-implementer.toml"]
    assert "developer_instructions = '''" in cx and 'model_reasoning_effort = "low"' in cx


def test_prompt_body_is_shared_across_toolchains():
    """Only the format/frontmatter differs — the instruction body is one source."""
    gen = _load_generator()
    for role in gen.ROSTER:
        body = role["body"]
        assert body in gen.render_cursor(role)
        assert body in gen.render_claude(role)
        assert body in gen.render_codex(role)


def test_readonly_maps_to_each_tools_native_control():
    gen = _load_generator()
    scout = next(r for r in gen.ROSTER if r["name"] == "al-scout")  # read-only
    impl = next(r for r in gen.ROSTER if r["name"] == "al-implementer")  # writer

    assert "readonly: true" in gen.render_cursor(scout)
    assert "readonly: false" in gen.render_cursor(impl)
    assert 'sandbox_mode = "read-only"' in gen.render_codex(scout)
    assert 'sandbox_mode = "workspace-write"' in gen.render_codex(impl)


def test_codex_toml_is_valid_and_round_trips_the_body():
    gen = _load_generator()
    for role in gen.ROSTER:
        data = tomllib.loads(gen.render_codex(role))
        assert data["name"] == role["name"]
        assert data["sandbox_mode"] in ("read-only", "workspace-write")
        assert data["model_reasoning_effort"] in ("high", "low")
        # The prompt body survives verbatim through TOML's literal string.
        assert data["developer_instructions"].strip() == role["body"].strip()


def test_readme_invariants_are_verbatim_from_agents_md():
    gen = _load_generator()
    invariants = gen.extract_section((REPO / "AGENTS.md").read_text(), "Invariants")
    assert invariants, "could not extract Invariants from AGENTS.md"
    readme = (REPO / ".cursor" / "agents" / "README.md").read_text()
    assert invariants in readme, "fleet README invariants drifted from AGENTS.md"
