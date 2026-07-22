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
    ForeignKey,
    Integer,
    String,
    Text,
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[list[Membership]] = relationship(back_populates="user")
    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="user")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    accent: Mapped[str] = mapped_column(String, default="#c6f24e")
    visibility: Mapped[str] = mapped_column(String, default="private")
    description: Mapped[str] = mapped_column(Text, default="")
    share_global_memory: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_extract: Mapped[bool] = mapped_column(Boolean, default=True)
    mcp_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    embed_model: Mapped[str] = mapped_column(String, default="stub-384")

    memberships: Mapped[list[Membership]] = relationship(back_populates="project")


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

    id: Mapped[str] = mapped_column(String, primary_key=True)  # human key e.g. AL-12
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="backlog")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    effort: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    blocker: Mapped[str] = mapped_column(String, default="")
    date: Mapped[str] = mapped_column(String, default="")  # display date from design
    reporter: Mapped[dict] = mapped_column(JSON, default=dict)
    pr: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MemoryShard(Base):
    __tablename__ = "memory_shards"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    item_id: Mapped[str | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String, default="global")  # global/item
    source: Mapped[str] = mapped_column(String, default="")
    embedding = mapped_column(EmbeddingType(settings.embed_dim), nullable=True)
    fresh: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Request(Base):
    __tablename__ = "requests"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. R-31
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    type: Mapped[str] = mapped_column(String)  # bug/feature/enhancement/feedback
    title: Mapped[str] = mapped_column(String)
    by: Mapped[str] = mapped_column(String, default="")
    votes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="new")  # new/triaging/linked
    linked_to: Mapped[str | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    ago: Mapped[str] = mapped_column(String, default="")  # display string from design
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Prd(Base):
    __tablename__ = "prds"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. PRD-1
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
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
    llm_mode: Mapped[str] = mapped_column(String, default="stub")  # stub | local | cloud
    local_base_url: Mapped[str] = mapped_column(String, default="http://localhost:11434")
    local_model: Mapped[str] = mapped_column(String, default="llama3.1:8b")
    cloud_provider: Mapped[str] = mapped_column(String, default="anthropic")
    cloud_model: Mapped[str] = mapped_column(String, default="claude-opus-4-8")

    github_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    github_account: Mapped[str] = mapped_column(String, default="")
    github_repo: Mapped[str] = mapped_column(String, default="")
    github_scope: Mapped[str] = mapped_column(String, default="")

    gdrive_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    gdrive_account: Mapped[str] = mapped_column(String, default="")
    gdrive_folder: Mapped[str] = mapped_column(String, default="")


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

    user: Mapped[User] = relationship(back_populates="api_keys")


class IdempotencyKey(Base):
    """Maps an agent-supplied idempotency key to the resource a create tool produced,
    so a retried call returns the original resource instead of a duplicate."""

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    tool: Mapped[str] = mapped_column(String)
    resource_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
