"""Conferência fatura a fatura: total informado pelo banco × (saldo da fatura anterior + lançamentos ligados a ela).
Mesma base da saúde dos dados: ignora pendentes repetidos/velhos e pagamentos que a fonte entregou em dobro."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounting.effective import BILL_TOLERANCE, duplicate_card_payments, excluded_pending_ids, _is_payment
from app.categorization.text import norm
from app.models import CreditCardBill, Transaction


def reconcile_bills(s: Session) -> dict[str, list[dict]]:
    """{account_id: [fatura, mais recente primeiro]} com compras, créditos, pagamentos, diferença e situação."""
    excluded = excluded_pending_ids(s)
    dups = duplicate_card_payments(s)
    parts: dict[str, dict] = defaultdict(lambda: {"compras": 0.0, "creditos": 0.0, "pagamentos": 0.0, "n": 0})
    dropped: dict[str, list] = defaultdict(list)
    for t in s.scalars(select(Transaction).where(Transaction.bill_id.is_not(None), Transaction.removed_at.is_(None))):
        v = t.amount_brl or 0.0
        if t.id in dups:
            dropped[t.bill_id].append({"data": t.date, "descricao": t.description, "valor": round(v, 2)})
            continue
        if t.id in excluded:
            continue
        p = parts[t.bill_id]
        p["n"] += 1
        if v >= 0:
            p["compras"] += v
        elif _is_payment(norm(t.description or "")):
            p["pagamentos"] += v
        else:
            p["creditos"] += v
    by_acc: dict[str, list] = defaultdict(list)
    for b in s.scalars(select(CreditCardBill).where(CreditCardBill.removed_at.is_(None))):
        if b.due_date:
            by_acc[b.account_id].append(b)
    out: dict[str, list[dict]] = {}
    for acc, bills in by_acc.items():
        bills.sort(key=lambda b: b.due_date)
        rows = []
        for i, b in enumerate(bills):
            p = parts[b.id]
            prev = bills[i - 1] if i and (b.due_date - bills[i - 1].due_date).days <= 40 else None
            net = p["compras"] + p["creditos"] + p["pagamentos"]
            row = {"id": b.id, "due_date": b.due_date, "close_date": b.close_date, "total": b.total_amount,
                   "minimum": b.minimum_payment, "charges": b.finance_charges,
                   "anterior": prev.total_amount if prev else None, "compras": round(p["compras"], 2),
                   "creditos": round(p["creditos"], 2), "pagamentos": round(p["pagamentos"], 2), "lancamentos": p["n"],
                   "duplicados_descartados": dropped.get(b.id, [])}
            if prev is None or prev.total_amount is None or b.total_amount is None:
                row.update(diferenca=None, situacao="sem_anterior")
            else:
                diff = b.total_amount - (prev.total_amount + net)
                row.update(diferenca=round(diff, 2), situacao="ok" if abs(diff) <= BILL_TOLERANCE
                           else "falta_lancamento" if diff > 0 else "sobra_lancamento")
            rows.append(row)
        out[acc] = list(reversed(rows))
    return out
