"""SQLAlchemy models for AgentLedger.

Kept in one module for the core slice; split out later if it grows.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.config import settings
from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EmbeddingType(TypeDecorator):
    """Vector on Postgres, JSON-encoded text on SQLite (test fallback)."""

    impl = Text
    cache_ok = True

    def __init__(self, dim: int):
        self.dim = dim
        super().__init__()

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        return json.dumps(list(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        return json.loads(value)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    handle: Mapped[str] = mapped_column(String, unique=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    avatar: Mapped[str] = mapped_column(String, default="#a78bfa")
    initials: Mapped[str] = mapped_column(String, default="")
    password_hash: Mapped[str] = mapped_column(String)
    # Bumped on logout / password change to revoke every outstanding token: it's
    # embedded in each JWT as `tv` and checked on decode, so a leaked or logged-out
    # refresh token stops working immediately instead of living to its 14d expiry (AL-59).
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[list[Membership]] = relationship(back_populates="user")
    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="user")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    # Short prefix its item/request/PRD keys render with, e.g. AL -> AL-12 (PRD-13).
    # Stored uppercase, which is what makes this plain UNIQUE express case-insensitive
    # uniqueness on both engines. Changing it is one UPDATE: keys are rendered, never
    # stored, so no other row in the database moves. See app/tagging.py.
    tag: Mapped[str] = mapped_column(String, unique=True)
    accent: Mapped[str] = mapped_column(String, default="#c6f24e")
    visibility: Mapped[str] = mapped_column(String, default="private")
    description: Mapped[str] = mapped_column(Text, default="")
    share_global_memory: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_extract: Mapped[bool] = mapped_column(Boolean, default=True)
    mcp_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Memory auto-triage (AL-227): let the AL-151 scorer ACT on agent candidates
    # instead of only advising, so the review queue stays small. `auto_reject`
    # (on) drops near-dups / resembles-rejected on write; `auto_accept` (off)
    # publishes high-confidence corroborated lessons; `llm_judge` (off) swaps the
    # offline similarity scorer for an LLM assessment. Every auto-action is audited
    # and undoable — the AL-49 human boundary holds for anything left as candidate.
    memory_auto_reject: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    memory_auto_accept: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    memory_llm_judge: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    embed_model: Mapped[str] = mapped_column(String, default="stub-384")
    # Hosted SaaS only (AL-74): the owning organization. NULL on self-host, where
    # the org layer is inert. In hosted mode authz additionally requires the caller
    # to belong to this org, so a project never leaks outside its tenant.
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)

    memberships: Mapped[list[Membership]] = relationship(back_populates="project")


class Organization(Base):
    """A hosted-SaaS tenant (AL-74). Self-host never creates these; the org layer
    is gated by HOSTED_MODE and invisible to self-hosted deployments."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    plan: Mapped[str] = mapped_column(String, default="free")  # free | pro | team (AL-75)
    stripe_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrgMembership(Base):
    """A user's seat in an organization (hosted-only, AL-74)."""

    __tablename__ = "org_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String, default="member")  # owner | admin | member
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_org_membership"),)


class OrgRequest(Base):
    """A user's request to found an ADDITIONAL organization (hosted-only, AL-92).

    Every account gets one org for free; founding another is privileged. A user asks
    here, an operator approves or denies, and an approved request grants exactly ONE
    additional org — ``consumed`` flips when it's spent, so approval can't be reused.
    A standing (unlimited) entitlement comes from the plan instead
    (``Plan.may_found_additional_orgs``, carried by the enterprise tier)."""

    __tablename__ = "org_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # oreq_...
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    company: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="pending", index=True)  # pending|approved|denied
    consumed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_note: Mapped[str] = mapped_column(String, default="")


