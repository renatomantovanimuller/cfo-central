"""Detecção de recorrências (assinaturas, contas fixas, salário) a partir do razão.

Mensais (intervalo de 24–38 dias) e anuais: despesas grandes e infrequentes (IPVA, IPTU, seguro, anuidade,
matrícula) que viram "surpresa" se não forem provisionadas mês a mês ("custos verdadeiros")."""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.reviews import ReviewCandidate, fmt_brl
from app.categorization.text import merchant_alias, norm
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
                {"merchant_id": mid, "category_id": last.category_id, "amount": round(mean, 2),
                 "count": len(series), "confidence": 0.3, "monthly": True}))
    annual, annual_candidates = detect_annual(s, existing, names, today)
    s.flush()
    return {"found": found, "annual": annual, "review_candidates": candidates + annual_candidates}


ANNUAL_CATEGORIES = {"moradia.iptu", "transporte.seguro_impostos", "servicos.seguros"}
ANNUAL_RE = re.compile(r"\bipva\b|\biptu\b|licenciamento|anuidade|\bseguro\b|matricula|material escolar|\bdpvat\b")
ANNUAL_MIN = 150.0          # abaixo disso a provisão mensal não muda decisão nenhuma
ANNUAL_ALERT_DAYS = 60      # aviso antes do vencimento previsto


def detect_annual(s: Session, existing: dict, names: dict, today) -> tuple[int, list[ReviewCandidate]]:
    """Despesas anuais: duas ocorrências com ~1 ano de intervalo e valor parecido, ou (com só ~12 meses de
    histórico, o normal no Open Finance) uma ocorrência isolada de categoria/descrição tipicamente anual."""
    since = today - timedelta(days=430)
    rows = s.execute(select(FinancialEvent).where(
        FinancialEvent.event_type == "EXPENSE", FinancialEvent.is_removed.is_(False),
        FinancialEvent.competence_date >= since, FinancialEvent.amount <= -ANNUAL_MIN,
        FinancialEvent.installment_key.is_(None))).scalars().all()
    groups: dict[str, list[FinancialEvent]] = defaultdict(list)
    for e in rows:
        key = f"m:{e.merchant_id}" if e.merchant_id else f"d:{merchant_alias(e.description)}"
        groups[key].append(e)
    found, candidates = 0, []
    for key, evs in groups.items():
        evs.sort(key=lambda e: e.competence_date)
        months_seen = {(e.competence_date.year, e.competence_date.month) for e in evs}
        if len(months_seen) > 2:  # aparece todo mês ou quase: é mensal (ou parcelado), não anual
            continue
        last = evs[-1]
        amounts = [abs(e.amount) for e in evs]
        if len(evs) >= 2:
            gap = (last.competence_date - evs[0].competence_date).days
            cv = statistics.pstdev(amounts) / statistics.mean(amounts)
            if not (330 <= gap <= 400 and cv <= 0.35):
                continue
            basis = "intervalo anual observado"
        else:
            if not (last.category_id in ANNUAL_CATEGORIES or ANNUAL_RE.search(norm(last.description))):
                continue
            basis = "categoria tipicamente anual (uma ocorrência)"
        if (today - last.competence_date).days > 400:  # passou do vencimento e não se repetiu: parou
            continue
        found += 1
        desc = names.get(last.merchant_id) if last.merchant_id else (last.counterparty or last.description)
        rkey = f"a:{key}"
        r = existing.get(rkey) or RecurringRule(key=rkey, status="detected")
        r.description = (desc or last.description or rkey)[:300]
        r.direction = "out"
        r.category_id = last.category_id
        r.expected_amount = round(abs(last.amount), 2)  # o valor mais recente é o melhor palpite (reajustes)
        r.amount_std = round(statistics.pstdev(amounts), 2) if len(amounts) > 1 else None
        r.frequency_days = 365
        r.day_of_month = last.competence_date.day
        r.last_date = last.competence_date
        r.next_date = last.competence_date + timedelta(days=365)
        r.occurrences = len(evs)
        s.add(r)
        days = (r.next_date - today).days
        if r.status != "ignored" and 0 <= days <= ANNUAL_ALERT_DAYS:
            candidates.append(ReviewCandidate(
                f"annual:{rkey}:{r.next_date.year}", "annual_upcoming", "warn", "recurring", rkey,
                f"{desc}: cerca de {fmt_brl(r.expected_amount)} previsto para {r.next_date:%d/%m/%Y}",
                f"Despesa anual ({basis}). Faltam {days} dias: separe o valor para não sair do orçamento do mês.",
                {"amount": r.expected_amount, "next_date": r.next_date.isoformat()}))
    return found, candidates
