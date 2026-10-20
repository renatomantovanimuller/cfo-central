"""Planejamento: preferências do plano, 'quanto posso gastar este mês', política de investimentos (alocação-alvo
com bandas) e simulação de metas por Monte Carlo. Nada aqui recomenda produto: só mede contra regras do usuário."""
from __future__ import annotations

import calendar
import statistics
from datetime import date

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounting.statements import dre, month_list
from app.alerts.reviews import ReviewCandidate, fmt_brl
from app.models import AllocationTarget, AppSetting, FinancialEvent, RecurringRule
from app.utils.time import month_add, month_bounds, month_key, today_brt

PLAN_DEFAULTS = {
    "meta_aporte_mensal": None,      # R$/mês que você quer investir; None = usa 20% da receita recorrente
    "reserva_meses_minima": 6,       # meses de custo essencial que devem estar em liquidez D0/D1
    "limite_fgc": 250000.0,
    "retorno_esperado_aa": None,     # None = usa o histórico ex-ante da carteira
}
EXPENSE_LIKE = ("EXPENSE", "FINANCIAL_EXPENSE", "TAX", "REFUND")


def get_setting(s: Session, key: str, defaults: dict | None = None) -> dict:
    row = s.get(AppSetting, key)
    return {**(defaults or {}), **((row.value or {}) if row else {})}


def put_setting(s: Session, key: str, value: dict) -> dict:
    row = s.get(AppSetting, key) or AppSetting(key=key, value={})
    merged = {**(row.value or {}), **value}
    row.value = merged
    s.add(row)
    s.flush()
    return merged


def plan(s: Session) -> dict:
    return get_setting(s, "plano", PLAN_DEFAULTS)


# ------------------------------------------------------------------ quanto posso gastar
def safe_to_spend(s: Session, today: date | None = None) -> dict:
    today = today or today_brt()
    month = month_key(today)
    a, b = month_bounds(month)
    hist = month_list(month_add(month, -1), 3)
    d = dre(s, hist + [month], with_valuation=False)
    rows = {r["key"]: r["values"] for r in d["rows"]}
    # bônus/PLR entra no resultado, mas não é renda de todo mês: fica fora da base de previsão
    bonus = {m: 0.0 for m in hist + [month]}
    for amt, dt in s.execute(select(FinancialEvent.amount, FinancialEvent.competence_date).where(
            FinancialEvent.is_removed.is_(False), FinancialEvent.category_id == "rec.bonus",
            FinancialEvent.competence_date.between(month_bounds(hist[0])[0], b))):
        key = month_key(dt)
        if key in bonus:
            bonus[key] += amt
    rec_hist = [rows["receita_liquida"][m] - bonus[m] for m in hist if rows["receita_liquida"][m] - bonus[m] > 0]
    renda_base = statistics.median(rec_hist) if rec_hist else 0.0
    recebido = rows["receita_liquida"][month] - bonus[month]
    renda = max(renda_base, recebido)
    p = plan(s)
    if p["meta_aporte_mensal"] is not None:
        aporte, origem = p["meta_aporte_mensal"], "plano"
    else:
        # sem meta definida: 20% da renda, mas nunca mais do que de fato sobrou nos meses anteriores
        # (sugerir aporte de 20% a quem fecha o mês no vermelho só empurra o "quanto posso gastar" para baixo de zero)
        sobra = [rows["resultado_liquido"][m] for m in hist]
        teto = max(0.0, statistics.median(sobra)) if sobra else 0.0
        aporte = round(min(0.2 * renda, teto), 2)
        origem = "padrao" if aporte >= round(0.2 * renda, 2) else "padrao_limitado"

    gasto = -(s.scalar(select(func.coalesce(func.sum(FinancialEvent.amount), 0.0)).where(
        FinancialEvent.is_removed.is_(False), FinancialEvent.competence_date.between(a, b),
        FinancialEvent.event_type.in_(EXPENSE_LIKE))) or 0.0)
    pendentes = []
    for r in s.scalars(select(RecurringRule).where(RecurringRule.direction == "out", RecurringRule.status != "ignored")):
        if r.next_date and today <= r.next_date <= b and (r.last_date is None or r.last_date < a):
            pendentes.append({"descricao": r.description, "valor": r.expected_amount, "data": r.next_date})
    comprometido = sum(x["valor"] for x in pendentes)
    disponivel = renda - aporte - gasto - comprometido
    dias_rest = (b - today).days + 1
    dias_mes = calendar.monthrange(today.year, today.month)[1]
    ritmo = gasto / today.day * dias_mes if today.day else gasto
    return {
        "mes": month, "renda_prevista": round(renda, 2), "renda_recebida": round(recebido, 2),
        "meta_aporte": round(aporte, 2), "meta_aporte_origem": origem, "gasto_ate_hoje": round(gasto, 2),
        "recorrencias_pendentes": pendentes, "comprometido": round(comprometido, 2),
        "disponivel": round(disponivel, 2), "por_dia": round(disponivel / dias_rest, 2) if dias_rest > 0 else None,
        "dias_restantes": dias_rest, "projecao_gasto_mes": round(ritmo + comprometido, 2),
        "premissas": [
            "Renda prevista = maior entre a mediana da receita recorrente dos 3 meses anteriores e o já recebido no mês (sem bônus/PLR).",
            "Meta de aporte = configurada no plano; sem meta, 20% da renda prevista limitado à sobra mediana dos 3 meses anteriores.",
            "Gasto até hoje = despesas do mês por competência (cartão na data da compra), já descontados reembolsos.",
            "Recorrências pendentes = gastos recorrentes detectados com próxima data ainda neste mês.",
            "Extraordinários (herança, doações) não entram na renda.",
        ],
    }


