"""Consultas do painel, categorias, comerciantes, orçamento, cartões e previsão de liquidez."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounting.balance import current_position, future_installments
from app.accounting.statements import SPENDING_LINES, dre, month_list
from app.models import (Account, Budget, Category, CreditCardBill, DailyNetWorth, EventType, FinancialEvent,
                        Merchant, RecurringRule, ReviewItem)
from app.utils.time import month_add, month_bounds, month_key, today_brt

EXPENSE_LIKE = {"EXPENSE", "FINANCIAL_EXPENSE", "TAX", "REFUND"}


def _root_map(s: Session) -> tuple[dict, dict]:
    cats = {c.id: c for c in s.scalars(select(Category))}
    roots = {}
    for cid, c in cats.items():
        r = c
        while r.parent_id and r.parent_id in cats:
            r = cats[r.parent_id]
        roots[cid] = r.id
    return cats, roots


def month_budgets(s: Session, month: str) -> dict[str, float]:
    """Orçamento definido por categoria para o mês: o do mês vence o padrão (sem mês)."""
    out: dict[str, float] = {}
    for b in s.scalars(select(Budget)):
        if b.month in (None, month) and b.amount and (b.month == month or b.category_id not in out):
            out[b.category_id] = float(b.amount)
    return out


def rollup_budgets(own: dict[str, float], cats: dict) -> dict[str, float]:
    """Orçamento efetivo de cada categoria: o próprio, se definido; senão a soma das filhas. Assim mãe e filhas
    orçadas ao mesmo tempo não contam em dobro (o teto da mãe já cobre as filhas)."""
    children: dict[str, list[str]] = defaultdict(list)
    for cid, c in cats.items():
        if c.parent_id:
            children[c.parent_id].append(cid)

    def eff(cid: str) -> float:
        if cid in own:
            return own[cid]
        return sum(eff(k) for k in children.get(cid, []))
    return {cid: v for cid in cats if (v := eff(cid))}


def kpis_from_dre(d: dict) -> dict:
    rows = {r["key"]: r for r in d["rows"]}
    out = {}
    for m in d["months"]:
        rec = rows["receita_liquida"]["values"][m]
        res = rows["resultado_liquido"]["values"][m]
        expenses = sum(rows[k]["values"][m] for k in SPENDING_LINES)
        out[m] = {"receita_liquida": rec, "despesas": -expenses, "essenciais": -rows["essenciais"]["values"][m],
                  "estilo_vida": -rows["estilo_vida"]["values"][m], "resultado": res,
                  "extraordinarios": rows["extraordinarios"]["values"][m],
                  "a_classificar_entradas": rows["entradas_a_classificar"]["values"][m],
                  "resultado_total": rows["resultado_total"]["values"][m],
                  "taxa_poupanca": d["savings_rate"][m]}
    return out


def overview(s: Session, month: str | None = None) -> dict:
    month = month or month_key(today_brt())
    months = month_list(month, 13)
    d = dre(s, months, with_valuation=False)
    k = kpis_from_dre(d)
    cur, prev = k[month], k[months[-2]]
    hist = [k[m] for m in months[-7:-1]]

    def avg(key):
        vals = [h[key] for h in hist if h[key] is not None]
        return statistics.mean(vals) if vals else None

    cats, roots = _root_map(s)
    a, b = month_bounds(month)
    ev = s.execute(select(FinancialEvent.category_id, FinancialEvent.amount, FinancialEvent.event_type,
                          FinancialEvent.competence_date, FinancialEvent.merchant_id)
                   .where(FinancialEvent.is_removed.is_(False), FinancialEvent.competence_date.between(a, b),
                          FinancialEvent.event_type.in_(EXPENSE_LIKE))).all()
    by_root: dict[str, float] = defaultdict(float)
    by_merchant: dict[int, float] = defaultdict(float)
    for cid, amt, et, dt, mid in ev:
        by_root[roots.get(cid, "nc")] -= amt
        if mid:
            by_merchant[mid] -= amt
    names = {m.id: m.canonical_name for m in s.scalars(select(Merchant).where(Merchant.id.in_(list(by_merchant) or [-1])))}
    inv = s.execute(select(func.sum(FinancialEvent.amount)).where(
        FinancialEvent.is_removed.is_(False), FinancialEvent.competence_date.between(a, b),
        FinancialEvent.event_type.in_(["INVESTMENT_CONTRIBUTION", "INVESTMENT_REDEMPTION"]))).scalar() or 0.0
    pos = current_position(s)
    nw = [{"date": r.date.isoformat(), "net_worth": r.net_worth}
          for r in s.scalars(select(DailyNetWorth).order_by(DailyNetWorth.date))]
    reviews = dict(s.execute(select(ReviewItem.severity, func.count()).where(ReviewItem.status == "open")
                             .group_by(ReviewItem.severity)).all())
    results6 = [k[m]["resultado"] for m in months[-7:-1] if k[m]["receita_liquida"] or k[m]["despesas"]]
    inst = pos["installments"]
    next3 = sum(x["amount"] for x in inst["by_month"][:3])
    return {
        "month": month,
        "kpis": {"current": cur, "previous": prev,
                 "avg6": {key: avg(key) for key in ("receita_liquida", "despesas", "resultado", "taxa_poupanca")},
                 "invested_net": -inv},
        "series": [{"month": m, **k[m]} for m in months],
        "top_categories": [{"id": r, "name": cats[r].name if r in cats else r, "color": cats[r].color if r in cats else None,
                            "value": round(v, 2)} for r, v in sorted(by_root.items(), key=lambda kv: -kv[1]) if v > 0][:10],
        "top_merchants": [{"id": mid, "name": names.get(mid, str(mid)), "value": round(v, 2)}
                          for mid, v in sorted(by_merchant.items(), key=lambda kv: -kv[1])[:10]],
        "position": {"totals": pos["totals"], "investments_by_class": pos["investments_by_class"],
                     "assumptions": pos["assumptions"]},
        "net_worth_series": nw,
        "capacity": {"avg_result_6m": statistics.mean(results6) if results6 else None,
                     "median_result_6m": statistics.median(results6) if results6 else None,
                     "card_commitments_3m": next3},
        "reviews_open": reviews,
        "safe_to_spend": _safe(s) if month == month_key(today_brt()) else None,
        "daily": daily_spend(s, month),
    }


def _safe(s: Session) -> dict | None:
    from app.analytics.plano import safe_to_spend
    try:
        return safe_to_spend(s)
    except Exception:  # noqa: BLE001
        return None


def daily_spend(s: Session, month: str) -> dict:
    out = {}
    for label, m in (("current", month), ("previous", month_add(month, -1))):
        a, b = month_bounds(m)
        rows = s.execute(select(FinancialEvent.competence_date, func.sum(FinancialEvent.amount))
                         .where(FinancialEvent.is_removed.is_(False), FinancialEvent.competence_date.between(a, b),
                                FinancialEvent.event_type.in_(EXPENSE_LIKE))
                         .group_by(FinancialEvent.competence_date)).all()
        by_day = {d.day: -v for d, v in rows}
        acc, cum = 0.0, []
        for day in range(1, 32):
            acc += by_day.get(day, 0.0)
            cum.append(round(acc, 2))
        out[label] = cum
    cats = {c.id: c for c in s.scalars(select(Category))}
    eff = rollup_budgets(month_budgets(s, month), cats)
    out["budget"] = sum(v for cid, v in eff.items() if not cats[cid].parent_id and cats[cid].nature != "receita")
    return out


# ------------------------------------------------------------------ categorias e orçamento
def category_tree(s: Session, month: str) -> list[dict]:
    cats, roots = _root_map(s)
    months = month_list(month, 6)
    start, _ = month_bounds(months[0])
    _, end = month_bounds(month)
    rows = s.execute(select(FinancialEvent.category_id, FinancialEvent.competence_date, FinancialEvent.amount)
                     .where(FinancialEvent.is_removed.is_(False), FinancialEvent.competence_date.between(start, end),
                            FinancialEvent.event_type.in_(EventType.PNL))).all()
    agg: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for cid, d, amt in rows:
        m = f"{d.year:04d}-{d.month:02d}"
        agg[cid][m] += amt
        if roots.get(cid) and roots[cid] != cid:
            agg[roots[cid]][m] += amt
    budgets = month_budgets(s, month)
    out = []
    for c in sorted(cats.values(), key=lambda c: c.sort):
        if c.nature == "patrimonial" or not c.active:
            continue
        vals = agg.get(c.id, {})
        series = [round(vals.get(m, 0.0), 2) for m in months]
        prev = series[:-1]
        nonzero = [v for v in prev if v]
        out.append({"id": c.id, "parent_id": c.parent_id, "name": c.name, "nature": c.nature, "dre_line": c.dre_line,
                    "essential": c.essential, "color": c.color, "current": series[-1], "series": series,
                    "months": months, "avg3": round(statistics.mean(prev[-3:]), 2) if prev else 0.0,
                    "median6": round(statistics.median(nonzero), 2) if nonzero else 0.0,
                    "budget": budgets.get(c.id), "is_system": c.is_system})
    return out


def category_detail(s: Session, category_id: str, months: int = 12) -> dict:
    cats, roots = _root_map(s)
    ids = [cid for cid, r in roots.items() if cid == category_id or r == category_id or cats[cid].parent_id == category_id]
    end = month_key(today_brt())
    ml = month_list(end, months)
    start, _ = month_bounds(ml[0])
    rows = s.execute(select(FinancialEvent.competence_date, FinancialEvent.amount, FinancialEvent.merchant_id,
                            FinancialEvent.category_id)
                     .where(FinancialEvent.is_removed.is_(False), FinancialEvent.category_id.in_(ids),
                            FinancialEvent.event_type.in_(EventType.PNL),  # mesmo recorte da DRE
                            FinancialEvent.competence_date >= start)).all()
    by_month: dict[str, float] = defaultdict(float)
    by_merchant: dict[int, list[float]] = defaultdict(list)
    by_sub: dict[str, float] = defaultdict(float)
    for d, amt, mid, cid in rows:
        by_month[f"{d.year:04d}-{d.month:02d}"] += amt
        by_sub[cid] += amt
        if mid:
            by_merchant[mid].append(amt)
    names = {m.id: m.canonical_name for m in s.scalars(select(Merchant).where(Merchant.id.in_(list(by_merchant) or [-1])))}
    return {
        "category": {"id": category_id, "name": cats[category_id].name if category_id in cats else category_id},
        "series": [{"month": m, "value": round(by_month.get(m, 0.0), 2)} for m in ml],
        "subcategories": [{"id": k, "name": cats[k].name if k in cats else k, "value": round(v, 2)}
                          for k, v in sorted(by_sub.items(), key=lambda kv: kv[1])],
        "merchants": [{"id": mid, "name": names.get(mid, str(mid)), "total": round(sum(v), 2), "count": len(v),
                       "avg_ticket": round(sum(v) / len(v), 2)}
                      for mid, v in sorted(by_merchant.items(), key=lambda kv: sum(kv[1]))[:30]],
    }


def merchants_ranking(s: Session, months: int = 12) -> list[dict]:
    cats, _ = _root_map(s)
    start = month_bounds(month_list(n=months)[0])[0]
    rows = s.execute(select(FinancialEvent.merchant_id, func.count(), func.sum(FinancialEvent.amount),
                            func.min(FinancialEvent.competence_date), func.max(FinancialEvent.competence_date))
                     .where(FinancialEvent.is_removed.is_(False), FinancialEvent.merchant_id.is_not(None),
                            FinancialEvent.competence_date >= start, FinancialEvent.event_type.in_(EventType.PNL))
                     .group_by(FinancialEvent.merchant_id)).all()
    ms = {m.id: m for m in s.scalars(select(Merchant))}
    # categoria mais frequente de cada comerciante (não a de maior id em ordem alfabética)
    top_cat: dict[int, str] = {}
    best: dict[int, int] = {}
    for mid, cid, n in s.execute(select(FinancialEvent.merchant_id, FinancialEvent.category_id, func.count())
                                 .where(FinancialEvent.merchant_id.is_not(None), FinancialEvent.is_removed.is_(False),
                                        FinancialEvent.event_type.in_(EventType.PNL))
                                 .group_by(FinancialEvent.merchant_id, FinancialEvent.category_id)):
        if n > best.get(mid, 0):
            top_cat[mid], best[mid] = cid, n
    out = []
    for mid, n, total, first, last in rows:
        m = ms.get(mid)
        if not m:
            continue
        cid = m.default_category_id or top_cat.get(mid)
        out.append({"id": mid, "name": m.canonical_name, "doc": m.cnpj, "count": n, "total": round(total, 2),
                    "avg_ticket": round(total / n, 2), "first": first, "last": last,
                    "category_id": cid, "category": cats[cid].name if cid in cats else None,
                    "category_origin": m.category_origin})
    return sorted(out, key=lambda x: x["total"])


# ------------------------------------------------------------------ cartões e previsão
def cards_view(s: Session) -> dict:
    pos = current_position(s)
    bills = s.scalars(select(CreditCardBill).order_by(CreditCardBill.due_date.desc())).all()
    by_acc = defaultdict(list)
    for b in bills:
        by_acc[b.account_id].append({"id": b.id, "due_date": b.due_date, "close_date": b.close_date,
                                     "total": b.total_amount, "minimum": b.minimum_payment,
                                     "charges": b.finance_charges})
    cards = []
    for c in pos["cards"]:
        c = dict(c)
        c["bills"] = by_acc.get(c["account_id"], [])[:18]
        cards.append(c)
    # gasto no cartão por mês (competência) para tendência
    start = month_bounds(month_list(n=12)[0])[0]
    rows = s.execute(select(FinancialEvent.competence_date, FinancialEvent.amount)
                     .join(Account, Account.id == FinancialEvent.account_id)
                     .where(Account.type == "CREDIT", FinancialEvent.is_removed.is_(False),
                            FinancialEvent.event_type.in_(EXPENSE_LIKE), FinancialEvent.competence_date >= start)).all()
    spend = defaultdict(float)
    for d, amt in rows:
        spend[f"{d.year:04d}-{d.month:02d}"] -= amt
    return {"cards": cards, "installments": pos["installments"],
            "monthly_spend": [{"month": m, "value": round(spend.get(m, 0.0), 2)} for m in month_list(n=12)]}


FORECAST_MONTHS = 6
EXTRAORDINARY_CATEGORIES = {"rec.heranca", "rec.bonus"}
SALARY_CATEGORY = "rec.salario"


def _monthly_totals(df: pd.DataFrame, mask, months: list[str]) -> list[float]:
    """Soma por mês (incluindo meses zerados) dentro da janela `months`."""
    if df.empty:
        return [0.0] * len(months)
    sums = df[mask].groupby("m")["amount"].sum()
    return [float(sums.get(m, 0.0)) for m in months]


def _median(values: list[float]) -> float:
    return float(statistics.median(values)) if values else 0.0


def liquidity_forecast(s: Session, horizon: int = 6) -> dict:
    """Projeção de caixa (contas correntes) mês a mês. Premissas explícitas.

    Receita projetada = só recorrente (sem herança/doação/bônus/transferências/resgates):
    último salário confirmado + mediana de outras receitas recorrentes. Despesas = mediana
    dos meses completos (o mês corrente parcial fica fora da janela)."""
    today = today_brt()
    cur_m = month_key(today)
    hist = month_list(month_add(cur_m, -1), FORECAST_MONTHS)
    start, _ = month_bounds(hist[0])
    rows = s.execute(select(FinancialEvent.competence_date, FinancialEvent.amount, FinancialEvent.event_type,
                            Account.type, FinancialEvent.installment_key, FinancialEvent.category_id,
                            Category.dre_line)
                     .join(Account, Account.id == FinancialEvent.account_id)
                     .outerjoin(Category, Category.id == FinancialEvent.category_id)
                     .where(FinancialEvent.is_removed.is_(False),
                            FinancialEvent.competence_date.between(start, today))).all()
    df = pd.DataFrame(rows, columns=["d", "amount", "et", "acc", "inst", "cat", "line"])
    if not df.empty:
        df["m"] = df["d"].map(lambda d: f"{d.year:04d}-{d.month:02d}")
        # meses anteriores ao primeiro dado não contam (histórico curto)
        first_m = df["m"].min()
        hist = [m for m in hist if m >= first_m] or hist
    n = len(hist)

    income_mask = ((df["acc"] == "BANK") & df["et"].isin(["INCOME", "INVESTMENT_INCOME"]) & (df["amount"] > 0)
                   & ~df["cat"].isin(EXTRAORDINARY_CATEGORIES)
                   & ~df["line"].isin(["extraordinarios", "entradas_a_classificar"])) if not df.empty else None
    salary_months = _monthly_totals(df, income_mask & (df["cat"] == SALARY_CATEGORY), hist) if not df.empty else []
    other_months = _monthly_totals(df, income_mask & (df["cat"] != SALARY_CATEGORY), hist) if not df.empty else []
    last_salary = next((v for v in reversed(salary_months) if v > 0), 0.0)
    income_basis = "salario_ultimo_valor" if last_salary > 0 else "mediana_receita_recorrente"
    if last_salary > 0:
        income = last_salary + _median(other_months)
    else:
        income = _median(_monthly_totals(df, income_mask, hist)) if not df.empty else 0.0
    bank_mask = ((df["acc"] == "BANK") & df["et"].isin(["EXPENSE", "FINANCIAL_EXPENSE", "TAX", "REFUND"])) \
        if not df.empty else None
    bank_exp = -_median(_monthly_totals(df, bank_mask, hist)) if not df.empty else 0.0
    # mês corrente: o que já entrou/saiu está no saldo de hoje; projeta só o que falta do esperado
    received_now = _monthly_totals(df, income_mask, [cur_m])[0] if not df.empty else 0.0
    spent_now = -_monthly_totals(df, bank_mask, [cur_m])[0] if not df.empty else 0.0
    card_new = -_median(_monthly_totals(
        df, (df["acc"] == "CREDIT") & df["et"].isin(list(EXPENSE_LIKE)) & df["inst"].isna(), hist)) if not df.empty else 0.0
    pos = current_position(s)
    cash = pos["totals"]["cash"]
    inst = {x["month"]: x["amount"] for x in pos["installments"]["by_month"]}
    current_bill = pos["totals"]["card_current"]
    recurring_out = s.scalar(select(func.sum(RecurringRule.expected_amount)).where(
        RecurringRule.direction == "out", RecurringRule.status != "ignored")) or 0.0
    out = []
    bal = cash
    for k in range(horizon):
        m = month_add(cur_m, k)
        card_bill = current_bill if k == 0 else inst.get(m, 0.0) + card_new
        if k == 0:  # mês corrente: só o que falta (esperado − já realizado)
            inflow, outflow = max(0.0, income - received_now), max(0.0, bank_exp - spent_now) + card_bill
        else:
            inflow, outflow = income, bank_exp + card_bill
        bal = bal + inflow - outflow
        out.append({"month": m, "income": round(inflow, 2), "bank_expenses": round(outflow - card_bill, 2),
                    "card_bill": round(card_bill, 2), "end_cash": round(bal, 2)})
    return {"start_cash": cash, "months": out, "min_cash": min(x["end_cash"] for x in out) if out else cash,
            "assumptions_basis": {"income_basis": income_basis, "expense_basis": "mediana_meses_completos",
                                  "months": n, "window": hist, "income_monthly": round(income, 2),
                                  "bank_expenses_monthly": round(bank_exp, 2), "card_new_monthly": round(card_new, 2)},
            "assumptions": [
                f"Receitas: só recorrentes ({income_basis}; sem herança/bônus/transferências), {income:,.0f}/mês.",
                f"Despesas em conta: mediana de {n} meses completos ({bank_exp:,.0f}/mês).",
                f"Cartão: fatura atual no 1º mês; depois parcelas já contratadas + gasto médio à vista ({card_new:,.0f}/mês).",
                f"Recorrências de saída detectadas somam {recurring_out:,.0f}/mês (já embutidas nas médias).",
                "Mês corrente: projeta só o que falta (esperado − já recebido/gasto no mês, que está no saldo).",
                "Não considera aportes/resgates de investimento.",
            ]}


def budget_execution(s: Session, month: str) -> list[dict]:
    tree = category_tree(s, month)
    return [{"id": c["id"], "name": c["name"], "budget": c["budget"], "actual": -c["current"],
             "usage": (-c["current"] / c["budget"]) if c["budget"] else None, "avg3": -c["avg3"]}
            for c in tree if c["budget"]]
