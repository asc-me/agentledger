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


def get_config(db: Session, project_id: str = "core") -> PlatformConfig:
    cfg = db.get(PlatformConfig, project_id)
    if cfg is None:
        cfg = PlatformConfig(project_id=project_id)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def apply_llm(cfg: PlatformConfig) -> None:
    """Point the in-memory settings + provider cache at the configured chat provider."""
    if cfg.llm_mode == "local":
        app_settings.chat_provider = "ollama"
        app_settings.ollama_base_url = cfg.local_base_url
        app_settings.ollama_chat_model = cfg.local_model
    elif cfg.llm_mode == "cloud":
        app_settings.chat_provider = "anthropic"
        app_settings.anthropic_model = cfg.cloud_model
    else:
        app_settings.chat_provider = "stub"
    providers.reset()


_LLM_FIELDS = {"llm_mode", "local_base_url", "local_model", "cloud_provider", "cloud_model"}


def update_config(db: Session, project_id: str, fields: dict) -> PlatformConfig:
    cfg = get_config(db, project_id)
    for k, v in fields.items():
        if hasattr(cfg, k) and v is not None:
            setattr(cfg, k, v)
    db.commit()
    db.refresh(cfg)
    if _LLM_FIELDS & fields.keys():
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
