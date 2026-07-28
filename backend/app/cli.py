"""`agentledger` — a thin local CLI over the code-graph sync services (AL-218 / AL-134 D4).

Drives the AL-137/139/140 sync **directly against the local instance's database**, so a
self-host operator can link, push, purge, and move code-graph bundles with one command
instead of raw HTTP. (The HTTP sync endpoints don't accept the cloud credential in their
body — the `code_sync` service functions do — so the CLI calls the services, not the API.)

Run it where `DATABASE_URL` points at your instance — inside the backend container
(`docker compose exec backend agentledger sync`) or with the env exported. The cloud link
(URL + org-issued sync credential) is stored in `~/.agentledger/config.json`
(override with `AGENTLEDGER_CONFIG`), chmod 600.

    agentledger link --cloud-url https://cloud.example/ --api-key al_sk_… --project core
    agentledger status          # link + last-synced state
    agentledger sync            # incremental push of the linked project's code graph
    agentledger purge --yes     # delete this project's graph from the cloud
    agentledger export --out graph.json
    agentledger import --in graph.json --prune
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _config_path() -> Path:
    return Path(os.environ.get("AGENTLEDGER_CONFIG") or Path.home() / ".agentledger" / "config.json")


def load_config() -> dict:
    path = _config_path()
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        sys.exit(f"agentledger: config at {path} is not valid JSON ({e})")


def save_config(cfg: dict) -> Path:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n")
    path.chmod(0o600)  # holds the sync credential
    return path


def _project(args, cfg: dict) -> str:
    return getattr(args, "project", None) or cfg.get("project") or "core"


def _session():
    from app.db import SessionLocal
    return SessionLocal()


# ---- commands -----------------------------------------------------------------

def cmd_link(args) -> int:
    cfg = load_config()
    if args.cloud_url:
        cfg["cloud_url"] = args.cloud_url.rstrip("/")
    if args.api_key:
        cfg["api_key"] = args.api_key
    if args.project:
        cfg["project"] = args.project
    if not cfg.get("cloud_url") or not cfg.get("api_key"):
        sys.exit("agentledger link: need --cloud-url and --api-key (the org-issued sync credential)")
    path = save_config(cfg)
    print(f"Linked → {cfg['cloud_url']} (project {cfg.get('project', 'core')}). Saved to {path}.")
    return 0


def cmd_status(args) -> int:
    cfg = load_config()
    if not cfg.get("cloud_url"):
        print("Not linked. Run: agentledger link --cloud-url … --api-key …")
        return 0
    project = _project(args, cfg)
    key = cfg.get("api_key", "")
    print(f"Linked to : {cfg['cloud_url']}")
    print(f"Project   : {project}")
    print(f"Credential: {'set (' + key[:6] + '…)' if key else 'MISSING'}")
    from app.models import CodeSyncState
    db = _session()
    try:
        state = db.get(CodeSyncState, project)
    finally:
        db.close()
    if state is None:
        print("Last sync : never")
    else:
        print(f"Last sync : {state.last_synced_at} · {len(state.manifest or {})} paths in the pushed manifest")
    return 0


def cmd_sync(args) -> int:
    cfg = load_config()
    from app.services import code_sync
    db = _session()
    try:
        result = code_sync.push(
            db, project_id=_project(args, cfg),
            cloud_url=cfg.get("cloud_url", ""), api_key=cfg.get("api_key", ""),
        )
    except code_sync.NotLinked as e:
        sys.exit(f"agentledger sync: {e}  (run `agentledger link` first)")
    finally:
        db.close()
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_purge(args) -> int:
    if not args.yes:
        sys.exit("agentledger purge: this deletes the project's graph from the cloud. Re-run with --yes.")
    cfg = load_config()
    from app.services import code_sync
    db = _session()
    try:
        result = code_sync.purge(
            db, project_id=_project(args, cfg),
            cloud_url=cfg.get("cloud_url", ""), api_key=cfg.get("api_key", ""),
        )
    except code_sync.NotLinked as e:
        sys.exit(f"agentledger purge: {e}")
    finally:
        db.close()
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_export(args) -> int:
    cfg = load_config()
    project = _project(args, cfg)
    from app.services import code_graph
    db = _session()
    try:
        graph = code_graph.export_graph(db, project)
    finally:
        db.close()
    bundle = {"bundle_version": 1, "project_id": project,
              "nodes": graph.get("nodes", []), "edges": graph.get("edges", [])}
    text = json.dumps(bundle, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text + "\n")
        print(f"Exported {len(bundle['nodes'])} nodes / {len(bundle['edges'])} edges → {args.out}")
    else:
        print(text)
    return 0


def cmd_import(args) -> int:
    cfg = load_config()
    try:
        bundle = json.loads(Path(args.infile).read_text())
    except FileNotFoundError:
        sys.exit(f"agentledger import: no such bundle: {args.infile}")
    except json.JSONDecodeError as e:
        sys.exit(f"agentledger import: {args.infile} is not valid JSON ({e})")
    project = args.project or bundle.get("project_id") or cfg.get("project") or "core"
    from app.services import code_graph
    db = _session()
    try:
        result = code_graph.describe_code(
            db, project_id=project,
            nodes=bundle.get("nodes", []), edges=bundle.get("edges", []), prune=args.prune,
        )
    finally:
        db.close()
    print(json.dumps({"project_id": project, **result}, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentledger", description="Local code-graph sync for AgentLedger self-host (AL-134).")
    sub = p.add_subparsers(dest="command", required=True)

    lk = sub.add_parser("link", help="store the cloud sync target (URL + org-issued credential)")
    lk.add_argument("--cloud-url")
    lk.add_argument("--api-key")
    lk.add_argument("--project")
    lk.set_defaults(func=cmd_link)

    st = sub.add_parser("status", help="show the link + last-synced state")
    st.add_argument("--project")
    st.set_defaults(func=cmd_status)

    sy = sub.add_parser("sync", help="incremental push of the project's code graph to the cloud")
    sy.add_argument("--project")
    sy.set_defaults(func=cmd_sync)

    pu = sub.add_parser("purge", help="delete the project's code graph from the cloud")
    pu.add_argument("--project")
    pu.add_argument("--yes", action="store_true", help="confirm the destructive purge")
    pu.set_defaults(func=cmd_purge)

    ex = sub.add_parser("export", help="write the project's code graph as a portable bundle")
    ex.add_argument("--project")
    ex.add_argument("--out", help="output file (default: stdout)")
    ex.set_defaults(func=cmd_export)

    im = sub.add_parser("import", help="import a code-graph bundle into the project (re-embeds locally)")
    im.add_argument("--in", dest="infile", required=True, metavar="FILE")
    im.add_argument("--project")
    im.add_argument("--prune", action="store_true", help="mark paths absent from the bundle stale")
    im.set_defaults(func=cmd_import)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
