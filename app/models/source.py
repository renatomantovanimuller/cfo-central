"""Camada 1 — fonte e integração."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base, JSONType
from app.utils.time import utcnow


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Institution(Base):
    __tablename__ = "institutions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # connector id Pluggy
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str | None] = mapped_column(String(40))
    image_url: Mapped[str | None] = mapped_column(String(500))
    primary_color: Mapped[str | None] = mapped_column(String(20))
    is_open_finance: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=False)


class Item(Base):
    __tablename__ = "items"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"))
    nickname: Mapped[str | None] = mapped_column(String(120))
    client_user_id: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str | None] = mapped_column(String(40))
    execution_status: Mapped[str | None] = mapped_column(String(60))
    status_detail: Mapped[dict | None] = mapped_column(JSONType)
    error: Mapped[dict | None] = mapped_column(JSONType)
    products: Mapped[list | None] = mapped_column(JSONType)
    consent_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_auto_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # pluggy | market | ledger
    trigger: Mapped[str] = mapped_column(String(20))  # manual | schedule | webhook | startup | cli
    item_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | ok | partial | error
    stats: Mapped[dict | None] = mapped_column(JSONType)
    error: Mapped[str | None] = mapped_column(Text)


class SyncEvent(Base):
    """Log técnico."""
    __tablename__ = "sync_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("sync_runs.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    level: Mapped[str] = mapped_column(String(10))  # info | warn | error
    step: Mapped[str] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSONType)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event: Mapped[str | None] = mapped_column(String(80))
    event_id: Mapped[str | None] = mapped_column(String(80))
    item_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict | None] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(20), default="received")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawPayload(Base):
    """Payload bruto versionado: uma linha por (entidade, id, hash). Nunca é alterado."""
    __tablename__ = "raw_payloads"
    __table_args__ = (
        UniqueConstraint("source", "entity_type", "external_id", "payload_hash", name="uq_raw_version"),
        Index("ix_raw_entity", "entity_type", "external_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(20), default="pluggy")
    entity_type: Mapped[str] = mapped_column(String(40))
    external_id: Mapped[str] = mapped_column(String(80))
    item_id: Mapped[str | None] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSONType)
    payload_hash: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    run_id: Mapped[int | None] = mapped_column(Integer)
