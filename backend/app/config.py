from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# The insecure fallback secret. Anyone knowing it can mint tokens for any user, so
# an internet-exposed deploy MUST override JWT_SECRET (see startup security check).
DEFAULT_JWT_SECRET = "dev-secret-change-me-in-production-0123456789abcdef"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Postgres by default; falls back to SQLite for zero-infra local runs / tests.
    database_url: str = "postgresql+psycopg://agentledger:agentledger@localhost:5432/agentledger"

    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 14

    # Security hardening for internet-exposed deploys (all safe-by-default for local):
    # verify inbound GitHub webhook HMAC when set; trust X-Forwarded-For only behind a
    # known proxy; refuse to start on a weak/default JWT secret when required.
    github_webhook_secret: str = ""
    trusted_proxy: bool = False
    require_strong_secret: bool = False

    # Release identity: the git revision this image was built from, baked in at
    # `docker compose build` time (see docs/deploy.md) and reported by /health.
    git_sha: str = "unknown"

    # Secret encryption at rest (AL-73). When set, BYOK provider API keys (and other
    # stored secrets) are Fernet-encrypted in the DB; unset means store as-is (fine for
    # a trusted single-tenant self-host). Any string works — it's stretched to a key.
    # Hosted mode requires it (check_security refuses to boot otherwise).
    secret_encryption_key: str = ""

    # Multi-tenant SaaS switch. OFF for self-hosted/OSS builds (flat User→Project,
    # cross-project "global" memory allowed). ON only for the hosted offering, where
    # Organizations + billing + quotas mount and tenant boundaries tighten (e.g. no
    # project-less global shards, so one tenant's memory can never reach another).
    hosted_mode: bool = False

    embed_dim: int = 384

    # ---- AI providers (F1). Defaults are all-stub → fully offline. ----
    # embed_provider: stub | ollama | openai   (must match embed_dim: nomic-embed-text=768, openai text-embedding-3-small=1536)
    embed_provider: str = "stub"
    # chat_provider: stub | ollama | anthropic  (drives agent chat + auto-extraction)
    chat_provider: str = "stub"

    ollama_base_url: str = "http://localhost:11434"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_chat_model: str = "llama3.1:8b"
    ollama_auth_key: str = ""  # optional bearer for a Caddy-guarded public Ollama endpoint

    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_embed_model: str = "text-embedding-3-small"

    # Anthropic auth is read from ANTHROPIC_API_KEY by the SDK.
    anthropic_model: str = "claude-opus-4-8"

    # Public embeddable feedback form (Phase 2).
    public_submit_enabled: bool = True

    # Upstream feedback: where a "Report an issue with AgentLedger" report is forwarded
    # (always user/agent-initiated — never silent telemetry). Defaults to ASCME's hosted
    # intake; a deployer can repoint it, or set the URL blank to disable the feature.
    upstream_feedback_url: str = "https://feedback.asc-me.dev/api/public/requests"
    upstream_feedback_project: str = "agentledger"  # project_id on the upstream instance

    # Drive sync: base directory the filesystem backend syncs into. Mount this at a
    # Google Drive Desktop folder to reach Drive with no OAuth.
    sync_dir: str = "/data/sync"

    # Seed the design's dataset on startup when the DB is empty.
    seed_on_start: bool = True

    # Comma-separated list of allowed CORS origins for the SPA.
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def jwt_secret_is_weak(self) -> bool:
        """The default secret, or anything too short to resist offline guessing."""
        return self.jwt_secret == DEFAULT_JWT_SECRET or len(self.jwt_secret) < 32


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