class OrgUsage(Base):
    """Per-org, per-month usage counter for plan enforcement (hosted-only, AL-75).

    Only the metered MCP-call count lives here; project/seat/shard usage is derived
    by counting rows on demand. Keyed by (org_id, period) where period is 'YYYY-MM'
    (UTC), so each month starts fresh — no reset job needed."""

    __tablename__ = "org_usage"

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    period: Mapped[str] = mapped_column(String, primary_key=True)  # 'YYYY-MM' (UTC)
    mcp_calls: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class OrgInvite(Base):
    """A pending invitation, of one of two kinds (hosted-only, AL-74b / AL-91).

    - ``kind="org"`` — seats the invitee in an EXISTING org (``org_id`` set). Created
      by an org owner/admin.
    - ``kind="platform"`` — authorizes a brand-new account to sign up and found its
      OWN org (``org_id`` NULL, since that org doesn't exist yet). Created by a
      platform operator; may carry a ``plan`` to pre-assign to the org they found.

    Both share one pipeline: the unguessable ``token`` addresses the accept link,
    ``status`` moves pending → accepted or revoked, and an invite past ``expires_at``
    is refused even while still ``pending``. Rows are kept after acceptance for
    provenance."""

    __tablename__ = "org_invites"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # inv_...
    kind: Mapped[str] = mapped_column(String, default="org", index=True)  # org | platform
    # NULL for a platform invite — the org is founded on accept.
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String, index=True)  # invitee (may not have an account yet)
    role: Mapped[str] = mapped_column(String, default="member")  # admin | member (never owner)
    # Platform invites only: plan to stamp on the org the invitee founds (e.g. seed a
    # design partner straight onto `team`). NULL = the default free plan.
    plan: Mapped[str | None] = mapped_column(String, nullable=True)
    token: Mapped[str] = mapped_column(String, unique=True, index=True)
    invited_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String, default="pending", index=True)  # pending|accepted|revoked
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    role: Mapped[str] = mapped_column(String, default="member")  # owner/admin/member
    access: Mapped[str] = mapped_column(String, default="read")  # write/read/none

    user: Mapped[User] = relationship(back_populates="memberships")
    project: Mapped[Project] = relationship(back_populates="memberships")


class Item(Base):
    __tablename__ = "items"

    # FROZEN at issue time and never rewritten — identity, not display (PRD-13). The key
    # a human sees is rendered from the project's current tag + `number`; retagging a
    # project must not move this or any of the eleven other columns that reference it.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    # Per-project, per-kind sequence. Unique within the project, so two projects can both
    # have a number 235 — which is exactly what the old global counter prevented.
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="backlog")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    touchpoints: Mapped[list] = mapped_column(JSON, default=list)  # files/globs/modules the item affects
    effort: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    blocker: Mapped[str] = mapped_column(String, default="")
    date: Mapped[str] = mapped_column(String, default="")  # display date from design
    reporter: Mapped[dict] = mapped_column(JSON, default=dict)
    pr: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    github_url: Mapped[str] = mapped_column(String, default="")  # linked issue/PR
    # Proof-on-done (AL-53): receipts that match evidence to the completion claim —
    # a list of {kind: test|url|screenshot|health|note, detail, url}.
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    # Assignment / agent claiming (feature A).
    assignee: Mapped[str] = mapped_column(String, default="")  # durable owner (human or agent)
    claimed_by: Mapped[str | None] = mapped_column(String, nullable=True)  # agent holding the lease
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Spec traceability (feature D): the PRD + section this item implements.
    prd_id: Mapped[str | None] = mapped_column(String, nullable=True)
    prd_section: Mapped[str] = mapped_column(String, default="")
    # Fidelity (AL-68): `low` = specifiable in words now; `high` = needs a prototype
    # to answer (the grill → prototype → grill handoff). Routes prototype-first work.
    fidelity: Mapped[str] = mapped_column(String, default="low")  # low | high
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    # The backstop for the mint path (services/items.py): even if minting is bypassed
    # or two agents race, the database refuses a duplicate number within a project.
    __table_args__ = (UniqueConstraint("project_id", "number", name="uq_item_number"),)


