"""Ponto único de "transações efetivas": o que de fato conta para razão, saldo histórico do cartão e saúde.

Duas regras sobre lançamentos PENDING (a fonte Open Finance continua enviando o pendente depois de efetivar):
- superseded: existe POSTED equivalente (mesma conta, mesmo |valor|, data ±3 dias, descrição compatível);
- stale: pendente há mais de N dias sem efetivação (N=10 na conta, 40 no cartão, onde pendente = compra ainda não faturada) (cancelado/estornado pelo banco).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.categorization.text import norm
from app.config.settings import get_settings
from app.models import Account, Transaction
from app.utils.time import today_brt

SUPERSEDED = "pending:superseded"
STALE = "pending:stale"
TWIN_WINDOW_DAYS = 3
PREFIX_LEN = 8


def _is_payment(desc: str) -> bool:
    return "pagament" in desc or "pgto" in desc


def _compatible(pend, posted) -> bool:
    """Descrições compatíveis: mesmo prefixo normalizado, ou ambos pagamento de fatura; parcelas só casam
    com a mesma parcela."""
    if pend.total_installments and (pend.installment_number or 0) != (posted.installment_number or 0):
        return False
    a, b = norm(pend.description or ""), norm(posted.description or "")
    return a[:PREFIX_LEN] == b[:PREFIX_LEN] or (_is_payment(a) and _is_payment(b))


def _amount(t) -> float:
    return round(abs(t.flow or 0.0), 2)


def find_posted_twin(pend, posted_by_key: dict):
    """Primeiro POSTED equivalente do pendente, ou None."""
    for t in posted_by_key.get((pend.account_id, _amount(pend)), []):
        if abs((t.date - pend.date).days) <= TWIN_WINDOW_DAYS and _compatible(pend, t):
            return t
    return None


def ineffective_pending(txs: Iterable, today: date | None = None, stale_days: int | None = None,
                        account_types: dict[str, str] | None = None) -> dict[str, str]:
    """{id: motivo} dos pendentes que não contam. `txs` precisa de id, account_id, flow, date, status,
    description, installment_number, total_installments e `removed`/`removed_at` (removidos são ignorados)."""
    today = today or today_brt()
    cfg = get_settings()
    types = account_types or {}

    def limit_for(t) -> int:
        if stale_days is not None:
            return stale_days
        kind = types.get(t.account_id) or getattr(t, "account_type", "BANK")
        return cfg.pending_stale_days_card if kind == "CREDIT" else cfg.pending_stale_days
    live = [t for t in txs if not (getattr(t, "removed", False) or getattr(t, "removed_at", None))]
    posted: dict = defaultdict(list)
    for t in live:
        if t.status != "PENDING":
            posted[(t.account_id, _amount(t))].append(t)
    out: dict[str, str] = {}
    for t in live:
        if t.status != "PENDING":
            continue
        if find_posted_twin(t, posted) is not None:
            out[t.id] = SUPERSEDED
        elif (today - t.date).days > limit_for(t):
            out[t.id] = STALE
    return out


def _account_types(s: Session) -> dict[str, str]:
    return dict(s.execute(select(Account.id, Account.type)).all())


def excluded_pending_ids(s: Session, today: date | None = None, stale_days: int | None = None) -> set[str]:
    """IDs de transações pendentes a excluir de qualquer soma/leitura de razão."""
    rows = list(s.scalars(select(Transaction).where(Transaction.removed_at.is_(None))))
    return set(ineffective_pending(rows, today, stale_days, _account_types(s)))


def effective_transactions(s: Session, today: date | None = None, stale_days: int | None = None) -> list[Transaction]:
    """Transações não removidas, sem pendentes duplicados ou velhos."""
    rows = list(s.scalars(select(Transaction).where(Transaction.removed_at.is_(None))))
    bad = ineffective_pending(rows, today, stale_days, _account_types(s))
    return [t for t in rows if t.id not in bad]
