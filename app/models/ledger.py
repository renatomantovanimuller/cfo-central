"""Camada 4 — contabilidade financeira pessoal."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base, JSONType
from app.utils.time import utcnow


class EventType:
    INCOME = "INCOME"
    INVESTMENT_INCOME = "INVESTMENT_INCOME"
    EXPENSE = "EXPENSE"
    FINANCIAL_EXPENSE = "FINANCIAL_EXPENSE"
    TAX = "TAX"
    REFUND = "REFUND"
    INTERNAL_TRANSFER = "INTERNAL_TRANSFER"
    EXTERNAL_OWN_TRANSFER = "EXTERNAL_OWN_TRANSFER"
    CARD_PAYMENT = "CARD_PAYMENT"
    INVESTMENT_CONTRIBUTION = "INVESTMENT_CONTRIBUTION"
    INVESTMENT_REDEMPTION = "INVESTMENT_REDEMPTION"
    LOAN_IN = "LOAN_IN"
    LOAN_PAYMENT = "LOAN_PAYMENT"
    IGNORE = "IGNORE"

    ALL = [INCOME, INVESTMENT_INCOME, EXPENSE, FINANCIAL_EXPENSE, TAX, REFUND, INTERNAL_TRANSFER,
           EXTERNAL_OWN_TRANSFER, CARD_PAYMENT, INVESTMENT_CONTRIBUTION, INVESTMENT_REDEMPTION,
           LOAN_IN, LOAN_PAYMENT, IGNORE]
    # entram na DRE
    PNL = {INCOME, INVESTMENT_INCOME, EXPENSE, FINANCIAL_EXPENSE, TAX, REFUND}

    LABELS = {
        INCOME: "Receita", INVESTMENT_INCOME: "Receita financeira", EXPENSE: "Despesa",
        FINANCIAL_EXPENSE: "Despesa financeira", TAX: "Imposto", REFUND: "Estorno/Reembolso",
        INTERNAL_TRANSFER: "Transferência interna", EXTERNAL_OWN_TRANSFER: "Conta própria não conectada",
        CARD_PAYMENT: "Pagamento de fatura", INVESTMENT_CONTRIBUTION: "Aporte",
        INVESTMENT_REDEMPTION: "Resgate", LOAN_IN: "Empréstimo recebido", LOAN_PAYMENT: "Parcela de empréstimo",
        IGNORE: "Ignorar",
    }


class FinancialEvent(Base):
    __tablename__ = "financial_events"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "split_seq", name="uq_event_source"),
        Index("ix_event_competence", "competence_date"),
        Index("ix_event_type_cat", "event_type", "category_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(20), default="transaction")
    source_id: Mapped[str] = mapped_column(String(64))
    split_seq: Mapped[int] = mapped_column(Integer, default=0)
    account_id: Mapped[str | None] = mapped_column(String(64), index=True)
    item_id: Mapped[str | None] = mapped_column(String(64))
    competence_date: Mapped[date] = mapped_column(Date)
    cash_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Float)  # fluxo assinado em BRL (+entrada / −saída)
    event_type: Mapped[str] = mapped_column(String(40))
    category_id: Mapped[str | None] = mapped_column(String(80))
    merchant_id: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    counterparty: Mapped[str | None] = mapped_column(String(200))
    rule_source: Mapped[str] = mapped_column(String(20))  # manual | rule | structural | merchant | pluggy_map | heuristic | default
    rule_id: Mapped[str | None] = mapped_column(String(80))
    confidence: Mapped[float] = mapped_column(Float)
    is_inferred: Mapped[bool] = mapped_column(Boolean, default=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[str | None] = mapped_column(String(200))
    transfer_id: Mapped[int | None] = mapped_column(Integer)
    installment_key: Mapped[str | None] = mapped_column(String(120))
    is_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    is_removed: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSONType)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventOverride(Base):
    __tablename__ = "event_overrides"
    __table_args__ = (UniqueConstraint("source_type", "source_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(20), default="transaction")
    source_id: Mapped[str] = mapped_column(String(64))
    category_id: Mapped[str | None] = mapped_column(String(80))
    event_type: Mapped[str | None] = mapped_column(String(40))
    competence_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class InternalTransfer(Base):
    __tablename__ = "internal_transfers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    out_tx_id: Mapped[str] = mapped_column(String(64), unique=True)
    in_tx_id: Mapped[str] = mapped_column(String(64), unique=True)
    amount: Mapped[float] = mapped_column(Float)
    days_apart: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[float] = mapped_column(Float)


class CardPaymentLink(Base):
    __tablename__ = "card_payment_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_tx_id: Mapped[str] = mapped_column(String(64), unique=True)
    card_account_id: Mapped[str] = mapped_column(String(64))
    card_tx_id: Mapped[str | None] = mapped_column(String(64))
    bill_id: Mapped[str | None] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(30))
    diff: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float)


class ReviewItem(Base):
    __tablename__ = "review_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(160), unique=True)
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10), default="info")  # info | warn | high
    entity_type: Mapped[str | None] = mapped_column(String(30))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(15), default="open")  # open | resolved | dismissed | auto_closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[dict | None] = mapped_column(JSONType)


class LedgerAudit(Base):
    """Log financeiro: toda mudança de classificação de um evento."""
    __tablename__ = "ledger_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    source_type: Mapped[str] = mapped_column(String(20), default="transaction")
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    field: Mapped[str] = mapped_column(String(40))
    old: Mapped[str | None] = mapped_column(Text)
    new: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(20))  # system | user
    reason: Mapped[str | None] = mapped_column(String(200))


class DailyNetWorth(Base):
    """Camada 5 — patrimônio diário com composição e premissas."""
    __tablename__ = "daily_net_worth"
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    cash: Mapped[float] = mapped_column(Float, default=0)
    investments: Mapped[float] = mapped_column(Float, default=0)
    manual_assets: Mapped[float] = mapped_column(Float, default=0)
    card_current: Mapped[float] = mapped_column(Float, default=0)
    card_future: Mapped[float] = mapped_column(Float, default=0)
    loans: Mapped[float] = mapped_column(Float, default=0)
    manual_liabilities: Mapped[float] = mapped_column(Float, default=0)
    net_worth: Mapped[float] = mapped_column(Float, default=0)
    composition: Mapped[dict | None] = mapped_column(JSONType)
    assumptions: Mapped[list | None] = mapped_column(JSONType)
    is_inferred: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
