"""Camada 2 — espelho normalizado dos objetos da Pluggy (significado original preservado)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base, JSONType
from app.utils.time import utcnow


class Provenance:
    """Colunas de rastreabilidade comuns."""
    source: Mapped[str] = mapped_column(String(20), default="pluggy")
    raw_payload_id: Mapped[int | None] = mapped_column(Integer)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Account(Provenance, Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    type: Mapped[str | None] = mapped_column(String(20))  # BANK | CREDIT
    subtype: Mapped[str | None] = mapped_column(String(40))
    name: Mapped[str | None] = mapped_column(String(200))
    marketing_name: Mapped[str | None] = mapped_column(String(200))
    number: Mapped[str | None] = mapped_column(String(60))
    owner: Mapped[str | None] = mapped_column(String(200))
    tax_number: Mapped[str | None] = mapped_column(String(30))
    currency: Mapped[str | None] = mapped_column(String(5))
    balance: Mapped[float | None] = mapped_column(Float)
    bank_data: Mapped[dict | None] = mapped_column(JSONType)
    credit_data: Mapped[dict | None] = mapped_column(JSONType)
    credit_limit: Mapped[float | None] = mapped_column(Float)
    available_credit: Mapped[float | None] = mapped_column(Float)
    bill_close_date: Mapped[date | None] = mapped_column(Date)
    bill_due_date: Mapped[date | None] = mapped_column(Date)
    minimum_payment: Mapped[float | None] = mapped_column(Float)
    brand: Mapped[str | None] = mapped_column(String(40))
    card_sign: Mapped[int] = mapped_column(Integer, default=1)  # amount × sign = fluxo (+entra/−sai)
    last_tx_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountBalance(Base):
    __tablename__ = "account_balances"
    __table_args__ = (UniqueConstraint("account_id", "date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    balance: Mapped[float | None] = mapped_column(Float)
    credit_limit: Mapped[float | None] = mapped_column(Float)
    available_credit: Mapped[float | None] = mapped_column(Float)
    is_inferred: Mapped[bool] = mapped_column(Boolean, default=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Transaction(Provenance, Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("ix_tx_account_date", "account_id", "date"), Index("ix_tx_date", "date"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    item_id: Mapped[str] = mapped_column(String(64), index=True)
    date: Mapped[date] = mapped_column(Date)
    datetime_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    description: Mapped[str | None] = mapped_column(Text)
    description_raw: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[float] = mapped_column(Float)  # valor original Pluggy (sinal da fonte)
    amount_brl: Mapped[float] = mapped_column(Float)  # em BRL, mesmo sinal de amount
    flow: Mapped[float] = mapped_column(Float, default=0.0)  # + entrou / − saiu (normalizado)
    currency: Mapped[str | None] = mapped_column(String(5))
    type: Mapped[str | None] = mapped_column(String(10))  # DEBIT | CREDIT
    status: Mapped[str | None] = mapped_column(String(15))  # POSTED | PENDING
    operation_type: Mapped[str | None] = mapped_column(String(60))
    pluggy_category_id: Mapped[str | None] = mapped_column(String(20))
    pluggy_category: Mapped[str | None] = mapped_column(String(120))
    merchant_name: Mapped[str | None] = mapped_column(String(200))
    merchant_cnpj: Mapped[str | None] = mapped_column(String(20))
    merchant_cnae: Mapped[str | None] = mapped_column(String(20))
    merchant_category: Mapped[str | None] = mapped_column(String(120))
    mcc: Mapped[int | None] = mapped_column(Integer)
    payment_method: Mapped[str | None] = mapped_column(String(20))
    payer_name: Mapped[str | None] = mapped_column(String(200))
    payer_doc: Mapped[str | None] = mapped_column(String(30))
    receiver_name: Mapped[str | None] = mapped_column(String(200))
    receiver_doc: Mapped[str | None] = mapped_column(String(30))
    counterparty_name: Mapped[str | None] = mapped_column(String(200))
    counterparty_doc: Mapped[str | None] = mapped_column(String(30))
    installment_number: Mapped[int | None] = mapped_column(Integer)
    total_installments: Mapped[int | None] = mapped_column(Integer)
    installment_total_amount: Mapped[float | None] = mapped_column(Float)
    bill_id: Mapped[str | None] = mapped_column(String(64))
    purchase_date: Mapped[date | None] = mapped_column(Date)
    provider_id: Mapped[str | None] = mapped_column(String(120))
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreditCardBill(Provenance, Base):
    __tablename__ = "credit_card_bills"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    due_date: Mapped[date | None] = mapped_column(Date)
    close_date: Mapped[date | None] = mapped_column(Date)
    total_amount: Mapped[float | None] = mapped_column(Float)
    minimum_payment: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(5))
    finance_charges: Mapped[list | None] = mapped_column(JSONType)
    payments: Mapped[list | None] = mapped_column(JSONType)


class Investment(Provenance, Base):
    __tablename__ = "investments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"))
    name: Mapped[str | None] = mapped_column(String(300))
    number: Mapped[str | None] = mapped_column(String(60))
    code: Mapped[str | None] = mapped_column(String(60))
    isin: Mapped[str | None] = mapped_column(String(20))
    type: Mapped[str | None] = mapped_column(String(30))
    subtype: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str | None] = mapped_column(String(30))
    currency: Mapped[str | None] = mapped_column(String(5))
    balance: Mapped[float | None] = mapped_column(Float)  # valor líquido atual
    amount: Mapped[float | None] = mapped_column(Float)  # valor bruto
    amount_original: Mapped[float | None] = mapped_column(Float)  # custo
    amount_profit: Mapped[float | None] = mapped_column(Float)
    amount_withdrawal: Mapped[float | None] = mapped_column(Float)
    taxes: Mapped[float | None] = mapped_column(Float)
    taxes2: Mapped[float | None] = mapped_column(Float)
    quantity: Mapped[float | None] = mapped_column(Float)
    value: Mapped[float | None] = mapped_column(Float)  # preço unitário
    rate: Mapped[float | None] = mapped_column(Float)
    rate_type: Mapped[str | None] = mapped_column(String(20))
    fixed_annual_rate: Mapped[float | None] = mapped_column(Float)
    annual_rate: Mapped[float | None] = mapped_column(Float)
    last_month_rate: Mapped[float | None] = mapped_column(Float)
    last_12m_rate: Mapped[float | None] = mapped_column(Float)
    issuer: Mapped[str | None] = mapped_column(String(300))
    issuer_cnpj: Mapped[str | None] = mapped_column(String(30))
    due_date: Mapped[date | None] = mapped_column(Date)
    issue_date: Mapped[date | None] = mapped_column(Date)
    purchase_date: Mapped[date | None] = mapped_column(Date)
    reference_date: Mapped[date | None] = mapped_column(Date)


class InvestmentBalance(Base):
    __tablename__ = "investment_balances"
    __table_args__ = (UniqueConstraint("investment_id", "date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    investment_id: Mapped[str] = mapped_column(ForeignKey("investments.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    balance: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)
    quantity: Mapped[float | None] = mapped_column(Float)
    value: Mapped[float | None] = mapped_column(Float)
    is_inferred: Mapped[bool] = mapped_column(Boolean, default=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InvestmentTransaction(Provenance, Base):
    __tablename__ = "investment_transactions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    investment_id: Mapped[str] = mapped_column(ForeignKey("investments.id", ondelete="CASCADE"), index=True)
    type: Mapped[str | None] = mapped_column(String(20))  # BUY | SELL | ...
    movement_type: Mapped[str | None] = mapped_column(String(20))
    quantity: Mapped[float | None] = mapped_column(Float)
    value: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)
    net_amount: Mapped[float | None] = mapped_column(Float)
    expenses: Mapped[dict | None] = mapped_column(JSONType)
    date: Mapped[date | None] = mapped_column(Date)
    trade_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    brokerage_number: Mapped[str | None] = mapped_column(String(60))


class Loan(Provenance, Base):
    __tablename__ = "loans"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    contract_number: Mapped[str | None] = mapped_column(String(80))
    product_name: Mapped[str | None] = mapped_column(String(200))
    type: Mapped[str | None] = mapped_column(String(80))
    contract_amount: Mapped[float | None] = mapped_column(Float)
    outstanding: Mapped[float | None] = mapped_column(Float)
    next_installment_amount: Mapped[float | None] = mapped_column(Float)
    contract_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    cet: Mapped[float | None] = mapped_column(Float)
    interest_rates: Mapped[list | None] = mapped_column(JSONType)
    installments: Mapped[dict | None] = mapped_column(JSONType)


class IdentityRecord(Base):
    __tablename__ = "identity_records"
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    full_name: Mapped[str | None] = mapped_column(String(200))
    tax_number: Mapped[str | None] = mapped_column(String(30))
    raw_payload_id: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
