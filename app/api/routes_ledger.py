"""Razão (eventos), ajustes manuais com aprendizado, regras, comerciantes, categorias, revisões."""
from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.accounting.ledger import load_tx_views
from app.analytics import overview as O
from app.auth.security import CurrentUser
from app.categorization.engine import compile_rules, match_rule
from app.database.session import get_db
from app.models import (Account, AccountSetting, Budget, CardPaymentLink, Category, CategoryRule, EventOverride,
                        EventType, FinancialEvent, InternalTransfer, LedgerAudit, Merchant, RawPayload,
                        ReviewItem, Transaction)
from app.services.pipeline import pipeline
from app.utils.time import month_bounds, utcnow

router = APIRouter(prefix="/api", dependencies=[CurrentUser])


def _descendants(db: Session, cid: str) -> list[str]:
    cats = list(db.scalars(select(Category)))
    out, frontier = {cid}, {cid}
    while frontier:
        frontier = {c.id for c in cats if c.parent_id in frontier} - out
        out |= frontier
    return list(out)


# ------------------------------------------------------------------ eventos (razão)
@router.get("/events")
def list_events(month: str | None = None, start: date | None = None, end: date | None = None,
                account: str | None = None, category: str | None = None, event_type: str | None = None,
                merchant: int | None = None, q: str | None = None, review: bool | None = None,
                min_amount: float | None = None, max_amount: float | None = None, direction: str | None = None,
                include_removed: bool = False, page: int = 1, page_size: int = 100, sort: str = "-date",
                db: Session = Depends(get_db)) -> dict:
    cond = []
    if not include_removed:
        cond.append(FinancialEvent.is_removed.is_(False))
    if month:
        a, b = month_bounds(month)
        cond.append(FinancialEvent.competence_date.between(a, b))
    if start:
        cond.append(FinancialEvent.competence_date >= start)
    if end:
        cond.append(FinancialEvent.competence_date <= end)
    if account:
        cond.append(FinancialEvent.account_id == account)
    if category:
        cond.append(FinancialEvent.category_id.in_(_descendants(db, category)))
    if event_type:
        cond.append(FinancialEvent.event_type.in_(event_type.split(",")))
    if merchant:
        cond.append(FinancialEvent.merchant_id == merchant)
    if review is not None:
        cond.append(FinancialEvent.needs_review.is_(review))
    if direction == "in":
        cond.append(FinancialEvent.amount > 0)
    elif direction == "out":
        cond.append(FinancialEvent.amount < 0)
    if min_amount is not None:
        cond.append(func.abs(FinancialEvent.amount) >= min_amount)
    if max_amount is not None:
        cond.append(func.abs(FinancialEvent.amount) <= max_amount)
    if q:
        like = f"%{q}%"
        cond.append(or_(FinancialEvent.description.ilike(like), FinancialEvent.counterparty.ilike(like),
                        FinancialEvent.note.ilike(like)))
    base = select(FinancialEvent).where(*cond)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    sums = db.execute(select(func.coalesce(func.sum(FinancialEvent.amount).filter(FinancialEvent.amount > 0), 0),
                             func.coalesce(func.sum(FinancialEvent.amount).filter(FinancialEvent.amount < 0), 0))
                      .where(*cond)).one()
    order = {"date": FinancialEvent.competence_date, "amount": FinancialEvent.amount,
             "confidence": FinancialEvent.confidence}.get(sort.lstrip("-"), FinancialEvent.competence_date)
    order = order.desc() if sort.startswith("-") else order.asc()
    rows = db.scalars(base.order_by(order, FinancialEvent.id.desc()).limit(page_size).offset((page - 1) * page_size)).all()
    cats = {c.id: c for c in db.scalars(select(Category))}
    accs = {a.id: a for a in db.scalars(select(Account))}
    sets = {x.account_id: x.nickname for x in db.scalars(select(AccountSetting))}
    txs = {t.id: t for t in db.scalars(select(Transaction).where(Transaction.id.in_([r.source_id for r in rows] or ["-"])))}
    items = []
    for e in rows:
        c = cats.get(e.category_id)
        a = accs.get(e.account_id)
        t = txs.get(e.source_id)
        items.append({
            "id": e.source_id, "date": e.competence_date, "cash_date": e.cash_date, "description": e.description,
            "counterparty": e.counterparty, "merchant_id": e.merchant_id, "amount": e.amount,
            "event_type": e.event_type, "event_label": EventType.LABELS.get(e.event_type, e.event_type),
            "category_id": e.category_id, "category": c.name if c else None,
            "parent_category": cats[c.parent_id].name if c and c.parent_id in cats else None,
            "color": (cats[c.parent_id].color if c and c.parent_id in cats else (c.color if c else None)),
            "account_id": e.account_id, "account": sets.get(e.account_id) or (a.name if a else None),
            "account_type": a.type if a else None, "rule_source": e.rule_source, "rule_id": e.rule_id,
            "confidence": e.confidence, "needs_review": e.needs_review, "review_reason": e.review_reason,
            "is_pending": e.is_pending, "is_removed": e.is_removed, "note": e.note, "tags": e.tags,
            "installment": f"{t.installment_number}/{t.total_installments}" if t and t.total_installments and t.total_installments > 1 else None,
            "payment_method": t.payment_method if t else None,
        })
    return {"total": total, "inflow": float(sums[0]), "outflow": float(sums[1]), "page": page,
            "page_size": page_size, "items": items}


