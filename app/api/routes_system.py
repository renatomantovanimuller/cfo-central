"""Auth, conexões Pluggy, sincronização, webhooks, logs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import (COOKIE, CurrentUser, authenticate, has_users, issue_token, read_token,
                               set_password)
from app.config.settings import get_settings
from app.connectors.pluggy.client import PluggyError
from app.database.session import get_db
from app.models import (Account, AccountSetting, Institution, Item, SyncEvent, SyncRun, WebhookEvent)
from app.services.pipeline import pipeline

public = APIRouter(prefix="/api")
router = APIRouter(prefix="/api", dependencies=[CurrentUser])


class Credentials(BaseModel):
    username: str
    password: str


@public.get("/health")
def health() -> dict:
    return {"ok": True}


@public.get("/auth/status")
def auth_status(request: Request) -> dict:
    return {"setup_required": not has_users(), "user": read_token(request.cookies.get(COOKIE))}


def _login(response: Response, username: str) -> None:
    response.set_cookie(COOKIE, issue_token(username), httponly=True, samesite="strict",
                        max_age=get_settings().session_hours * 3600)


@public.post("/auth/setup")
def auth_setup(body: Credentials, response: Response) -> dict:
    if has_users():
        raise HTTPException(403, "usuário já configurado")
    try:
        set_password(body.username.strip(), body.password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    _login(response, body.username.strip())
    return {"ok": True}


@public.post("/auth/login")
def auth_login(body: Credentials, response: Response) -> dict:
    if not authenticate(body.username.strip(), body.password):
        raise HTTPException(401, "usuário ou senha inválidos")
    _login(response, body.username.strip())
    return {"ok": True}


@public.post("/auth/logout")
def auth_logout(response: Response) -> dict:
    response.delete_cookie(COOKIE)
    return {"ok": True}


@public.post("/webhooks/pluggy")
def webhook(payload: dict, db: Session = Depends(get_db)) -> dict:
    """Responde rápido. O payload só dispara releitura do item com a sua chave — nunca grava dados dele."""
    event, item_id = payload.get("event"), payload.get("itemId")
    db.add(WebhookEvent(event=event, event_id=payload.get("eventId"), item_id=item_id, payload=payload))
    known = item_id and db.get(Item, item_id) is not None
    if item_id and (known or event == "item/created"):
        if event == "item/deleted":
            it = db.get(Item, item_id)
            if it:
                it.is_active = False
        else:
            pipeline.debounced_sync(item_id)
    return {"received": True}


# ------------------------------------------------------------------ conexões
class ItemBody(BaseModel):
    itemId: str


class ItemPatch(BaseModel):
    nickname: str | None = None
    is_active: bool | None = None


@router.post("/connect-token")
def connect_token(body: dict | None = None) -> dict:
    s = get_settings()
    token = pipeline.client.connect_token(s.pluggy_client_user_id, item_id=(body or {}).get("itemId"),
                                          webhook_url=s.webhook_url)
    ids = list(s.connector_ids)
    if s.pluggy_include_sandbox and ids:
        ids.append(2)
    return {"accessToken": token, "connectorIds": ids, "includeSandbox": s.pluggy_include_sandbox}


def _account_key(a: dict) -> tuple:
    return (a.get("type"), (a.get("number") or "").strip() or a.get("name"), a.get("subtype"))


def duplicate_of(db: Session, item_id: str, accounts: list[dict]) -> list[str]:
    """Contas do novo item que já existem em outra conexão (ex.: escolher o Nubank de novo no MeuPluggy)."""
    known = {(a.type, (a.number or "").strip() or a.name, a.subtype): a.name
             for a in db.scalars(select(Account).where(Account.item_id != item_id, Account.removed_at.is_(None)))}
    return [known[k] for k in map(_account_key, accounts) if k in known]


@router.post("/items")
def add_item(body: ItemBody, db: Session = Depends(get_db)) -> dict:
    item_id = body.itemId.strip()
    pipeline.client.item(item_id)  # valida
    if not db.get(Item, item_id):
        dups = duplicate_of(db, item_id, pipeline.client.accounts(item_id))
        if dups:
            try:
                pipeline.client.delete_item(item_id)  # remove só o compartilhamento com este app
            except PluggyError:
                pass
            raise HTTPException(409, f"Essa conexão repete contas já conectadas ({', '.join(sorted(set(dups)))}). "
                                     "Na tela do MeuPluggy, escolha o outro banco.")
    return {"ok": True, "started": pipeline.sync_async(trigger="manual", item_ids=[item_id], full=True)}


@router.patch("/items/{item_id}")
def patch_item(item_id: str, body: ItemPatch, db: Session = Depends(get_db)) -> dict:
    it = db.get(Item, item_id)
    if not it:
        raise HTTPException(404)
    if body.nickname is not None:
        it.nickname = body.nickname or None
    if body.is_active is not None:
        it.is_active = body.is_active
    return {"ok": True}


@router.delete("/items/{item_id}")
def delete_item(item_id: str, remote: bool = False, db: Session = Depends(get_db)) -> dict:
    """Desativa a conexão (dados históricos permanecem). remote=1 também apaga na Pluggy."""
    it = db.get(Item, item_id)
    if not it:
        raise HTTPException(404)
    it.is_active = False
    if remote:
        pipeline.client.delete_item(item_id)
    return {"ok": True}


@router.get("/connections")
def connections(db: Session = Depends(get_db)) -> dict:
    insts = {i.id: i for i in db.scalars(select(Institution))}
    sets = {x.account_id: x for x in db.scalars(select(AccountSetting))}
    items = []
    for it in db.scalars(select(Item).order_by(Item.first_seen_at)):
        inst = insts.get(it.institution_id)
        accs = [{"id": a.id, "name": a.name, "nickname": sets[a.id].nickname if a.id in sets else None,
                 "purpose": sets[a.id].purpose if a.id in sets else None,
                 "include_in_net_worth": sets[a.id].include_in_net_worth if a.id in sets else True,
                 "type": a.type, "subtype": a.subtype, "number": a.number, "balance": a.balance,
                 "credit_limit": a.credit_limit, "available_credit": a.available_credit,
                 "last_tx_sync_at": a.last_tx_sync_at, "removed": a.removed_at is not None}
                for a in db.scalars(select(Account).where(Account.item_id == it.id))]
        items.append({"id": it.id, "nickname": it.nickname, "institution": inst.name if inst else None,
                      "image_url": inst.image_url if inst else None, "color": inst.primary_color if inst else None,
                      "is_sandbox": inst.is_sandbox if inst else False, "status": it.status,
                      "execution_status": it.execution_status, "consent_expires_at": it.consent_expires_at,
                      "next_auto_sync_at": it.next_auto_sync_at, "source_updated_at": it.source_updated_at,
                      "last_synced_at": it.last_synced_at, "last_sync_status": it.last_sync_status,
                      "products": it.products, "is_active": it.is_active, "accounts": accs})
    runs = [{"id": r.id, "kind": r.kind, "trigger": r.trigger, "item_id": r.item_id, "started_at": r.started_at,
             "finished_at": r.finished_at, "status": r.status, "stats": r.stats, "error": r.error}
            for r in db.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(40))]
    hooks = [{"id": w.id, "received_at": w.received_at, "event": w.event, "item_id": w.item_id}
             for w in db.scalars(select(WebhookEvent).order_by(WebhookEvent.id.desc()).limit(20))]
    s = get_settings()
    return {"items": items, "runs": runs, "webhooks": hooks, "sync": pipeline.state,
            "config": {"webhooks_enabled": bool(s.webhook_url), "sync_hours": s.pluggy_sync_hours,
                       "scheduler": s.scheduler_enabled}}


@router.get("/runs/{run_id}/events")
def run_events(run_id: int, db: Session = Depends(get_db)) -> list[dict]:
    return [{"at": e.at, "level": e.level, "step": e.step, "message": e.message, "data": e.data}
            for e in db.scalars(select(SyncEvent).where(SyncEvent.run_id == run_id).order_by(SyncEvent.id))]


class SyncBody(BaseModel):
    full: bool = False
    item_id: str | None = None


@router.post("/sync")
def sync(body: SyncBody) -> dict:
    return {"started": pipeline.sync_async(trigger="manual", item_ids=[body.item_id] if body.item_id else None,
                                           full=body.full)}


@router.get("/sync/status")
def sync_status(db: Session = Depends(get_db)) -> dict:
    last = db.scalar(select(SyncRun).where(SyncRun.kind == "pluggy", SyncRun.status.in_(["ok", "partial"]))
                     .order_by(SyncRun.id.desc()).limit(1))
    return {**pipeline.state, "last_ok_at": last.finished_at if last else None}


@router.post("/rebuild")
def rebuild() -> dict:
    res = pipeline.rebuild_now("manual")
    return {"ok": True, "counts": res.get("counts"), "reviews": res.get("reviews")}


@router.post("/market/sync")
def market_sync() -> dict:
    res = pipeline.market("manual")
    return {"ok": "error" not in res, "errors": res.get("errors"), "sgs": res.get("sgs")}


# ------------------------------------------------------------------ primeiros passos e integrações
UNCLASSIFIED_INCOME = ("rec.pix_terceiros", "rec.outras")


@router.get("/onboarding")
def onboarding(db: Session = Depends(get_db)) -> dict:
    """Estado da configuração inicial: o que falta para os números ficarem confiáveis."""
    from datetime import timedelta

    from sqlalchemy import func

    from app.config.integrations import public_view
    from app.models import AppSetting, Budget, FinancialEvent, RecurringRule
    from app.utils.time import today_brt

    since = today_brt() - timedelta(days=95)
    income = select(func.coalesce(func.sum(FinancialEvent.amount), 0.0)).where(
        FinancialEvent.is_removed.is_(False), FinancialEvent.event_type == "INCOME",
        FinancialEvent.competence_date >= since)
    total_in = db.scalar(income) or 0.0
    unclassified_in = db.scalar(income.where(FinancialEvent.category_id.in_(UNCLASSIFIED_INCOME))) or 0.0
    plano = db.get(AppSetting, "plano")
    integ = public_view(db)
    return {
        "pluggy_configured": integ["pluggy"]["configured"],
        "email_configured": integ["email"]["configured"],
        "items": db.scalar(select(func.count()).select_from(Item).where(Item.is_active.is_(True))) or 0,
        "events": db.scalar(select(func.count()).select_from(FinancialEvent).where(FinancialEvent.is_removed.is_(False))) or 0,
        "budgets": db.scalar(select(func.count()).select_from(Budget)) or 0,
        "plan_set": bool(plano and plano.value and plano.value.get("meta_aporte_mensal") is not None),
        "recurring_confirmed": db.scalar(select(func.count()).select_from(RecurringRule)
                                         .where(RecurringRule.status == "confirmed")) or 0,
        # receita dos últimos 3 meses que ainda está "a classificar": enquanto for relevante, os resultados são provisórios
        "income_unclassified": round(unclassified_in, 2),
        "income_unclassified_share": round(unclassified_in / total_in, 3) if total_in > 0 else 0.0,
        "sync": pipeline.state,
    }


class IntegrationsBody(BaseModel):
    pluggy_client_id: str | None = None
    pluggy_client_secret: str | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    alert_email_to: str | None = None


@router.get("/integrations")
def integrations(db: Session = Depends(get_db)) -> dict:
    from app.config.integrations import public_view
    return public_view(db)


@router.put("/integrations")
def save_integrations(body: IntegrationsBody, db: Session = Depends(get_db)) -> dict:
    from app.config.integrations import public_view, save
    save(db, body.model_dump())
    return public_view(db)


@router.post("/integrations/pluggy/test")
def test_pluggy() -> dict:
    """Valida a chave da Pluggy pedindo uma API key (não lê dados de nenhum banco)."""
    try:
        pipeline.client.api_key(force=True)
        return {"ok": True}
    except PluggyError as e:
        msg = "Client ID ou Secret inválidos." if e.status in (400, 401, 403) else str(e)
        return {"ok": False, "erro": msg}
    except Exception as e:  # noqa: BLE001 — rede/DNS: a tela mostra o motivo em vez de um erro 500
        return {"ok": False, "erro": f"sem conexão com a Pluggy ({e.__class__.__name__})"}
