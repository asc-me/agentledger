"""Platform + integration config (Phase 5).

The AI-provider settings genuinely drive F1: updating llm_mode switches the live
chat/extraction provider (Ollama/Anthropic/stub). The embed provider stays a
deploy-time setting because changing it changes the pgvector column dimension.

GitHub/Drive here manage connection *state and config* — live OAuth/token exchange
and API sync are intentionally out of scope for the local slice (no third-party
credentials); the inbound GitHub webhook (routers/public.py) is fully implemented.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app import providers
from app.models import PlatformConfig
from app.security import secrets


def get_config(db: Session, project_id: str = "core") -> PlatformConfig:
    cfg = db.get(PlatformConfig, project_id)
    if cfg is None:
        cfg = PlatformConfig(project_id=project_id)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def apply_llm(cfg: PlatformConfig) -> None:
    """Point the live provider layer at the configured chat provider, and bridge Ollama's
    endpoint/model into the (deploy-time) embedder."""
    if cfg.active_chat_provider:
        # New provider-registry path.
        pconf = (cfg.providers or {}).get(cfg.active_chat_provider, {})
        providers.set_active_chat(
            provider=cfg.active_chat_provider,
            base_url=pconf.get("base_url", ""),
            api_key=secrets.decrypt(pconf.get("api_key", "")),
            model=pconf.get("chat_model", ""),
        )
    elif cfg.llm_mode == "local":
        # Legacy llm_mode path (kept for back-compat; sets app_settings.chat_provider too).
        app_settings.chat_provider = "ollama"
        app_settings.ollama_base_url = cfg.local_base_url
        app_settings.ollama_chat_model = cfg.local_model
        providers.set_active_chat("ollama", base_url=cfg.local_base_url, model=cfg.local_model)
    elif cfg.llm_mode == "cloud":
        app_settings.chat_provider = "anthropic"
        app_settings.anthropic_model = cfg.cloud_model
        providers.set_active_chat("anthropic", model=cfg.cloud_model)
    else:
        app_settings.chat_provider = "stub"
        providers.set_active_chat("stub")

    # A UI-configured Ollama serves embeddings too when EMBED_PROVIDER=ollama (deploy-time):
    # push its endpoint/model/auth into the env-selected embedder.
    ollama_conf = (cfg.providers or {}).get("ollama", {})
    if ollama_conf.get("base_url"):
        app_settings.ollama_base_url = ollama_conf["base_url"]
    if ollama_conf.get("embed_model"):
        app_settings.ollama_embed_model = ollama_conf["embed_model"]
    if ollama_conf.get("api_key"):
        app_settings.ollama_auth_key = secrets.decrypt(ollama_conf["api_key"])
    providers.reset()


_LLM_FIELDS = {
    "llm_mode", "local_base_url", "local_model", "cloud_provider", "cloud_model",
    "active_chat_provider", "providers",
}


def update_config(db: Session, project_id: str, fields: dict) -> PlatformConfig:
    cfg = get_config(db, project_id)
    touched = set(fields.keys())

    # Providers dict: merge (don't clobber), with write-only key semantics — a blank api_key
    # keeps the stored one, so the redacted round-trip from the UI never wipes a key.
    if fields.get("providers") is not None:
        merged = dict(cfg.providers or {})
        for pid, incoming in (fields["providers"] or {}).items():
            cur = dict(merged.get(pid, {}))
            for k, v in (incoming or {}).items():
                if k == "api_key":
                    # Write-only + encrypted at rest: a blank value keeps the stored
                    # (encrypted) key; a new value is Fernet-encrypted before storage (AL-73).
                    if v:
                        cur["api_key"] = secrets.encrypt(v)
                elif v is not None:
                    cur[k] = v
            merged[pid] = cur
        cfg.providers = merged  # reassign so SQLAlchemy tracks the JSON change

    for k, v in fields.items():
        if k == "providers":
            continue
        if hasattr(cfg, k) and v is not None:
            setattr(cfg, k, v)

    db.commit()
    db.refresh(cfg)
    if _LLM_FIELDS & touched:
        apply_llm(cfg)
    return cfg


def connect_github(db: Session, project_id: str, *, account: str, repo: str) -> PlatformConfig:
    cfg = get_config(db, project_id)
    cfg.github_connected = True
    cfg.github_account = account
    cfg.github_repo = repo
    cfg.github_scope = "repo · read/write"
    db.commit()
    db.refresh(cfg)
    return cfg


def disconnect_github(db: Session, project_id: str) -> PlatformConfig:
    cfg = get_config(db, project_id)
    cfg.github_connected = False
    cfg.github_account = ""
    cfg.github_repo = ""
    cfg.github_scope = ""
    db.commit()
    db.refresh(cfg)
    return cfg


def connect_gdrive(db: Session, project_id: str, *, account: str, folder: str) -> PlatformConfig:
    cfg = get_config(db, project_id)
    cfg.gdrive_connected = True
    cfg.gdrive_account = account
    cfg.gdrive_folder = folder
    db.commit()
    db.refresh(cfg)
    return cfg


def disconnect_gdrive(db: Session, project_id: str) -> PlatformConfig:
    cfg = get_config(db, project_id)
    cfg.gdrive_connected = False
    cfg.gdrive_account = ""
    cfg.gdrive_folder = ""
    db.commit()
    db.refresh(cfg)
    return cfg