@router.get("/events/{source_id}")
def event_detail(source_id: str, db: Session = Depends(get_db)) -> dict:
    e = db.scalar(select(FinancialEvent).where(FinancialEvent.source_id == source_id))
    t = db.get(Transaction, source_id)
    if not e or not t:
        raise HTTPException(404)
    raw = db.get(RawPayload, t.raw_payload_id) if t.raw_payload_id else None
    versions = db.scalars(select(RawPayload).where(RawPayload.entity_type == "transaction",
                                                   RawPayload.external_id == source_id)
                          .order_by(RawPayload.first_seen_at)).all()
    audit = [{"at": a.at, "field": a.field, "old": a.old, "new": a.new, "actor": a.actor, "reason": a.reason}
             for a in db.scalars(select(LedgerAudit).where(LedgerAudit.source_id == source_id).order_by(LedgerAudit.id))]
    ov = db.scalar(select(EventOverride).where(EventOverride.source_id == source_id))
    transfer = db.scalar(select(InternalTransfer).where(or_(InternalTransfer.out_tx_id == source_id,
                                                            InternalTransfer.in_tx_id == source_id)))
    card = db.scalar(select(CardPaymentLink).where(or_(CardPaymentLink.payment_tx_id == source_id,
                                                       CardPaymentLink.card_tx_id == source_id)))
    rule = None
    if e.rule_id and e.rule_id.startswith("rule:"):
        r = db.get(CategoryRule, int(e.rule_id.split(":")[1]))
        rule = {"id": r.id, "field": r.field, "operator": r.operator, "pattern": r.pattern} if r else None
    merchant = db.get(Merchant, e.merchant_id) if e.merchant_id else None
    return {
        "event": {c.name: getattr(e, c.name) for c in FinancialEvent.__table__.columns},
        "transaction": {c.name: getattr(t, c.name) for c in Transaction.__table__.columns},
        "raw_payload": raw.payload if raw else None,
        "provenance": {"source": t.source, "item_id": t.item_id, "external_id": t.id, "first_seen_at": t.first_seen_at,
                       "last_seen_at": t.last_seen_at, "source_updated_at": t.source_updated_at,
                       "raw_versions": [{"id": v.id, "first_seen_at": v.first_seen_at, "hash": v.payload_hash[:12]}
                                        for v in versions]},
        "override": {"category_id": ov.category_id, "event_type": ov.event_type, "note": ov.note,
                     "competence_date": ov.competence_date} if ov else None,
        "rule": rule, "audit": audit,
        "merchant": {"id": merchant.id, "name": merchant.canonical_name, "doc": merchant.cnpj,
                     "default_category_id": merchant.default_category_id} if merchant else None,
        "transfer": {"out": transfer.out_tx_id, "in": transfer.in_tx_id, "method": transfer.method} if transfer else None,
        "card_link": {"payment": card.payment_tx_id, "card_tx": card.card_tx_id, "bill_id": card.bill_id,
                      "method": card.method, "diff": card.diff} if card else None,
    }


class EventPatch(BaseModel):
    category_id: str | None = None
    event_type: str | None = None
    note: str | None = None
    competence_date: date | None = None
    tags: list[str] | None = None
    learn: bool = True  # ensina o comerciante
    clear: bool = False


STRUCTURAL_TYPES = {EventType.INTERNAL_TRANSFER, EventType.EXTERNAL_OWN_TRANSFER, EventType.CARD_PAYMENT,
                    EventType.INVESTMENT_CONTRIBUTION, EventType.INVESTMENT_REDEMPTION}


