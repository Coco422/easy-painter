"""Agent authorization is independent of browser sessions and billing ledgers."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentClient(Base):
    __tablename__ = "agent_clients"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(100))
    redirect_uris: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentGrant(Base):
    __tablename__ = "agent_grants"
    __table_args__ = (CheckConstraint("max_per_job >= 0 AND daily_limit >= max_per_job", name="ck_agent_grant_limits"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_clients.id"))
    resource: Mapped[str] = mapped_column(String(2048))
    label: Mapped[str] = mapped_column(String(100))
    scopes: Mapped[list] = mapped_column(JSON)
    password_digest: Mapped[str] = mapped_column(String(64))
    max_per_job: Mapped[int] = mapped_column(Integer)
    daily_limit: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentAuthorization(Base):
    __tablename__ = "agent_authorizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    client_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_clients.id"))
    redirect_uri: Mapped[str] = mapped_column(String(2048))
    state: Mapped[str] = mapped_column(String(1024))
    challenge: Mapped[str] = mapped_column(String(43))
    scopes: Mapped[list] = mapped_column(JSON)
    resource: Mapped[str] = mapped_column(String(2048))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    grant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agent_grants.id", ondelete="CASCADE"), nullable=True)
    code_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentCredential(Base):
    __tablename__ = "agent_credentials"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    grant_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_grants.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentUsage(Base):
    __tablename__ = "agent_usage"
    __table_args__ = (UniqueConstraint("grant_id", "request_key", name="uq_agent_usage_request"),)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("generation_jobs.id", ondelete="CASCADE"), primary_key=True)
    grant_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_grants.id", ondelete="CASCADE"), index=True)
    request_key: Mapped[str] = mapped_column(String(128))
    request_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
