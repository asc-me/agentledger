from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- Auth ----
class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RegisterIn(BaseModel):
    name: str
    email: EmailStr
    handle: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(ORMModel):
    id: str
    name: str
    handle: str
    email: EmailStr
    avatar: str
    initials: str


# ---- Projects ----
class ProjectOut(ORMModel):
    id: str
    name: str
    accent: str
    visibility: str
    description: str
    share_global_memory: bool
    auto_extract: bool
    mcp_enabled: bool
    embed_model: str


class ProjectCreate(BaseModel):
    name: str
    accent: str = "#c6f24e"
    description: str = ""


# ---- Items ----
class ItemCreate(BaseModel):
    title: str
    description: str = ""
    tags: list[str] = []
    effort: int = 0
    status: str = "backlog"
    project_id: str = "core"


class ItemUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    effort: int | None = None
    blocker: str | None = None
    github_url: str | None = None


class ReorderIn(BaseModel):
    ordered_ids: list[str]


class ItemOut(ORMModel):
    id: str
    project_id: str
    title: str
    description: str
    status: str
    tags: list[str]
    effort: int
    sort_order: int
    blocker: str
    date: str
    reporter: dict
    pr: dict | None
    github_url: str = ""
    created_at: datetime
    updated_at: datetime


# ---- Memory ----
class ShardCreate(BaseModel):
    text: str
    scope: str = "global"
    item_id: str | None = None
    project_id: str | None = "core"


class ShardOut(ORMModel):
    id: str
    text: str
    scope: str
    source: str
    item_id: str | None
    project_id: str | None
    fresh: bool
    created_at: datetime


class MemorySearchIn(BaseModel):
    query: str
    top_k: int = 5
    project_id: str | None = None


class ShardHit(BaseModel):
    shard: ShardOut
    score: float


# ---- Requests ----
class RequestCreate(BaseModel):
    type: str
    title: str
    by: str = ""
    project_id: str = "core"


class RequestLinkIn(BaseModel):
    item_id: str | None = None


class RequestVoteIn(BaseModel):
    delta: int = 1


class RequestOut(ORMModel):
    id: str
    project_id: str
    type: str
    title: str
    detail: str = ""
    by: str
    votes: int
    status: str
    linked_to: str | None
    ago: str
    source_url: str = ""
    meta: dict = {}
    attachment_ids: list[str] = []
    created_at: datetime

    # Rows created before these columns existed can hold NULL; coerce to the default.
    @field_validator("meta", mode="before")
    @classmethod
    def _meta_default(cls, v):
        return v or {}

    @field_validator("attachment_ids", mode="before")
    @classmethod
    def _atts_default(cls, v):
        return v or []


# ---- API keys ----
class ApiKeyCreate(BaseModel):
    name: str = "agent key"
    scopes: list[str] = ["read", "write"]
    # Project the key's agent writes to by default. None = global key.
    project_id: str | None = None


class ApiKeyOut(ORMModel):
    id: str
    name: str
    prefix: str
    scopes: list[str]
    project_id: str | None = None
    last_used: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    plaintext: str


# ---- Platform + integrations (Phase 5) ----
class PlatformConfigOut(ORMModel):
    project_id: str
    llm_mode: str
    local_base_url: str
    local_model: str
    cloud_provider: str
    cloud_model: str
    github_connected: bool
    github_account: str
    github_repo: str
    github_scope: str
    gdrive_connected: bool
    gdrive_account: str
    gdrive_folder: str
    rate_limit_per_min: int = 20
    turnstile_sitekey: str = ""
    turnstile_secret_set: bool = False  # never expose the secret itself


class PlatformUpdate(BaseModel):
    llm_mode: str | None = None
    local_base_url: str | None = None
    local_model: str | None = None
    cloud_provider: str | None = None
    cloud_model: str | None = None
    rate_limit_per_min: int | None = None
    turnstile_sitekey: str | None = None
    turnstile_secret: str | None = None


class GithubConnectIn(BaseModel):
    account: str
    repo: str


class GdriveConnectIn(BaseModel):
    account: str
    folder: str


class GithubIssueIn(BaseModel):
    title: str
    body: str = ""
    type: str = "feature"  # feature | bug | enhancement | feedback


class ProjectUpdate(BaseModel):
    name: str | None = None
    accent: str | None = None
    visibility: str | None = None
    description: str | None = None
    share_global_memory: bool | None = None
    auto_extract: bool | None = None
    mcp_enabled: bool | None = None
    embed_model: str | None = None


class MemberOut(BaseModel):
    user: UserOut
    role: str
    access: str


# ---- PRDs (Phase 3) ----
class PrdVersionOut(ORMModel):
    id: int
    version: str
    date: str
    note: str
    body: str
    created_at: datetime


class PrdOut(ORMModel):
    id: str
    project_id: str
    title: str
    status: str
    version: str
    body: str
    linked: list[str]
    updated: str
    created_at: datetime
    updated_at: datetime


class PrdSummary(ORMModel):
    id: str
    title: str
    status: str
    version: str
    linked: list[str]
    updated: str


class PrdCreate(BaseModel):
    title: str
    template: str = "standard"
    project_id: str = "core"
    body: str | None = None  # raw markdown when importing a .md file


class PrdUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    body: str | None = None


class PrdVersionIn(BaseModel):
    note: str = ""


class PrdLinkIn(BaseModel):
    item_id: str
    add: bool = True


class PrdAiIn(BaseModel):
    command: str  # expand | risks | summarize


class PrdAiOut(BaseModel):
    text: str


# ---- Public feedback (Phase 2) ----
class PublicRequestIn(BaseModel):
    type: str
    title: str
    detail: str = ""
    email: str = ""
    project_id: str = "core"
    source_url: str = ""
    meta: dict = {}
    attachment_ids: list[str] = []
    hp: str = ""  # honeypot — must stay empty
    turnstile_token: str = ""


class DuplicateHit(BaseModel):
    kind: str  # item | request
    id: str
    title: str
    score: float
    type: str | None = None
    status: str | None = None


class PublicRequestOut(BaseModel):
    request: RequestOut
    duplicates: list[DuplicateHit]


# ---- Agent chat ----
class ChatIn(BaseModel):
    message: str
    project_id: str | None = None


class ChatOut(BaseModel):
    reply: str
    shards: list[ShardHit]