def _apply_override(db: Session, source_id: str, body: EventPatch, actor: str = "user") -> None:
    if body.event_type and body.event_type not in EventType.ALL:
        raise HTTPException(400, "tipo de evento inválido")
    if body.category_id and not db.get(Category, body.category_id):
        raise HTTPException(400, "categoria inexistente")
    ov = db.scalar(select(EventOverride).where(EventOverride.source_id == source_id))
    if body.clear:
        if ov:
            db.delete(ov)
        return
    if ov is None:
        ov = EventOverride(source_type="transaction", source_id=source_id)
        db.add(ov)
    data = body.model_dump(exclude_unset=True, exclude={"learn", "clear"})
    for k, v in data.items():
        setattr(ov, k, v)
    ov.updated_at = utcnow()
    db.add(LedgerAudit(source_id=source_id, field="override", old=None,
                       new=str({k: str(v) for k, v in data.items()}), actor=actor, reason="ajuste manual"))
    if body.learn and body.category_id:
        e = db.scalar(select(FinancialEvent).where(FinancialEvent.source_id == source_id))
        # movimentações estruturais (transferência própria, fatura, aporte/resgate) não ensinam o comerciante:
        # reclassificar uma entrada vinda da sua outra conta não pode virar padrão para todas as transferências
        if e and e.merchant_id and e.rule_source != "structural" and e.event_type not in STRUCTURAL_TYPES:
            m = db.get(Merchant, e.merchant_id)
            if m:
                m.default_category_id, m.category_origin = body.category_id, "user"


@router.patch("/events/{source_id}")
def patch_event(source_id: str, body: EventPatch, db: Session = Depends(get_db)) -> dict:
    if not db.get(Transaction, source_id):
        raise HTTPException(404)
    _apply_override(db, source_id, body)
    db.commit()
    res = pipeline.rebuild_now("user")
    return {"ok": True, "changed": res.get("counts", {}).get("changed", 0)}


class BulkPatch(EventPatch):
    ids: list[str]


@router.post("/events/bulk")
def bulk_patch(body: BulkPatch, db: Session = Depends(get_db)) -> dict:
    for sid in body.ids:
        _apply_override(db, sid, body)
    db.commit()
    res = pipeline.rebuild_now("user")
    return {"ok": True, "updated": len(body.ids), "changed": res.get("counts", {}).get("changed", 0)}


# ------------------------------------------------------------------ regras
class RuleBody(BaseModel):
    name: str | None = None
    priority: int = 100
    field: str = "description"
    operator: str = "contains"
    pattern: str
    amount_min: float | None = None
    amount_max: float | None = None
    direction: str | None = None
    account_id: str | None = None
    category_id: str | None = None
    event_type: str | None = None
    active: bool = True


RULE_FIELDS = {"description", "merchant", "merchant_id", "cnpj", "counterparty_doc", "pluggy_category", "mcc",
               "account"}


def _validate_rule(body: RuleBody) -> None:
    if not (body.category_id or body.event_type):
        raise HTTPException(400, "informe categoria e/ou tipo de evento")
    if body.field not in RULE_FIELDS:
        raise HTTPException(400, f"campo de regra inválido: {body.field}")
    if body.field == "merchant_id" and not body.pattern.strip().isdigit():
        raise HTTPException(400, "merchant_id: informe o número do comerciante")
    if body.operator == "regex":
        try:
            re.compile(body.pattern)
        except re.error as e:
            raise HTTPException(400, f"regex inválida: {e}") from e


@router.get("/rules")
def list_rules(db: Session = Depends(get_db)) -> list[dict]:
    cats = {c.id: c.name for c in db.scalars(select(Category))}
    return [{**{c.name: getattr(r, c.name) for c in CategoryRule.__table__.columns}, "category": cats.get(r.category_id)}
            for r in db.scalars(select(CategoryRule).order_by(CategoryRule.priority, CategoryRule.id))]


@router.post("/rules/preview")
def preview_rule(body: RuleBody, db: Session = Depends(get_db)) -> dict:
    _validate_rule(body)
    rule = CategoryRule(id=-1, **body.model_dump())
    compiled = compile_rules([rule])
    mids = dict(db.execute(select(FinancialEvent.source_id, FinancialEvent.merchant_id)
                           .where(FinancialEvent.merchant_id.is_not(None))).all())
    hits = [t for t in load_tx_views(db) if not t.removed and match_rule(t, compiled, mids.get(t.id))]
    return {"count": len(hits), "total": round(sum(t.flow for t in hits), 2),
            "sample": [{"id": t.id, "date": t.date, "description": t.description, "amount": t.flow} for t in hits[:25]]}