class MemoryShard(Base):
    __tablename__ = "memory_shards"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    item_id: Mapped[str | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String, default="global")  # global/item
    source: Mapped[str] = mapped_column(String, default="")
    # Lifecycle (AL-49): agent self-reports enter as `candidate` and only reach the
    # default retrieval path once a human `publish`es them. `rejected` is kept for
    # provenance but never surfaces in search. `origin` records who/what wrote it.
    status: Mapped[str] = mapped_column(String, default="published", index=True)  # candidate|published|rejected
    origin: Mapped[str] = mapped_column(String, default="")  # user:<handle> | agent:<key> | agent:auto-extract
    embedding = mapped_column(EmbeddingType(settings.embed_dim), nullable=True)
    fresh: Mapped[bool] = mapped_column(Boolean, default=False)
    # Auto-triage provenance (AL-227): set when the scorer published/rejected this
    # shard without a human. `scoring_source` ("" = human-only) marks an auto-action
    # and names the signal ("similarity" | "llm"); `auto_confidence` is the score it
    # acted on. Powers the "recent auto-actions" lane and keeps every auto-action undoable.
    scoring_source: Mapped[str] = mapped_column(String, default="", server_default="", nullable=False)
    auto_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Request(Base):
    __tablename__ = "requests"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # frozen; see Item.id
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    number: Mapped[int] = mapped_column(Integer)  # renders as <TAG>-R<number>
    type: Mapped[str] = mapped_column(String)  # bug/feature/enhancement/feedback
    title: Mapped[str] = mapped_column(String)
    detail: Mapped[str] = mapped_column(Text, default="")  # submitter's full description
    by: Mapped[str] = mapped_column(String, default="")
    votes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="new")  # new/triaging/linked
    linked_to: Mapped[str | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    ago: Mapped[str] = mapped_column(String, default="")  # display string from design
    source_url: Mapped[str] = mapped_column(String, default="")  # page the widget was on
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # user_agent, app_version, custom
    attachment_ids: Mapped[list] = mapped_column(JSON, default=list)  # screenshot ids
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("project_id", "number", name="uq_request_number"),)


class Prd(Base):
    __tablename__ = "prds"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # frozen; see Item.id
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    number: Mapped[int] = mapped_column(Integer)  # renders as <TAG>-P<number>
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft/review/approved
    version: Mapped[str] = mapped_column(String, default="v0.1")
    body: Mapped[str] = mapped_column(Text, default="")
    linked: Mapped[list] = mapped_column(JSON, default=list)  # linked item ids
    updated: Mapped[str] = mapped_column(String, default="")  # display date from design
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    versions: Mapped[list[PrdVersion]] = relationship(
        back_populates="prd", cascade="all, delete-orphan", order_by="desc(PrdVersion.id)"
    )

    __table_args__ = (UniqueConstraint("project_id", "number", name="uq_prd_number"),)


