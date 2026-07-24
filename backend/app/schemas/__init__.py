from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


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
    password: str = Field(min_length=8, max_length=200)
    # Hosted onboarding (AL-74b): a valid org-invite token lets a user sign up even
    # when open self-serve registration is closed, and auto-joins them to the org.
    invite_token: str | None = None

    @field_validator("password")
    @classmethod
    def _password_not_trivial(cls, v: str) -> str:
        # Cheap floor against the worst passwords; length is the main lever (AL-72).
        if v.strip() != v or len(set(v)) < 4:
            raise ValueError("password is too weak")
        return v


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


# ---- Organizations (hosted-only, AL-74b) ----
class OrgCreate(BaseModel):
    name: str


class OrgOut(BaseModel):
    id: str
    name: str
    plan: str
    role: str  # the requesting user's role in this org


class OrgMemberOut(BaseModel):
    user: UserOut
    role: str


class InviteCreate(BaseModel):
    email: EmailStr
    role: str = "member"  # admin | member (owner is never invitable)


class InviteOut(ORMModel):
    id: str
    kind: str = "org"  # org | platform (AL-91)
    org_id: str | None = None  # NULL for a platform invite — the org doesn't exist yet
    email: EmailStr
    role: str
    plan: str | None = None  # platform invites only: plan preset for the org they found
    status: str
    created_at: datetime
    expires_at: datetime | None = None
    accept_url: str = ""  # convenience: the link emailed to the invitee (copy-able by admins)


class PlatformInviteCreate(BaseModel):
    email: EmailStr
    plan: str | None = None  # optional preset, e.g. seed a design partner onto `team`


class InvitePreviewOut(BaseModel):
    """Unauthenticated peek at an invite (by token) so the accept page can show who/
    what before the invitee logs in. Reveals only the org name + invited email/role.
    For a platform invite (AL-91) there is no org yet, so ``org_name`` is empty and
    ``kind`` tells the page to render the found-your-own-org flow instead."""
    kind: str = "org"  # org | platform
    org_name: str = ""
    email: EmailStr
    role: str
    invited_by: str


class InviteAcceptIn(BaseModel):
    token: str


# ---- Plans & quotas (hosted-only, AL-75) ----
class PlanLimitsOut(BaseModel):
    max_projects: int
    max_seats: int
    max_shards: int
    max_calls_per_month: int


class UsageOut(BaseModel):
    projects: int
    seats: int
    shards: int
    calls_this_month: int


class BillingOut(BaseModel):
    plan: str
    limits: PlanLimitsOut
    usage: UsageOut


class SetPlanIn(BaseModel):
    plan: str  # free | pro | team


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
    # Hosted-only (AL-74b): the org to create the project under. Optional when the
    # caller belongs to exactly one org (defaulted server-side); required otherwise.
    # Ignored on self-host, where projects have no org.
    org_id: str | None = None


# ---- Items ----
class ItemCreate(BaseModel):
    title: str
    description: str = ""
    tags: list[str] = []
    touchpoints: list[str] = []
    effort: int = 0
    status: str = "backlog"
    project_id: str = "core"
    prd_id: str | None = None
    prd_section: str = ""


class ItemUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    effort: int | None = None
    blocker: str | None = None
    github_url: str | None = None
    assignee: str | None = None
    touchpoints: list[str] | None = None
    prd_id: str | None = None
    prd_section: str | None = None


class ReorderIn(BaseModel):
    ordered_ids: list[str]


class ItemOut(ORMModel):
    id: str
    project_id: str
    title: str
    description: str
    status: str
    tags: list[str]
    touchpoints: list[str] = []
    effort: int
    sort_order: int
    blocker: str
    date: str
    reporter: dict
    pr: dict | None
    github_url: str = ""
    assignee: str = ""
    claimed_by: str | None = None
    prd_id: str | None = None
    prd_section: str = ""
    fidelity: str = "low"
    created_at: datetime
    updated_at: datetime

    @field_validator("touchpoints", mode="before")
    @classmethod
    def _tp_default(cls, v):
        return v or []


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
    status: str
    origin: str
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
    # Optional lifetime; None = non-expiring (AL-72).
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyOut(ORMModel):
    id: str
    name: str
    prefix: str
    scopes: list[str]
    project_id: str | None = None
    last_used: datetime | None
    created_at: datetime
    expires_at: datetime | None = None
    revoked: bool = False


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
    active_chat_provider: str = ""
    provider_config: dict = {}  # redacted per-provider config (api keys → key_set bool)
    public_share_enabled: bool = False
    share_token: str | None = None  # the share-link token (shown to authed members only)


class PlatformUpdate(BaseModel):
    llm_mode: str | None = None
    local_base_url: str | None = None
    local_model: str | None = None
    cloud_provider: str | None = None
    cloud_model: str | None = None
    rate_limit_per_min: int | None = None
    turnstile_sitekey: str | None = None
    turnstile_secret: str | None = None
    active_chat_provider: str | None = None
    providers: dict | None = None
    public_share_enabled: bool | None = None


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
    token: str | None = None  # public share token (preferred over raw project_id; AL-73)
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


# ---- Grill mode (AL-67): interactive PRD interrogation ----
class GrillMessage(BaseModel):
    role: str  # "user" | "agent"
    text: str


class GrillIn(BaseModel):
    message: str = ""  # empty on the opening turn
    history: list[GrillMessage] = []


class GrillApplyIn(BaseModel):
    history: list[GrillMessage] = []


class GrillApplyOut(BaseModel):
    body: str
    decisions_captured: int = 0  # candidate memory shards created from the transcript (AL-69)


class ChatOut(BaseModel):
    reply: str
    shards: list[ShardHit]


class CodeNodeOut(ORMModel):
    id: str
    path: str
    kind: str
    name: str
    lang: str
    summary: str
    fresh: bool


class CodeHit(BaseModel):
    node: CodeNodeOut
    score: float


class CodeAnswerOut(BaseModel):
    reply: str
    nodes: list[CodeHit]


class CodeEdgeOut(BaseModel):
    src: str
    dst: str
    type: str


class CodeMapOut(BaseModel):
    nodes: list[CodeNodeOut]
    edges: list[CodeEdgeOut]
    node_count: int
    edge_count: int


class CodeOutEdge(BaseModel):
    dst: str
    type: str


class CodeInEdge(BaseModel):
    src: str
    type: str


class CodeItemRef(BaseModel):
    id: str
    title: str
    status: str


class CodeLinkedItem(BaseModel):
    id: str
    title: str
    status: str
    relation: str


class CodeLinkedRequest(BaseModel):
    id: str
    title: str
    type: str
    status: str
    relation: str


class CodeNeighborsOut(BaseModel):
    path: str
    node: CodeNodeOut | None
    outgoing: list[CodeOutEdge]
    incoming: list[CodeInEdge]
    items_touching: list[CodeItemRef]
    linked_items: list[CodeLinkedItem]
    linked_requests: list[CodeLinkedRequest]


class CodeRefIn(BaseModel):
    ref_id: str
    path: str
    relation: str = "affects"
    ref_type: str | None = None


class CodeRefOut(BaseModel):
    id: int
    ref_type: str
    ref_id: str
    path: str
    relation: str


class CodeUnlinkIn(BaseModel):
    ref_id: str
    path: str
    relation: str | None = None


class CodeForRefRow(BaseModel):
    path: str
    relation: str
    node: CodeNodeOut | None


class UpstreamReportIn(BaseModel):
    type: str = "feedback"
    title: str
    detail: str = ""
