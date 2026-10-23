"""Painel, demonstrativos, cartões, carteira, planejamento, configurações e exportação."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounting import balance as B
from app.accounting import statements as S
from app.analytics import overview as O
from app.analytics.export import export_csv, export_xlsx
from app.auth.security import CurrentUser
from app.database.session import get_db
from app.models import (AccountSetting, Asset, Bucket, BucketAllocation, FinancialGoal, ManualAsset,
                        RecurringRule)
from app.portfolio import service as P
from app.utils.time import month_key, today_brt

router = APIRouter(prefix="/api", dependencies=[CurrentUser])


def _end(end: str | None) -> str:
    return end or month_key(today_brt())


@router.get("/overview")
def overview(month: str | None = None, db: Session = Depends(get_db)) -> dict:
    return O.overview(db, month)


@router.get("/dre")
def dre(end: str | None = None, months: int = 12, db: Session = Depends(get_db)) -> dict:
    return S.dre(db, S.month_list(_end(end), max(1, min(months, 36))))


@router.get("/dre/gerencial")
def dre_gerencial(month: str | None = None, db: Session = Depends(get_db)) -> dict:
    from app.accounting.management import dre_gerencial as G
    return G(db, month)


@router.get("/dfc")
def dfc(end: str | None = None, months: int = 12, db: Session = Depends(get_db)) -> dict:
    return S.dfc(db, S.month_list(_end(end), max(1, min(months, 36))))


@router.get("/sankey")
def sankey(month: str | None = None, db: Session = Depends(get_db)) -> dict:
    return S.sankey(db, _end(month))


@router.get("/balance")
def balance(db: Session = Depends(get_db)) -> dict:
    p = B.current_position(db)
    p.pop("positions", None)
    return p


@router.get("/patrimony")
def patrimony(db: Session = Depends(get_db)) -> dict:
    from app.analytics.patrimonio import consolidated
    return P._clean(consolidated(db))


@router.get("/patrimony/bridge")
def patrimony_bridge(months: int = 12, db: Session = Depends(get_db)) -> dict:
    from app.analytics.patrimonio import bridge
    return P._clean(bridge(db, max(2, min(months, 24))))


@router.get("/patrimony/evolution")
def patrimony_evolution(months: int = 12, db: Session = Depends(get_db)) -> dict:
    from app.analytics.patrimonio import evolution
    return P._clean(evolution(db, max(2, min(months, 36))))


@router.get("/patrimony/projection")
def patrimony_projection(years: int = 10, alvo: float | None = None, inflacao: float = 0.04,
                         db: Session = Depends(get_db)) -> dict:
    from app.analytics.patrimonio import projection
    return P._clean(projection(db, max(1, min(years, 40)), alvo, max(0.0, min(inflacao, 0.2))))


@router.get("/balance/history")
def balance_history(months: int = 12, db: Session = Depends(get_db)) -> list[dict]:
    return B.history(db, max(1, min(months, 36)))


@router.get("/cards")
def cards(db: Session = Depends(get_db)) -> dict:
    return O.cards_view(db)


@router.get("/portfolio")
def portfolio(db: Session = Depends(get_db)) -> dict:
    pos = P.positions(db)
    return P._clean({"positions": pos, "allocation": P.allocation(pos), "fgc": P.fgc_exposure(pos),
                     "ladder": P.maturity_ladder(pos), "performance": P.performance(db),
                     "movements": P.investment_movements(db)})


@router.get("/portfolio/realized")
def portfolio_realized(db: Session = Depends(get_db)) -> dict:
    from app.portfolio.realized import equity_lots, fixed_income_titles
    return {"renda_fixa": fixed_income_titles(db), "renda_variavel": equity_lots(db)}


@router.get("/alerts/status")
def alerts_status(db: Session = Depends(get_db)) -> dict:
    from app.alerts.notify import status
    return status(db)


@router.post("/alerts/test")
def alerts_test(db: Session = Depends(get_db)) -> dict:
    from app.alerts.notify import send_test
    return send_test(db)


@router.get("/portfolio/risk")
def portfolio_risk(years: int = 2, db: Session = Depends(get_db)) -> dict:
    return P.risk_report(db, max(1, min(years, 3)))


class AssetPatch(BaseModel):
    asset_class: str | None = None
    indexer: str | None = None
    liquidity: str | None = None
    yahoo_symbol: str | None = None
    risk_proxy: str | None = None
    fgc_covered: bool | None = None


@router.get("/assets")
def assets(db: Session = Depends(get_db)) -> list[dict]:
    return [{c.name: getattr(a, c.name) for c in Asset.__table__.columns} for a in db.scalars(select(Asset))]


@router.patch("/assets/{asset_id}")
def patch_asset(asset_id: int, body: AssetPatch, db: Session = Depends(get_db)) -> dict:
    a = db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    a.origin = "user"
    return {"ok": True}


# ------------------------------------------------------------------ planejamento
@router.get("/planning")
def planning(db: Session = Depends(get_db)) -> dict:
    from app.analytics import metas as MT
    from app.analytics import plano as PL
    ov = O.overview(db)
    pos = B.current_position(db)
    cfg = PL.plan(db)
    sts = PL.safe_to_spend(db)
    aporte = sts["meta_aporte"]
    politica = PL.policy_report(db, aporte=aporte)
    goals = MT.goals_status(db, pos)
    total_inv = sum(c["valor"] for c in politica["classes"])
    plano_aportes = MT.contribution_plan(aporte, politica["reserva"], goals, politica["classes"], total_inv)
    politica["aporte"] = {"valor": aporte, "destinos": plano_aportes["destinos"]}
    for g in plano_aportes["metas"]:
        if g["months_left"] and g["target_amount"]:
            mensal = g["aporte_alocado"] if g["aporte_alocado"] is not None else 0.0
            mu, sigma, fonte = PL.portfolio_mu_sigma(db, g["expected_return_aa"])
            g["simulacao"] = {**PL.monte_carlo(g["current"], g["target_amount"], g["months_left"], mensal, mu, sigma),
                              "fonte_risco": fonte, "aporte_mensal": mensal}
    recurring = [{c.name: getattr(r, c.name) for c in RecurringRule.__table__.columns}
                 for r in db.scalars(select(RecurringRule).order_by(RecurringRule.expected_amount.desc()))]
    gasto_anual = (ov["kpis"]["avg6"].get("despesas") or 0.0) * 12
    return {"forecast": O.liquidity_forecast(db), "recurring": recurring, "goals": plano_aportes["metas"],
            "capacity": ov["capacity"], "kpis": ov["kpis"], "budget": O.budget_execution(db, ov["month"]),
            "plano": cfg, "aporte_simulacao": aporte, "safe_to_spend": sts, "politica": politica,
            "plano_aportes": {k: v for k, v in plano_aportes.items() if k != "metas"},
            "aportes_realizados": MT.contributions_history(db, cfg["meta_aporte_mensal"] or aporte),
            "sugestao_independencia": {"gasto_anual": round(gasto_anual, 2), "taxa_retirada": MT.SAFE_WITHDRAWAL,
                                       "valor": round(gasto_anual / MT.SAFE_WITHDRAWAL, 2) if gasto_anual else None},
            "aumentos": PL.salary_raises(db)}


@router.get("/financial-health")
def financial_health(db: Session = Depends(get_db)) -> dict:
    from app.analytics.saude_financeira import financial_health as FH
    return FH(db)


class PlanSettingsBody(BaseModel):
    meta_aporte_mensal: float | None = None
    reserva_meses_minima: float | None = None
    limite_fgc: float | None = None
    retorno_esperado_aa: float | None = None
    aumento_para_aporte: float | None = Field(default=None, ge=0, le=1)
    score_credito: float | None = Field(default=None, ge=0, le=1000)


@router.put("/plan/settings")
def put_plan_settings(body: PlanSettingsBody, db: Session = Depends(get_db)) -> dict:
    from app.analytics import plano as PL
    return PL.put_setting(db, "plano", body.model_dump(exclude_unset=True))


class TargetItem(BaseModel):
    asset_class: str
    target_pct: float
    min_pct: float | None = None
    max_pct: float | None = None


@router.put("/plan/targets")
def put_targets(body: list[TargetItem], db: Session = Depends(get_db)) -> dict:
    from app.analytics import plano as PL
    if sum(t.target_pct for t in body) > 1.0001:
        raise HTTPException(400, "a soma dos alvos passa de 100%")
    PL.set_targets(db, [t.model_dump() for t in body])
    db.commit()
    return PL.policy_report(db)


class GoalBody(BaseModel):
    name: str
    target_amount: float
    target_date: date | None = None
    basis: str = "bucket"  # bucket (recomendado) | investments | net_worth | asset_class | manual
    asset_class: str | None = None
    manual_current: float | None = None
    expected_return_aa: float = 0.10
    kind: str = "prazo"
    priority: int = 100


class GoalPatch(BaseModel):
    name: str | None = None
    target_amount: float | None = None
    target_date: date | None = None
    basis: str | None = None
    expected_return_aa: float | None = None
    kind: str | None = None
    priority: int | None = None


def _goal_bucket(db: Session, g: FinancialGoal):
    """Bolso da meta (criado na primeira vez). Meta de aposentadoria vira bolso de aposentadoria."""
    b = db.scalar(select(Bucket).where(Bucket.goal_id == g.id))
    if b is None:
        b = Bucket(name=g.name, goal_id=g.id, kind="aposentadoria" if g.kind == "aposentadoria" else "objetivo")
        db.add(b)
        db.flush()
    return b


@router.post("/goals")
def create_goal(body: GoalBody, db: Session = Depends(get_db)) -> dict:
    if body.kind not in ("prazo", "aposentadoria", "livre"):
        raise HTTPException(400, "tipo de meta inválido")
    g = FinancialGoal(**body.model_dump())
    db.add(g)
    db.flush()
    bucket_id = _goal_bucket(db, g).id if g.basis == "bucket" else None
    return {"ok": True, "id": g.id, "bucket_id": bucket_id}


@router.patch("/goals/{goal_id}")
def patch_goal(goal_id: int, body: GoalPatch, db: Session = Depends(get_db)) -> dict:
    g = db.get(FinancialGoal, goal_id)
    if not g:
        raise HTTPException(404)
    data = body.model_dump(exclude_unset=True)
    if "kind" in data and data["kind"] not in ("prazo", "aposentadoria", "livre"):
        raise HTTPException(400, "tipo de meta inválido")
    for k, v in data.items():
        setattr(g, k, v)
    if g.basis == "bucket":
        b = _goal_bucket(db, g)
        b.name = g.name
        b.kind = "aposentadoria" if g.kind == "aposentadoria" else "objetivo"
    return {"ok": True}


@router.delete("/goals/{goal_id}")
def delete_goal(goal_id: int, db: Session = Depends(get_db)) -> dict:
    g = db.get(FinancialGoal, goal_id)
    if g:
        for b in db.scalars(select(Bucket).where(Bucket.goal_id == goal_id)):
            for a in db.scalars(select(BucketAllocation).where(BucketAllocation.bucket_id == b.id)):
                db.delete(a)
            db.delete(b)
        db.delete(g)
    return {"ok": True}


# ------------------------------------------------------------------ bolsos
@router.get("/buckets")
def buckets(db: Session = Depends(get_db)) -> dict:
    from app.analytics.bolsos import buckets_report, ensure_reserve_bucket
    ensure_reserve_bucket(db)
    db.commit()
    return P._clean(buckets_report(db))


class BucketBody(BaseModel):
    name: str
    kind: str = "objetivo"


@router.post("/buckets")
def create_bucket(body: BucketBody, db: Session = Depends(get_db)) -> dict:
    if body.kind not in ("objetivo", "aposentadoria"):
        raise HTTPException(400, "tipo de bolso inválido (a reserva já existe)")
    b = Bucket(name=body.name.strip()[:120] or "Bolso", kind=body.kind)
    db.add(b)
    db.flush()
    return {"ok": True, "id": b.id}


@router.patch("/buckets/{bucket_id}")
def rename_bucket(bucket_id: int, body: BucketBody, db: Session = Depends(get_db)) -> dict:
    b = db.get(Bucket, bucket_id)
    if not b:
        raise HTTPException(404)
    b.name = body.name.strip()[:120] or b.name
    return {"ok": True}


@router.delete("/buckets/{bucket_id}")
def delete_bucket(bucket_id: int, db: Session = Depends(get_db)) -> dict:
    b = db.get(Bucket, bucket_id)
    if not b:
        return {"ok": True}
    if b.kind == "reserva" or b.goal_id:
        raise HTTPException(400, "a reserva não pode ser excluída; bolso de meta sai junto com a meta")
    for a in db.scalars(select(BucketAllocation).where(BucketAllocation.bucket_id == b.id)):
        db.delete(a)
    db.delete(b)
    return {"ok": True}


class AllocationItem(BaseModel):
    source_type: str
    source_id: str
    pct: float = Field(ge=0, le=1)


@router.put("/buckets/{bucket_id}/allocations")
def put_allocations(bucket_id: int, body: list[AllocationItem], db: Session = Depends(get_db)) -> dict:
    from app.analytics.bolsos import buckets_report, set_allocations
    if not db.get(Bucket, bucket_id):
        raise HTTPException(404)
    try:
        set_allocations(db, bucket_id, [x.model_dump() for x in body])
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    db.commit()
    return P._clean(buckets_report(db))


@router.post("/buckets/suggest-reserve")
def suggest_reserve(db: Session = Depends(get_db)) -> dict:
    from app.analytics.bolsos import buckets_report
    from app.analytics.bolsos import suggest_reserve as SR
    res = SR(db)
    db.commit()
    return {**res, "bolsos": P._clean(buckets_report(db))}


@router.patch("/recurring/{rec_id}")
def patch_recurring(rec_id: int, body: dict, db: Session = Depends(get_db)) -> dict:
    r = db.get(RecurringRule, rec_id)
    if not r:
        raise HTTPException(404)
    if body.get("status") in ("detected", "confirmed", "ignored"):
        r.status = body["status"]
    return {"ok": True}


# ------------------------------------------------------------------ configurações
class AccountSettingBody(BaseModel):
    nickname: str | None = None
    purpose: str | None = None
    include_in_net_worth: bool | None = None


@router.patch("/accounts/{account_id}")
def patch_account(account_id: str, body: AccountSettingBody, db: Session = Depends(get_db)) -> dict:
    st = db.get(AccountSetting, account_id) or AccountSetting(account_id=account_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(st, k, v)
    db.add(st)
    return {"ok": True}


class ManualBody(BaseModel):
    kind: str
    name: str
    asset_class: str | None = None
    value: float
    as_of: date | None = None
    notes: str | None = None
    active: bool = True
    acquired_at: date | None = None
    growth_aa: float | None = Field(default=None, ge=-0.5, le=0.5)


@router.get("/manual-assets")
def manual_assets(db: Session = Depends(get_db)) -> list[dict]:
    from app.accounting.manual import points_by_asset, value_at
    pts = points_by_asset(db)
    today = today_brt()
    return [{**{c.name: getattr(m, c.name) for c in ManualAsset.__table__.columns},
             "valor_atual": round(value_at(m, pts.get(m.id), today), 2),
             "historico": [{"data": d, "valor": v} for d, v in pts.get(m.id, [])]}
            for m in db.scalars(select(ManualAsset))]


@router.post("/manual-assets")
def create_manual(body: ManualBody, db: Session = Depends(get_db)) -> dict:
    if body.kind not in ("asset", "liability"):
        raise HTTPException(400, "kind deve ser asset ou liability")
    from app.accounting.manual import record_point
    m = ManualAsset(**{**body.model_dump(), "as_of": body.as_of or today_brt()})
    db.add(m)
    db.flush()
    record_point(db, m)
    return {"ok": True, "id": m.id}


@router.put("/manual-assets/{mid}")
def update_manual(mid: int, body: ManualBody, db: Session = Depends(get_db)) -> dict:
    m = db.get(ManualAsset, mid)
    if not m:
        raise HTTPException(404)
    from app.accounting.manual import record_point
    for k, v in body.model_dump().items():
        setattr(m, k, v if k != "as_of" else (v or today_brt()))
    db.flush()
    record_point(db, m)  # nova atualização vira ponto do histórico; os anteriores ficam
    return {"ok": True}


@router.delete("/manual-assets/{mid}")
def delete_manual(mid: int, db: Session = Depends(get_db)) -> dict:
    m = db.get(ManualAsset, mid)
    if m:
        db.delete(m)
    return {"ok": True}


@router.get("/export.xlsx")
def export_excel() -> Response:
    name = f"cfo-central-{today_brt():%Y-%m-%d}.xlsx"
    return Response(export_xlsx(), headers={"Content-Disposition": f"attachment; filename={name}"},
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/export.csv")
def export_ledger_csv() -> Response:
    name = f"cfo-central-razao-{today_brt():%Y-%m-%d}.csv"
    return Response(export_csv(), headers={"Content-Disposition": f"attachment; filename={name}"},
                    media_type="text/csv; charset=utf-8")


# ------------------------------------------------------------------ saúde dos dados, classificador, IR
@router.get("/data-health")
def data_health(db: Session = Depends(get_db)) -> dict:
    from app.health.checks import latest
    from app.analytics.plano import get_setting
    return {"ultima": latest(db), "classificador": get_setting(db, "classificador")}


@router.post("/data-health/run")
def data_health_run(db: Session = Depends(get_db)) -> dict:
    """Roda as verificações agora (sem reconstruir o razão)."""
    from app.health.checks import latest, run_checks, save_run
    save_run(db, run_checks(db), "manual")
    db.commit()
    return {"ultima": latest(db)}


@router.get("/ir")
def ir(ano: int | None = None, db: Session = Depends(get_db)) -> dict:
    from app.tax.irpf import irpf_report
    return irpf_report(db, ano)


@router.get("/ir.xlsx")
def ir_excel(ano: int | None = None, db: Session = Depends(get_db)) -> Response:
    from app.tax.irpf import irpf_xlsx
    data = irpf_xlsx(db, ano)
    name = f"cfo-central-ir-{ano or 'atual'}.xlsx"
    return Response(data, headers={"Content-Disposition": f"attachment; filename={name}"},
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
