"""Detecção de recorrências (assinaturas, contas fixas, salário) a partir do razão."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.reviews import ReviewCandidate, fmt_brl
from app.categorization.text import merchant_alias
from app.models import FinancialEvent, Merchant, RecurringRule
from app.utils.time import today_brt


def detect_recurring(s: Session, months: int = 12) -> dict:
    today = today_brt()
    since = today - timedelta(days=31 * months)
    rows = s.execute(select(FinancialEvent).where(
        FinancialEvent.event_type.in_(["EXPENSE", "INCOME", "INVESTMENT_INCOME"]),
        FinancialEvent.is_removed.is_(False), FinancialEvent.competence_date >= since,
        FinancialEvent.installment_key.is_(None))).scalars().all()
    names = {m.id: m.canonical_name for m in s.scalars(select(Merchant))}
    groups: dict[str, list[FinancialEvent]] = defaultdict(list)
    for e in rows:
        direction = "in" if e.amount > 0 else "out"
        key = f"m:{e.merchant_id}:{direction}" if e.merchant_id else f"d:{merchant_alias(e.description)}:{direction}"
        groups[key].append(e)

    existing = {r.key: r for r in s.scalars(select(RecurringRule))}
    found, candidates = 0, []
    for key, evs in groups.items():
        evs.sort(key=lambda e: e.competence_date)
        months_seen = {(e.competence_date.year, e.competence_date.month) for e in evs}
        if len(months_seen) < 3:
            continue
        # um lançamento por mês (o maior) para medir regularidade
        per_month: dict[tuple, FinancialEvent] = {}
        for e in evs:
            k = (e.competence_date.year, e.competence_date.month)
            if k not in per_month or abs(e.amount) > abs(per_month[k].amount):
                per_month[k] = e
        series = sorted(per_month.values(), key=lambda e: e.competence_date)
        amounts = [abs(e.amount) for e in series]
        mean = statistics.mean(amounts)
        cv = statistics.pstdev(amounts) / mean if mean else 1
        direction = "in" if series[0].amount > 0 else "out"
        if cv > (0.6 if direction == "in" else 0.25):
            continue
        gaps = [(b.competence_date - a.competence_date).days for a, b in zip(series, series[1:])]
        gap = statistics.median(gaps) if gaps else 30
        if not 24 <= gap <= 38:
            continue
        last = series[-1]
        if (today - last.competence_date).days > 50:  # parou
            continue
        found += 1
        mid = last.merchant_id
        desc = names.get(mid) if mid else (last.counterparty or last.description)
        r = existing.get(key) or RecurringRule(key=key, status="detected")
        r.description = (desc or last.description or key)[:300]
        r.direction = direction
        r.category_id = last.category_id
        r.expected_amount = round(mean, 2)
        r.amount_std = round(statistics.pstdev(amounts), 2)
        r.frequency_days = int(gap)
        r.day_of_month = int(statistics.median([e.competence_date.day for e in series]))
        r.last_date = last.competence_date
        r.next_date = last.competence_date + timedelta(days=int(gap))
        r.occurrences = len(series)
        s.add(r)
        if direction == "in" and last.category_id in ("rec.pix_terceiros", "rec.outras", "rec.salario") \
                and r.status == "detected" and last.rule_source not in ("manual", "rule", "merchant"):
            candidates.append(ReviewCandidate(
                f"recurring:{key}", "recurring_income", "warn", "recurring", key,
                f"{desc}: cerca de {fmt_brl(mean)} por mês. É salário?",
                f"{len(series)} meses seguidos, por volta do dia {r.day_of_month}. Crie uma regra para classificar.",
                {"merchant_id": mid, "category_id": last.category_id}))
    s.flush()
    return {"found": found, "review_candidates": candidates}