def add_rule(db: Session, body: RuleBody) -> CategoryRule:
    _validate_rule(body)
    r = CategoryRule(**body.model_dump(), origin="user")
    db.add(r)
    db.flush()
    return r


@router.post("/rules")
def create_rule(body: RuleBody, db: Session = Depends(get_db)) -> dict:
    r = add_rule(db, body)
    db.commit()
    res = pipeline.rebuild_now("rule")
    return {"ok": True, "id": r.id, "changed": res.get("counts", {}).get("changed", 0)}


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleBody, db: Session = Depends(get_db)) -> dict:
    r = db.get(CategoryRule, rule_id)
    if not r:
        raise HTTPException(404)
    _validate_rule(body)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    db.commit()
    pipeline.rebuild_now("rule")
    return {"ok": True}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)) -> dict:
    r = db.get(CategoryRule, rule_id)
    if r:
        db.delete(r)
        db.commit()
        pipeline.rebuild_now("rule")
    return {"ok": True}


# ------------------------------------------------------------------ comerciantes
@router.get("/merchants")
def merchants(months: int = 12, db: Session = Depends(get_db)) -> list[dict]:
    return O.merchants_ranking(db, months)


class MerchantPatch(BaseModel):
    canonical_name: str | None = None
    default_category_id: str | None = None


def update_merchant(db: Session, merchant_id: int, body: MerchantPatch) -> None:
    m = db.get(Merchant, merchant_id)
    if not m:
        raise HTTPException(404)
    if body.canonical_name:
        m.canonical_name = body.canonical_name
    if body.default_category_id is not None:
        m.default_category_id = body.default_category_id or None
        m.category_origin = "user" if body.default_category_id else None


@router.patch("/merchants/{merchant_id}")
def patch_merchant(merchant_id: int, body: MerchantPatch, db: Session = Depends(get_db)) -> dict:
    update_merchant(db, merchant_id, body)
    db.commit()
    pipeline.rebuild_now("merchant")
    return {"ok": True}


# ------------------------------------------------------------------ categorias e orçamento
@router.get("/categories")
def categories(month: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    from app.utils.time import month_key, today_brt
    return O.category_tree(db, month or month_key(today_brt()))


@router.get("/categories/flat")
def categories_flat(db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": c.id, "parent_id": c.parent_id, "name": c.name, "nature": c.nature, "dre_line": c.dre_line,
             "essential": c.essential, "color": c.color, "default_event_type": c.default_event_type,
             "is_system": c.is_system, "active": c.active}
            for c in db.scalars(select(Category).order_by(Category.sort))]


@router.get("/categories/{category_id}/detail")
def category_detail(category_id: str, months: int = 12, db: Session = Depends(get_db)) -> dict:
    return O.category_detail(db, category_id, months)


class CategoryBody(BaseModel):
    id: str | None = None
    parent_id: str | None = None
    name: str | None = None
    essential: bool | None = None
    dre_line: str | None = None
    color: str | None = None
    active: bool | None = None


def _check_dre_line(line: str | None) -> None:
    """Linha fora da DRE faria os lançamentos da categoria sumirem do demonstrativo sem aviso."""
    from app.categorization.chart import DRE_LINES
    if line is not None and line not in {k for k, _, _ in DRE_LINES}:
        raise HTTPException(400, f"linha da DRE inválida: {line}")


@router.post("/categories")
def create_category(body: CategoryBody, db: Session = Depends(get_db)) -> dict:
    _check_dre_line(body.dre_line)
    parent = db.get(Category, body.parent_id) if body.parent_id else None
    if body.parent_id and not parent:
        raise HTTPException(400, "categoria-mãe inexistente")
    slug = body.id or f"{body.parent_id + '.' if body.parent_id else 'u.'}{re.sub(r'[^a-z0-9]+', '_', (body.name or 'nova').lower()).strip('_')}"
    if db.get(Category, slug):
        raise HTTPException(400, "já existe")
    db.add(Category(id=slug, parent_id=body.parent_id, name=body.name or slug,
                    nature=parent.nature if parent else "despesa",
                    dre_line=body.dre_line or (parent.dre_line if parent else "estilo_vida"),
                    essential=body.essential if body.essential is not None else (parent.essential if parent else False),
                    default_event_type=parent.default_event_type if parent else "EXPENSE",
                    color=body.color, sort=9999, is_system=False))
    return {"ok": True, "id": slug}


