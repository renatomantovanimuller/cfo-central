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
DUP_PAYMENT = "card_payment:duplicate"
PAYMENT_TWIN_DAYS = 2
BILL_TOLERANCE = 1.0
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
    """IDs a excluir de qualquer soma/leitura de razão: pendentes duplicados ou velhos e pagamentos de fatura
    que a fonte entregou em dobro."""
    rows = list(s.scalars(select(Transaction).where(Transaction.removed_at.is_(None))))
    return set(ineffective_pending(rows, today, stale_days, _account_types(s))) | set(duplicate_card_payments(s, rows))


def effective_transactions(s: Session, today: date | None = None, stale_days: int | None = None) -> list[Transaction]:
    """Transações não removidas, sem pendentes duplicados ou velhos e sem pagamento de fatura repetido."""
    rows = list(s.scalars(select(Transaction).where(Transaction.removed_at.is_(None))))
    bad = set(ineffective_pending(rows, today, stale_days, _account_types(s))) | set(duplicate_card_payments(s, rows))
    return [t for t in rows if t.id not in bad]


def duplicate_card_payments(s: Session, rows: list[Transaction] | None = None) -> dict[str, str]:
    """Pagamentos de fatura que chegaram duas vezes no cartão (ex.: "Pagamento recebido" e "pagamento on line"
    do mesmo valor no mesmo dia, cada um ligado a uma fatura). Só descarta a cópia quando a conta das faturas
    prova o erro: sem ela, toda fatura afetada fecha (total = anterior + lançamentos) e, com ela, não fecha."""
    from app.models import CreditCardBill
    types = _account_types(s)
    rows = rows if rows is not None else list(s.scalars(select(Transaction).where(Transaction.removed_at.is_(None))))
    pend = ineffective_pending(rows, account_types=types)
    live = [t for t in rows if t.id not in pend and types.get(t.account_id) == "CREDIT"]
    bills = [b for b in s.scalars(select(CreditCardBill).where(CreditCardBill.removed_at.is_(None))) if b.due_date]
    if not bills:
        return {}
    by_acc: dict[str, list] = defaultdict(list)
    for b in bills:
        by_acc[b.account_id].append(b)
    prev_of: dict[str, object] = {}
    for bs in by_acc.values():
        bs.sort(key=lambda b: b.due_date)
        for p, c in zip(bs, bs[1:]):
            if (c.due_date - p.due_date).days <= 40 and p.total_amount is not None and c.total_amount is not None:
                prev_of[c.id] = p
    sums: dict[str, float] = defaultdict(float)
    for t in live:
        if t.bill_id:
            sums[t.bill_id] += t.amount_brl or 0.0
    bill_by_id = {b.id: b for b in bills}

    def closes(bill_id: str, adjust: float = 0.0) -> bool | None:
        b, p = bill_by_id.get(bill_id), prev_of.get(bill_id)
        if b is None or p is None:
            return None
        return abs(b.total_amount - (p.total_amount + sums[bill_id] + adjust)) <= BILL_TOLERANCE

    pays: dict = defaultdict(list)
    for t in live:
        if t.status != "PENDING" and _is_payment(norm(t.description or "")) and (t.amount_brl or 0) < 0:
            pays[(t.account_id, round(abs(t.amount_brl), 2))].append(t)
    out: dict[str, str] = {}
    # várias passadas: corrigir uma fatura pode ser o que faltava para a cópia de outro pagamento se provar
    for _ in range(4):
        before = len(out)
        _drop_twins(pays, out, closes, sums)
        if len(out) == before:
            break
    return out


def _drop_twins(pays: dict, out: dict, closes, sums: dict) -> None:
    for group in pays.values():
        group.sort(key=lambda t: t.date)
        for a, b in zip(group, group[1:]):
            if a.id in out or b.id in out or abs((b.date - a.date).days) > PAYMENT_TWIN_DAYS or a.bill_id == b.bill_id:
                continue
            for drop, keep in ((a, b), (b, a)):
                if not drop.bill_id or closes(drop.bill_id) is not False:
                    continue
                if closes(drop.bill_id, -(drop.amount_brl or 0.0)) and closes(keep.bill_id) is not False:
                    out[drop.id] = DUP_PAYMENT
                    sums[drop.bill_id] -= drop.amount_brl or 0.0
                    break