class PrdVersion(Base):
    __tablename__ = "prd_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prd_id: Mapped[str] = mapped_column(ForeignKey("prds.id"))
    version: Mapped[str] = mapped_column(String)
    date: Mapped[str] = mapped_column(String, default="")
    note: Mapped[str] = mapped_column(String, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    prd: Mapped[Prd] = relationship(back_populates="versions")


class ProjectTagHistory(Base):
    """A tag a project used to hold, so keys rendered under it keep resolving (PRD-13).

    One row per rename — not one per entity — so this never grows with the corpus. The
    tag is the primary key because reuse is forbidden per deployment (AL-258): letting
    two projects hold `AL` at different times would make `AL-12` ambiguous forever, and
    no ordering by date can fix that once both have an item numbered 12.
    """

    __tablename__ = "project_tag_history"

    tag: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    held_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    held_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LegacyEntityKey(Base):
    """An id issued before project tags existed, kept resolvable forever (PRD-13).

    Seeded once by the tag backfill migration and never appended to again. It exists
    because the old ids used `R-` and `PRD-` as *entity-kind* markers rather than
    project tags, so tag history cannot express them — `PRD-12` was never a project
    tagged `PRD`. Everything issued after the backfill resolves by grammar or by tag
    history instead, so this table's size is fixed at whatever the deployment had.

    `entity_id` points at a FROZEN id, so no chain can ever form here: a second retag
    doesn't invalidate these rows, because the thing they point at cannot move.
    """

    __tablename__ = "legacy_entity_keys"

    old_key: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. AL-12, PRD-4
    entity_type: Mapped[str] = mapped_column(String)  # item | request | prd
    entity_id: Mapped[str] = mapped_column(String, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)


class Link(Base):
    """Typed relationship between two items/requests (dependency/code/semantic/tag)."""

    __tablename__ = "links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    a: Mapped[str] = mapped_column(String)
    b: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String, default="dependency")
    confidence: Mapped[float] = mapped_column(default=1.0)
    reason: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CodeNode(Base):
    """A described unit of the codebase — module / file / symbol — with an agent- or
    LLM-written summary, embedded for semantic search over structure.

    The *producer* is normally the external coding agent (it has the repo in context);
    AgentLedger's connected LLM is the *consumer* that reasons over what's stored. Keyed
    by (project_id, path) so a re-describe upserts. `content_hash` + `fresh` are the
    staleness handle: when a file's hash changes, the agent re-describes and the node is
    marked fresh again; a `prune` pass marks nodes it no longer saw as stale (fresh=False).
    """

    __tablename__ = "code_nodes"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # cn_...
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    path: Mapped[str] = mapped_column(String)  # app/services/items.py  or  ...items.py::create_item
    kind: Mapped[str] = mapped_column(String, default="file")  # module | file | symbol
    name: Mapped[str] = mapped_column(String, default="")  # short label
    lang: Mapped[str] = mapped_column(String, default="")  # python | ts | ...
    summary: Mapped[str] = mapped_column(Text, default="")  # what it is / does / owns
    content_hash: Mapped[str] = mapped_column(String, default="")  # source hash for staleness
    fresh: Mapped[bool] = mapped_column(Boolean, default=True)  # verified this describe pass
    embedding = mapped_column(EmbeddingType(settings.embed_dim), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (UniqueConstraint("project_id", "path", name="uq_code_node_path"),)


class CodeEdge(Base):
    """A directed, typed relation between two code paths — imports / calls / owns /
    tested_by / references. Stored by *path* (not node id) so an edge may point at a node
    that hasn't been described yet (a dangling target is still information)."""

    __tablename__ = "code_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    src: Mapped[str] = mapped_column(String)  # path
    dst: Mapped[str] = mapped_column(String)  # path
    type: Mapped[str] = mapped_column(String, default="imports")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "src", "dst", "type", name="uq_code_edge"),
    )


class CodeRef(Base):
    """A directed link from a tracker item OR request to a code path — the bridge between
    the *work* (ideas/bugs/features) and the *code graph*. Distinct from an item's free-text
    `touchpoints` (fuzzy, glob-matched live): a CodeRef is an explicit, typed, curated edge to
    a specific path. Stored by path so it can point at a not-yet-described node."""

    __tablename__ = "code_refs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    ref_type: Mapped[str] = mapped_column(String)  # item | request
    ref_id: Mapped[str] = mapped_column(String)  # AL-12 / R-31
    path: Mapped[str] = mapped_column(String)  # code node path (may be undescribed)
    relation: Mapped[str] = mapped_column(String, default="affects")  # affects|implements|fixes|tests|references
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "ref_type", "ref_id", "path", "relation", name="uq_code_ref"),
    )


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    phase: Mapped[str] = mapped_column(String)  # mvp | post | later
    title: Mapped[str] = mapped_column(String)
    tag: Mapped[str] = mapped_column(String, default="")
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class McpToolStat(Base):
    __tablename__ = "mcp_tool_stats"

    tool: Mapped[str] = mapped_column(String, primary_key=True)
    calls: Mapped[int] = mapped_column(Integer, default=0)