@router.patch("/categories/{category_id}")
def patch_category(category_id: str, body: CategoryBody, db: Session = Depends(get_db)) -> dict:
    c = db.get(Category, category_id)
    if not c:
        raise HTTPException(404)
    _check_dre_line(body.dre_line)
    for k in ("name", "essential", "dre_line", "color", "active", "parent_id"):
        v = getattr(body, k)
        if v is not None:
            setattr(c, k, v)
    return {"ok": True}


class BudgetBody(BaseModel):
    amount: float | None = None
    month: str | None = None


@router.put("/budgets/{category_id}")
def set_budget(category_id: str, body: BudgetBody, db: Session = Depends(get_db)) -> dict:
    b = db.scalar(select(Budget).where(Budget.category_id == category_id,
                                       Budget.month.is_(None) if body.month is None else Budget.month == body.month))
    if not body.amount:
        if b:
            db.delete(b)
        return {"ok": True}
    if b is None:
        b = Budget(category_id=category_id, month=body.month, amount=body.amount)
        db.add(b)
    b.amount = body.amount
    return {"ok": True}


# ------------------------------------------------------------------ revisões
@router.get("/reviews")
def reviews(status: str = "open", kind: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    q = select(ReviewItem).where(ReviewItem.status == status)
    if kind:
        q = q.where(ReviewItem.kind == kind)
    sev = {"high": 0, "warn": 1, "info": 2}
    items = db.scalars(q).all()
    items.sort(key=lambda r: (sev.get(r.severity, 3), -abs((r.data or {}).get("total") or (r.data or {}).get("amount") or 0)))
    return [{c.name: getattr(r, c.name) for c in ReviewItem.__table__.columns} for r in items]


class ReviewAction(BaseModel):
    action: str  # resolve | dismiss
    category_id: str | None = None
    event_type: str | None = None
    resolution: str | None = None  # exit_no_counterpart: not_connected_account | custody_transferred | provider_error | loss


@router.post("/reviews/{review_id}")
def act_review(review_id: int, body: ReviewAction, db: Session = Depends(get_db)) -> dict:
    apply_review(db, review_id, body)
    db.commit()
    if body.action == "resolve" and (body.category_id or body.event_type or body.resolution):
        pipeline.rebuild_now("review")
    return {"ok": True}


def apply_review(db: Session, review_id: int, body: ReviewAction, actor: str = "user") -> None:
    r = db.get(ReviewItem, review_id)
    if not r:
        raise HTTPException(404)
    if r.kind == "exit_no_counterpart" and body.action == "resolve":
        from app.portfolio.transit import RESOLUTIONS, set_resolution
        if body.resolution not in RESOLUTIONS:
            raise HTTPException(422, "informe a resolução: " + ", ".join(RESOLUTIONS))
        set_resolution(db, (r.data or {})["key"], body.resolution, by=actor)
    elif body.action == "resolve" and (body.category_id or body.event_type):
        if r.entity_type == "recurring" and (r.data or {}).get("merchant_id"):
            r_entity, r_id = "merchant", str(r.data["merchant_id"])
        else:
            r_entity, r_id = r.entity_type, r.entity_id
        if r_entity == "merchant":
            m = db.get(Merchant, int(r_id))
            if m and body.category_id:
                m.default_category_id, m.category_origin = body.category_id, "user"
            if body.event_type and m:  # tipo explícito → regra pelo documento ou, sem ele, pelo próprio comerciante
                # (o nome canônico pode vir da descrição e não casar com a contraparte dos lançamentos futuros)
                db.add(CategoryRule(name=f"Revisão: {m.canonical_name}",
                                    field="cnpj" if m.cnpj else "merchant_id", operator="equals",
                                    pattern=m.cnpj or str(m.id),
                                    category_id=body.category_id, event_type=body.event_type, origin="user"))
        elif r_entity == "transaction" and r.entity_id:
            _apply_override(db, r.entity_id, EventPatch(category_id=body.category_id, event_type=body.event_type),
                            actor=actor)
    r.status = "resolved" if body.action == "resolve" else "dismissed"
    r.resolved_at = utcnow()
    r.resolution = {**body.model_dump(), "by": actor}