# ------------------------------------------------------------------ política de investimentos
def policy_report(s: Session) -> dict:
    from app.accounting.balance import current_position
    from app.accounting.management import LIQUID
    from app.portfolio.service import allocation, fgc_exposure

    p = plan(s)
    pos = current_position(s)
    positions = pos.get("positions", [])
    alloc = allocation(positions) if positions else {"total": 0, "by_class": []}
    current = {x["label"]: x["pct"] for x in alloc["by_class"]}
    targets = {t.asset_class: t for t in s.scalars(select(AllocationTarget))}
    total = alloc["total"] or 0.0
    linhas = []
    for cls in sorted(set(current) | set(targets)):
        t = targets.get(cls)
        cur = current.get(cls, 0.0)
        tgt = t.target_pct if t else None
        lo = (t.min_pct if t and t.min_pct is not None else (tgt - 0.05 if tgt is not None else None))
        hi = (t.max_pct if t and t.max_pct is not None else (tgt + 0.05 if tgt is not None else None))
        status = "sem alvo" if tgt is None else ("abaixo" if cur < lo - 1e-9 else "acima" if cur > hi + 1e-9 else "ok")
        linhas.append({"classe": cls, "atual": cur, "valor": round(cur * total, 2), "alvo": tgt, "min": lo, "max": hi,
                       "status": status,
                       "ajuste_para_alvo": round((tgt - cur) * total, 2) if tgt is not None else None})
    soma_alvos = sum(t.target_pct for t in targets.values())

    # reserva de emergência em meses de custo essencial
    hist = month_list(month_add(month_key(today_brt()), -1), 6)
    d = dre(s, hist, with_valuation=False)
    ess = [-v for v in next(r for r in d["rows"] if r["key"] == "essenciais")["values"].values()]
    ess_med = statistics.mean(ess) if ess else 0.0
    liquido = pos["totals"]["cash"] + sum(x["balance"] for x in positions if x.get("liquidity") in LIQUID)
    meses = liquido / ess_med if ess_med > 0 else None
    fgc = fgc_exposure(positions) if positions else []
    acima_fgc = [f for f in fgc if f["value"] > p["limite_fgc"]]
    return {
        "classes": linhas, "soma_alvos": soma_alvos, "alvos_definidos": bool(targets),
        "reserva": {"liquido_d0_d1": round(liquido, 2), "custo_essencial_mensal": round(ess_med, 2),
                    "meses": meses, "minimo_meses": p["reserva_meses_minima"],
                    "ok": meses is None or meses >= p["reserva_meses_minima"]},
        "fgc": {"limite": p["limite_fgc"], "acima_do_limite": acima_fgc},
        "nota": "Alvos e limites são definidos por você; o app só mede o desvio. Banda padrão: alvo ± 5 p.p.",
    }