class PlatformConfig(Base):
    """Per-project platform + integration settings (Phase 5). One row per project."""

    __tablename__ = "platform_config"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    llm_mode: Mapped[str] = mapped_column(String, default="stub")  # legacy: stub | local | cloud
    local_base_url: Mapped[str] = mapped_column(String, default="http://localhost:11434")
    local_model: Mapped[str] = mapped_column(String, default="llama3.1:8b")
    cloud_provider: Mapped[str] = mapped_column(String, default="anthropic")
    cloud_model: Mapped[str] = mapped_column(String, default="claude-opus-4-8")

    # Provider registry (F1 redesign): the active chat provider id + per-provider config
    # (dict keyed by provider id → {api_key, base_url, chat_model, embed_model}). API keys
    # are stored here write-only — never returned raw (see provider_config).
    active_chat_provider: Mapped[str] = mapped_column(String, default="")
    providers: Mapped[dict] = mapped_column(JSON, default=dict)

    # Public sharing (AL-73): a project is publicly readable ONLY when it opts in.
    # The unguessable share_token is how public links address the project, so the
    # raw project_id is never needed (and, in hosted mode, never accepted) — that
    # closes the "name any project_id unauthenticated → cross-tenant read" hole.
    public_share_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    share_token: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)

    github_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    github_account: Mapped[str] = mapped_column(String, default="")
    github_repo: Mapped[str] = mapped_column(String, default="")
    github_scope: Mapped[str] = mapped_column(String, default="")

    gdrive_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    gdrive_account: Mapped[str] = mapped_column(String, default="")
    gdrive_folder: Mapped[str] = mapped_column(String, default="")

    # Local↔cloud hybrid privacy (AL-137, D8): when False, a linked local instance never
    # pushes THIS project's code graph — the summaries describe proprietary source and some
    # teams won't send them off-network. Cloud-side triage/collision-clustering is then weaker.
    sync_graph: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)

    # Spam protection for the public feedback endpoints.
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=20)
    turnstile_sitekey: Mapped[str] = mapped_column(String, default="")  # public; rendered in widget
    turnstile_secret: Mapped[str] = mapped_column(String, default="")  # server-side verify only

    @property
    def turnstile_secret_set(self) -> bool:
        """Whether a secret is configured — surfaced to the UI without leaking it."""
        return bool(self.turnstile_secret)

    @property
    def provider_config(self) -> dict:
        """Per-provider config for the UI — api keys reduced to a `key_set` bool, never raw."""
        out: dict = {}
        for pid, c in (self.providers or {}).items():
            out[pid] = {
                "base_url": c.get("base_url", ""),
                "chat_model": c.get("chat_model", ""),
                "embed_model": c.get("embed_model", ""),
                "key_set": bool(c.get("api_key")),
            }
        return out


class Attachment(Base):
    """A public-uploaded image (bug screenshot) referenced by a feedback request.
    Bytes live in the DB; served public-read by unguessable id."""

    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    content_type: Mapped[str] = mapped_column(String, default="image/png")
    size: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    # The project this key's agent writes to by default. NULL = global key (the agent
    # must pass project_id per call, or it falls back to the default project).
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    name: Mapped[str] = mapped_column(String, default="agent key")
    prefix: Mapped[str] = mapped_column(String)  # e.g. al_sk_ab12 for display
    hashed_key: Mapped[str] = mapped_column(String)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    last_used: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Lifecycle (AL-72): NULL expires_at = non-expiring; revoked is a soft kill switch.
    # verify_api_key rejects a key that is past expiry or revoked.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)

    user: Mapped[User] = relationship(back_populates="api_keys")


