"""Camada 3 — cadastro próprio (adapta a realidade do usuário aos dados da fonte)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base, JSONType
from app.utils.time import utcnow


class Category(Base):
    """Plano de contas pessoal."""
    __tablename__ = "categories"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(String(120))
    nature: Mapped[str] = mapped_column(String(20))  # receita | despesa | financeiro | imposto | patrimonial
    dre_line: Mapped[str | None] = mapped_column(String(40))
    dfc_section: Mapped[str | None] = mapped_column(String(20))
    essential: Mapped[bool] = mapped_column(Boolean, default=False)
    default_event_type: Mapped[str | None] = mapped_column(String(40))
    color: Mapped[str | None] = mapped_column(String(20))
    icon: Mapped[str | None] = mapped_column(String(40))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PluggyCategory(Base):
    __tablename__ = "pluggy_categories"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    description: Mapped[str | None] = mapped_column(String(200))
    description_pt: Mapped[str | None] = mapped_column(String(200))
    parent_id: Mapped[str | None] = mapped_column(String(20))


class PluggyCategoryMap(Base):
    __tablename__ = "pluggy_category_map"
    pluggy_category_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id"))
    confidence: Mapped[float] = mapped_column(Float, default=0.7)


class CategoryRule(Base):
    __tablename__ = "category_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    field: Mapped[str] = mapped_column(String(30))  # description | merchant | cnpj | counterparty | counterparty_doc | pluggy_category | mcc | account
    operator: Mapped[str] = mapped_column(String(15), default="contains")  # contains | equals | starts | regex
    pattern: Mapped[str] = mapped_column(String(300))
    amount_min: Mapped[float | None] = mapped_column(Float)
    amount_max: Mapped[float | None] = mapped_column(Float)
    direction: Mapped[str | None] = mapped_column(String(5))  # in | out
    account_id: Mapped[str | None] = mapped_column(String(64))
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"))
    event_type: Mapped[str | None] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float, default=0.95)
    origin: Mapped[str] = mapped_column(String(15), default="user")  # user | learned | seed
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(200))
    cnpj: Mapped[str | None] = mapped_column(String(20), unique=True)
    cnae: Mapped[str | None] = mapped_column(String(20))
    cnae_desc: Mapped[str | None] = mapped_column(String(200))
    cnae_source: Mapped[str | None] = mapped_column(String(10))  # pluggy | receita
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # última consulta do CNPJ
    default_category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"))
    category_origin: Mapped[str | None] = mapped_column(String(15))  # learned | user
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MerchantAlias(Base):
    __tablename__ = "merchant_aliases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alias: Mapped[str] = mapped_column(String(200), unique=True)  # normalizado
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), index=True)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)  # ticker/ISIN ou chave sintética
    name: Mapped[str | None] = mapped_column(String(300))
    asset_class: Mapped[str] = mapped_column(String(40))
    indexer: Mapped[str | None] = mapped_column(String(20))  # CDI | SELIC | IPCA | PRE | VAR | USD
    liquidity: Mapped[str | None] = mapped_column(String(20))  # D0 | D1 | D2 | D30 | vencimento
    issuer: Mapped[str | None] = mapped_column(String(300))
    fgc_covered: Mapped[bool] = mapped_column(Boolean, default=False)
    yahoo_symbol: Mapped[str | None] = mapped_column(String(30))
    risk_proxy: Mapped[str | None] = mapped_column(String(30))  # yahoo symbol | CDI | SELIC
    origin: Mapped[str] = mapped_column(String(10), default="auto")  # auto | user


class AssetPrice(Base):
    __tablename__ = "asset_prices"
    symbol: Mapped[str] = mapped_column(String(30), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(20), default="yahoo")


class MarketSeries(Base):
    """Séries oficiais: CDI/Selic (% ao dia), IPCA (% ao mês)."""
    __tablename__ = "market_series"
    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[float] = mapped_column(Float)


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("category_id", "month"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id"))
    month: Mapped[str | None] = mapped_column(String(7))  # None = padrão de todo mês
    amount: Mapped[float] = mapped_column(Float)


class RecurringRule(Base):
    __tablename__ = "recurring_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(String(300))
    direction: Mapped[str] = mapped_column(String(5), default="out")
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"))
    expected_amount: Mapped[float] = mapped_column(Float)
    amount_std: Mapped[float | None] = mapped_column(Float)
    frequency_days: Mapped[int] = mapped_column(Integer, default=30)
    day_of_month: Mapped[int | None] = mapped_column(Integer)
    last_date: Mapped[date | None] = mapped_column(Date)
    next_date: Mapped[date | None] = mapped_column(Date)
    occurrences: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(15), default="detected")  # detected | confirmed | ignored
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FinancialGoal(Base):
    __tablename__ = "financial_goals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    target_amount: Mapped[float] = mapped_column(Float)
    target_date: Mapped[date | None] = mapped_column(Date)
    basis: Mapped[str] = mapped_column(String(20), default="net_worth")  # net_worth | investments | asset_class | manual
    asset_class: Mapped[str | None] = mapped_column(String(40))
    manual_current: Mapped[float | None] = mapped_column(Float)
    expected_return_aa: Mapped[float] = mapped_column(Float, default=0.10)
    notes: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default="prazo")  # prazo | aposentadoria | livre
    priority: Mapped[int] = mapped_column(Integer, default=100)     # menor = recebe o aporte antes
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Bucket(Base):
    """Bolso: finalidade do dinheiro (reserva, objetivo, aposentadoria). O que não está em bolso nenhum é "livre"."""
    __tablename__ = "buckets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20), default="objetivo")  # reserva | objetivo | aposentadoria
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("financial_goals.id", ondelete="CASCADE"), unique=True)
    color: Mapped[str | None] = mapped_column(String(20))
    sort: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BucketAllocation(Base):
    """Parte (fração 0–1) de uma conta, investimento ou ativo manual separada para um bolso."""
    __tablename__ = "bucket_allocations"
    __table_args__ = (UniqueConstraint("bucket_id", "source_type", "source_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bucket_id: Mapped[int] = mapped_column(ForeignKey("buckets.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(12))  # account | investment | manual
    source_id: Mapped[str] = mapped_column(String(64))
    pct: Mapped[float] = mapped_column(Float, default=1.0)


class ManualAsset(Base):
    """Ativos/passivos fora do Open Finance."""
    __tablename__ = "manual_assets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))  # asset | liability
    name: Mapped[str] = mapped_column(String(200))
    asset_class: Mapped[str | None] = mapped_column(String(40))
    value: Mapped[float] = mapped_column(Float)
    as_of: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    acquired_at: Mapped[date | None] = mapped_column(Date)       # antes disso o item não entra no patrimônio
    growth_aa: Mapped[float | None] = mapped_column(Float)       # atualização anual (índice; negativo = depreciação)


class ManualAssetValue(Base):
    """Histórico de valores de um item manual (cada atualização vira um ponto)."""
    __tablename__ = "manual_asset_values"
    __table_args__ = (UniqueConstraint("manual_asset_id", "date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manual_asset_id: Mapped[int] = mapped_column(ForeignKey("manual_assets.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Float)


class AccountSetting(Base):
    __tablename__ = "account_settings"
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    nickname: Mapped[str | None] = mapped_column(String(120))
    purpose: Mapped[str | None] = mapped_column(String(40))  # corrente | reserva | cartao_principal ...
    include_in_net_worth: Mapped[bool] = mapped_column(Boolean, default=True)
    extra: Mapped[dict | None] = mapped_column(JSONType)


class AppSetting(Base):
    """Preferências do usuário em chave/valor (plano financeiro, alertas)."""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict | None] = mapped_column(JSONType)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AllocationTarget(Base):
    """Política de investimentos: alocação-alvo por classe com banda de tolerância (definida pelo usuário)."""
    __tablename__ = "allocation_targets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(60), unique=True)
    target_pct: Mapped[float] = mapped_column(Float)
    min_pct: Mapped[float | None] = mapped_column(Float)
    max_pct: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class NotificationLog(Base):
    """Alertas enviados por e-mail (evita repetir o mesmo aviso)."""
    __tablename__ = "notification_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(20))
    fingerprint: Mapped[str] = mapped_column(String(200), index=True)
    subject: Mapped[str] = mapped_column(String(300))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="sent")
    error: Mapped[str | None] = mapped_column(Text)


class HealthRun(Base):
    """Resultado de cada rodada das verificações de saúde dos dados."""
    __tablename__ = "health_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    trigger: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10))  # ok | info | atencao | falha
    summary: Mapped[dict | None] = mapped_column(JSONType)
    results: Mapped[list | None] = mapped_column(JSONType)