def set_targets(s: Session, targets: list[dict]) -> None:
    keep = set()
    for t in targets:
        cls = t["asset_class"]
        keep.add(cls)
        row = s.scalar(select(AllocationTarget).where(AllocationTarget.asset_class == cls)) or AllocationTarget(asset_class=cls)
        row.target_pct = float(t["target_pct"])
        row.min_pct = t.get("min_pct")
        row.max_pct = t.get("max_pct")
        s.add(row)
    for row in s.scalars(select(AllocationTarget)):
        if row.asset_class not in keep:
            s.delete(row)
    s.flush()


def policy_reviews(s: Session) -> list[ReviewCandidate]:
    out: list[ReviewCandidate] = []
    try:
        rep = policy_report(s)
    except Exception:  # noqa: BLE001 - sem dados de mercado/posições
        return out
    for c in rep["classes"]:
        if c["status"] in ("abaixo", "acima"):
            out.append(ReviewCandidate(
                f"policy:{c['classe']}:{c['status']}", "policy_drift", "warn", "asset_class", c["classe"],
                f"{c['classe']} {c['status']} da banda: {c['atual']:.1%} (alvo {c['alvo']:.0%})",
                f"Para voltar ao alvo: {fmt_brl(c['ajuste_para_alvo'])}. Banda {c['min']:.0%}–{c['max']:.0%}."))
    r = rep["reserva"]
    if not r["ok"]:
        out.append(ReviewCandidate(
            "policy:reserva", "policy_reserve", "warn", "plan", "reserva",
            f"Reserva de emergência abaixo do mínimo: {r['meses']:.1f} meses (mínimo {r['minimo_meses']})",
            f"Liquidez D0/D1 {fmt_brl(r['liquido_d0_d1'])} para custo essencial de {fmt_brl(r['custo_essencial_mensal'])}/mês."))
    return out  # excesso de FGC já é sinalizado por portfolio_reviews


# ------------------------------------------------------------------ Monte Carlo de metas
def monte_carlo(current: float, target: float, months: int, monthly: float, mu_aa: float, sigma_aa: float,
                n: int = 4000, seed: int = 7) -> dict:
    """Retornos mensais log-normais (média e vol anuais), aporte no fim de cada mês."""
    months = max(1, int(months))
    rng = np.random.default_rng(seed)
    mu_m = np.log1p(mu_aa) / 12
    sig_m = sigma_aa / np.sqrt(12)
    r = np.exp(rng.normal(mu_m - sig_m ** 2 / 2, sig_m, size=(n, months))) - 1
    v = np.empty((n, months))
    cur = np.full(n, float(current))
    for t in range(months):
        cur = cur * (1 + r[:, t]) + monthly
        v[:, t] = cur
    final = v[:, -1]
    pct = np.percentile(v, [10, 50, 90], axis=0)
    step = max(1, months // 60)
    return {
        "probabilidade": float((final >= target).mean()),
        "final_p10": float(np.percentile(final, 10)), "final_p50": float(np.percentile(final, 50)),
        "final_p90": float(np.percentile(final, 90)),
        "trajetoria": [{"mes": t + 1, "p10": float(pct[0, t]), "p50": float(pct[1, t]), "p90": float(pct[2, t])}
                       for t in range(0, months, step)] + ([] if (months - 1) % step == 0 else
                       [{"mes": months, "p10": float(pct[0, -1]), "p50": float(pct[1, -1]), "p90": float(pct[2, -1])}]),
        "premissas": {"retorno_aa": mu_aa, "vol_aa": sigma_aa, "aporte_mensal": monthly, "simulacoes": n},
    }


def portfolio_mu_sigma(s: Session, fallback_mu: float) -> tuple[float, float, str]:
    from app.portfolio.service import risk_report
    try:
        rr = risk_report(s, 2)
        st = rr.get("stats") or {}
        if rr.get("available") and st.get("vol_ann"):
            mu = plan(s)["retorno_esperado_aa"]
            return (float(mu) if mu is not None else min(max(float(st.get("return_ann") or fallback_mu), 0.0), 0.25),
                    float(st["vol_ann"]), "carteira atual (2 anos, ex-ante)")
    except Exception:  # noqa: BLE001
        pass
    return fallback_mu, 0.08, "premissa padrão (vol 8% a.a.)"