class SyncState(Base):
    """Per-PRD last-synced snapshot for the Drive/filesystem sync — powers conflict
    detection (flag when both sides changed since last sync)."""

    __tablename__ = "sync_state"

    prd_id: Mapped[str] = mapped_column(String, primary_key=True)
    file_name: Mapped[str] = mapped_column(String, default="")
    last_hash: Mapped[str] = mapped_column(String, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CodeSyncState(Base):
    """Per-project manifest of the code graph last pushed to the linked cloud tenant (AL-139):
    `manifest` is {path: content_hash} of what the cloud confirmed — the diff base for an
    incremental, resumable push. Updated per confirmed batch so an interrupted push resumes."""

    __tablename__ = "code_sync_state"

    project_id: Mapped[str] = mapped_column(String, primary_key=True)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncLink(Base):
    """Instance-wide link to a cloud tenant (AL-141) — the web-managed counterpart of the
    `agentledger link` CLI. A self-hosted box pushes its code graph to `cloud_url`,
    authenticating with a `sync`-scoped org key held encrypted at rest (`api_key_enc`, the
    same Fernet-at-rest as provider BYOK keys). Singleton (`id="instance"`); a blank
    `cloud_url` means not linked — a pure local-only tool that never reaches out (the D2
    default). When present it OVERRIDES the env `SYNC_CLOUD_URL`/`SYNC_API_KEY`, so linking
    from the UI wins over a baked-in env link."""

    __tablename__ = "sync_link"

    id: Mapped[str] = mapped_column(String, primary_key=True, default="instance")
    cloud_url: Mapped[str] = mapped_column(String, default="")
    api_key_enc: Mapped[str] = mapped_column(String, default="")  # Fernet token; never returned raw
    org: Mapped[str] = mapped_column(String, default="")  # optional label shown in the UI
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class IdempotencyKey(Base):
    """Maps an agent-supplied idempotency key to the resource a create tool produced,
    so a retried call returns the original resource instead of a duplicate."""

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    tool: Mapped[str] = mapped_column(String)
    resource_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Event(Base):
    """Append-only audit log: who did what, when (AL-43). One row per accepted
    mutation, written at the boundary (MCP dispatcher + REST) so the actor's
    identity is captured — the ledger in AgentLedger."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_type: Mapped[str] = mapped_column(String)  # user | apikey | system
    actor_id: Mapped[str] = mapped_column(String, default="")
    actor_label: Mapped[str] = mapped_column(String, default="")  # display name/handle
    surface: Mapped[str] = mapped_column(String)  # mcp | rest | public
    action: Mapped[str] = mapped_column(String)  # e.g. create_item, revoke_api_key
    target_type: Mapped[str] = mapped_column(String, default="")
    target_id: Mapped[str] = mapped_column(String, default="")
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AssistantThread(Base):
    """A conversation with the in-app AI assistant, scoped to one item or PRD (AL-174).

    Threads give brainstorming continuity across sessions and a durable record of what
    the assistant proposed and whether it was applied. `provider`/`model` pin which model
    drives the thread (AL-176 model picker)."""
    __tablename__ = "assistant_threads"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # th_...
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String)  # item | prd
    entity_id: Mapped[str] = mapped_column(String, index=True)
    provider: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String, default="")
    title: Mapped[str] = mapped_column(String, default="")
    # Token metering per conversation (AL-179), accumulated across turns.
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    messages: Mapped[list[AssistantMessage]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", order_by="AssistantMessage.seq")


class AssistantMessage(Base):
    """One ordered turn in an AssistantThread. Carries plain content plus the structured
    tool-calling record (calls the model made, results fed back) and any staged
    proposed-actions with their approval status (AL-177 fills in the approval flow)."""
    __tablename__ = "assistant_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # msg_...
    thread_id: Mapped[str] = mapped_column(ForeignKey("assistant_threads.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # ordering within the thread
    role: Mapped[str] = mapped_column(String)  # user | assistant | tool
    content: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[list] = mapped_column(JSON, default=list)       # [{id, name, input}]
    tool_results: Mapped[list] = mapped_column(JSON, default=list)     # [{id, content, is_error}]
    proposed_actions: Mapped[list] = mapped_column(JSON, default=list) # staged writes + status (AL-177)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    thread: Mapped[AssistantThread] = relationship(back_populates="messages")


class AssistantProposedAction(Base):
    """A write the assistant proposed but has NOT executed (AL-177). Propose-then-approve:
    a write tool call is staged here as `pending`; the human `apply`s (executes + audits,
    capturing `prior_value` for reversibility) or `reject`s. Nothing mutates until approval,
    so prompt-injected content can at most propose a rejected action."""
    __tablename__ = "assistant_proposed_actions"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # pa_...
    thread_id: Mapped[str] = mapped_column(ForeignKey("assistant_threads.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    tool: Mapped[str] = mapped_column(String)          # the write tool name
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(String, default="")  # human-readable diff/summary
    status: Mapped[str] = mapped_column(String, default="pending", index=True)  # pending|applied|rejected|reverted
    prior_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # captured on apply for revert
    provider: Mapped[str] = mapped_column(String, default="")  # origin attribution: assistant:<provider>
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
