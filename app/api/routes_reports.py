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
from app.models import (AccountSetting, Asset, FinancialGoal, ManualAsset, RecurringRule)
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
    ov = O.overview(db)
    pos = B.current_position(db)
    goals = []
    for g in db.scalars(select(FinancialGoal)):
        current = {"net_worth": pos["totals"]["net_worth"], "investments": pos["totals"]["investments"],
                   "asset_class": pos["investments_by_class"].get(g.asset_class or "", 0.0),
                   "manual": g.manual_current or 0.0}.get(g.basis, 0.0)
        months_left = None
        needed = None
        if g.target_date:
            months_left = max(1, (g.target_date.year - today_brt().year) * 12 + g.target_date.month - today_brt().month)
            r = (1 + g.expected_return_aa) ** (1 / 12) - 1
            fv_current = current * (1 + r) ** months_left
            gap = g.target_amount - fv_current
            needed = gap * r / ((1 + r) ** months_left - 1) if gap > 0 and r > 0 else max(0.0, gap / months_left)
        goals.append({"id": g.id, "name": g.name, "target_amount": g.target_amount, "target_date": g.target_date,
                      "basis": g.basis, "asset_class": g.asset_class, "current": current,
                      "progress": current / g.target_amount if g.target_amount else None,
                      "months_left": months_left, "monthly_needed": needed, "expected_return_aa": g.expected_return_aa})
    recurring = [{c.name: getattr(r, c.name) for c in RecurringRule.__table__.columns}
                 for r in db.scalars(select(RecurringRule).order_by(RecurringRule.expected_amount.desc()))]
    from app.analytics import plano as PL
    cfg = PL.plan(db)
    aporte = cfg["meta_aporte_mensal"]
    if aporte is None:
        aporte = max(0.0, ov["capacity"]["median_result_6m"] or 0.0)
    for g in goals:
        if g["months_left"]:
            mu, sigma, fonte = PL.portfolio_mu_sigma(db, g["expected_return_aa"])
            g["simulacao"] = {**PL.monte_carlo(g["current"], g["target_amount"], g["months_left"], aporte, mu, sigma),
                              "fonte_risco": fonte}
    sts = PL.safe_to_spend(db)
    return {"forecast": O.liquidity_forecast(db), "recurring": recurring, "goals": goals,
            "capacity": ov["capacity"], "kpis": ov["kpis"], "budget": O.budget_execution(db, ov["month"]),
            "plano": cfg, "aporte_simulacao": aporte, "safe_to_spend": sts,
            "politica": PL.policy_report(db, aporte=sts["meta_aporte"]),
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
    basis: str = "net_worth"
    asset_class: str | None = None
    manual_current: float | None = None
    expected_return_aa: float = 0.10


@router.post("/goals")
def create_goal(body: GoalBody, db: Session = Depends(get_db)) -> dict:
    g = FinancialGoal(**body.model_dump())
    db.add(g)
    db.flush()
    return {"ok": True, "id": g.id}


@router.delete("/goals/{goal_id}")
def delete_goal(goal_id: int, db: Session = Depends(get_db)) -> dict:
    g = db.get(FinancialGoal, goal_id)
    if g:
        db.delete(g)
    return {"ok": True}


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


@router.get("/manual-assets")
def manual_assets(db: Session = Depends(get_db)) -> list[dict]:
    return [{c.name: getattr(m, c.name) for c in ManualAsset.__table__.columns} for m in db.scalars(select(ManualAsset))]


@router.post("/manual-assets")
def create_manual(body: ManualBody, db: Session = Depends(get_db)) -> dict:
    if body.kind not in ("asset", "liability"):
        raise HTTPException(400, "kind deve ser asset ou liability")
    m = ManualAsset(**{**body.model_dump(), "as_of": body.as_of or today_brt()})
    db.add(m)
    db.flush()
    return {"ok": True, "id": m.id}


@router.put("/manual-assets/{mid}")
def update_manual(mid: int, body: ManualBody, db: Session = Depends(get_db)) -> dict:
    m = db.get(ManualAsset, mid)
    if not m:
        raise HTTPException(404)
    for k, v in body.model_dump().items():
        setattr(m, k, v if k != "as_of" else (v or today_brt()))
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
