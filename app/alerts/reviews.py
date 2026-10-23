"""Fila de revisão: candidatos gerados a cada reconstrução; itens resolvidos/dispensados não reabrem."""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.accounting.effective import STALE, SUPERSEDED
from app.models import Account, FinancialEvent, Institution, Item, ReviewItem
from app.utils.time import today_brt, utcnow


@dataclass
class ReviewCandidate:
    fingerprint: str
    kind: str
    severity: str
    entity_type: str | None
    entity_id: str | None
    title: str
    detail: str | None = None
    data: dict = field(default_factory=dict)


def fmt_brl(v: float | None) -> str:
    if v is None:
        return "—"
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if v < 0 else ''}R$ {s}"


def sync_reviews(s: Session, candidates: list[ReviewCandidate]) -> dict:
    existing = {r.fingerprint: r for r in s.scalars(select(ReviewItem))}
    now = utcnow()
    seen = set()
    created = reopened = 0
    for c in candidates:
        if c.fingerprint in seen:
            continue
        seen.add(c.fingerprint)
        r = existing.get(c.fingerprint)
        if r is None:
            s.add(ReviewItem(fingerprint=c.fingerprint, kind=c.kind, severity=c.severity, entity_type=c.entity_type,
                             entity_id=c.entity_id, title=c.title[:300], detail=c.detail, data=c.data,
                             status="open", created_at=now, last_seen_at=now))
            created += 1
        else:
            r.title, r.detail, r.data, r.severity, r.last_seen_at = c.title[:300], c.detail, c.data, c.severity, now
            if r.status == "auto_closed":
                r.status, r.resolved_at = "open", None
                reopened += 1
    closed = 0
    for fp, r in existing.items():
        if fp not in seen and r.status == "open":
            r.status, r.resolved_at = "auto_closed", now
            closed += 1
    s.flush()
    return {"created": created, "reopened": reopened, "auto_closed": closed}


def system_reviews(s: Session) -> list[ReviewCandidate]:
    out: list[ReviewCandidate] = []
    today = today_brt()
    insts = {i.id: i.name for i in s.scalars(select(Institution))}
    for it in s.scalars(select(Item).where(Item.is_active.is_(True))):
        name = it.nickname or insts.get(it.institution_id, it.id[:8])
        if it.status in ("LOGIN_ERROR", "OUTDATED", "WAITING_USER_INPUT"):
            out.append(ReviewCandidate(f"item:{it.id}:status:{it.status}", "item_error", "high", "item", it.id,
                                       f"Conexão {name} com status {it.status}",
                                       "Reconecte em Conexões. Os dados existentes continuam disponíveis."))
        if it.consent_expires_at:
            days = (it.consent_expires_at.date() - today).days
            if days <= 30:
                out.append(ReviewCandidate(f"item:{it.id}:consent", "consent_expiring", "high" if days <= 7 else "warn",
                                           "item", it.id, f"Consentimento de {name} vence em {days} dias",
                                           "Renove a autorização do banco em meu.pluggy.ai."))
        if it.last_sync_status == "error":
            out.append(ReviewCandidate(f"item:{it.id}:sync_error", "sync_error", "warn", "item", it.id,
                                       f"Última sincronização de {name} falhou", "Veja o log técnico em Conexões."))

    # mesma conta em duas conexões ativas (ex.: banco autorizado duas vezes) duplicaria todos os lançamentos
    active = {it.id for it in s.scalars(select(Item).where(Item.is_active.is_(True)))}
    seen: dict[tuple, list[Account]] = defaultdict(list)
    for a in s.scalars(select(Account).where(Account.removed_at.is_(None))):
        if a.item_id in active:
            seen[(a.type, (a.number or "").strip() or a.name, a.subtype)].append(a)
    for accs in seen.values():
        if len({a.item_id for a in accs}) > 1:
            out.append(ReviewCandidate(f"account_dup:{':'.join(sorted(a.id for a in accs))}", "duplicate_account",
                                       "high", "account", accs[0].id, f"Conta repetida em duas conexões: {accs[0].name}",
                                       "Os lançamentos dessa conta entram em dobro. Desative uma das conexões em Conexões."))

    # anomalias: despesa > 3× mediana da categoria (últimos 12 meses, mín. 5 ocorrências) e ≥ R$ 100
    since = today - timedelta(days=365)
    rows = s.execute(select(FinancialEvent.source_id, FinancialEvent.category_id, FinancialEvent.amount,
                            FinancialEvent.competence_date, FinancialEvent.description)
                     .where(FinancialEvent.event_type == "EXPENSE", FinancialEvent.is_removed.is_(False),
                            FinancialEvent.competence_date >= since)).all()
    by_cat: dict[str, list] = defaultdict(list)
    for r in rows:
        by_cat[r.category_id].append(r)
    for cat, items in by_cat.items():
        if len(items) < 5:
            continue
        med = statistics.median(abs(i.amount) for i in items)
        for i in items:
            if abs(i.amount) >= max(100, 3 * med) and (today - i.competence_date).days <= 60:
                out.append(ReviewCandidate(f"tx:{i.source_id}:anomaly", "anomaly", "info", "transaction", i.source_id,
                                           f"Gasto atípico: {i.description} ({fmt_brl(i.amount)})",
                                           f"{abs(i.amount) / med:.1f}× a mediana da categoria ({fmt_brl(-med)})"))

    # duplicidade: mesma conta, mesmo valor, mesma descrição, mesma data, ids diferentes
    dup = s.execute(select(FinancialEvent.account_id, FinancialEvent.competence_date, FinancialEvent.amount,
                           FinancialEvent.description, FinancialEvent.source_id)
                    .where(FinancialEvent.is_removed.is_(False), FinancialEvent.competence_date >= since,
                           # pendente gêmeo de um efetivado já foi descartado do razão: não é duplicidade
                           or_(FinancialEvent.rule_id.is_(None),
                               FinancialEvent.rule_id.not_in([SUPERSEDED, STALE])))).all()
    groups: dict[tuple, list[str]] = defaultdict(list)
    for r in dup:
        groups[(r.account_id, r.competence_date, round(r.amount, 2), (r.description or "").lower())].append(r.source_id)
    for (acc, d, amt, desc), ids in groups.items():
        if len(ids) > 1 and abs(amt) >= 20:
            out.append(ReviewCandidate(f"dup:{acc}:{d}:{amt}:{desc[:40]}", "duplicate", "info", "transaction", ids[0],
                                       f"Possível duplicidade: {desc[:60]} {fmt_brl(amt)} em {d:%d/%m}",
                                       f"{len(ids)} lançamentos iguais. Se for legítimo, dispense.", {"ids": ids}))
    return out
