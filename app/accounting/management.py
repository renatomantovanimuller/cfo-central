"""DRE gerencial: o mês contra a média, o orçamento e o acumulado do ano, com indicadores de saúde financeira.
Resultado recorrente exclui itens extraordinários (herança, doações); eles aparecem abaixo, separados."""
from __future__ import annotations

import statistics
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounting.balance import current_position, future_installments
from app.accounting.statements import dre, month_list
from app.models import Budget, Category, InvestmentTransaction
from app.portfolio.classification import has_daily_liquidity
from app.utils.time import month_key, today_brt

EXPENSE_LINES = {"essenciais", "estilo_vida", "terceiros", "nao_classificado", "impostos_renda", "despesas_financeiras"}
LIQUID = {"D0", "D1"}


def reserva_liquida(s: Session, pos: dict) -> float:
    """Caixa + investimentos de liquidez D0/D1 (inclui Tesouro Selic) + RF com liquidez diaria comprovada
    (emissor Nu/RDB/caixinha ou historico de resgate parcial antes do vencimento)."""
    redeemed = {i for i in s.scalars(select(InvestmentTransaction.investment_id).where(
        InvestmentTransaction.type == "SELL").distinct())}
    total = pos["totals"]["cash"]
    for p in pos.get("positions", []):
        liq = p.get("liquidity")
        daily = liq in LIQUID or p.get("asset_class") == "Tesouro Selic" or (
            liq == "vencimento" and has_daily_liquidity({**p, "early_redemption": p.get("id") in redeemed}))
        if daily:
            total += p["balance"]
    return total


def _budgets(s: Session, month: str, cats: dict[str, Category]) -> dict[str, float]:
    """Orçamento mensal por categoria (o do mês vence o padrão), somado nas categorias-mãe."""
    base: dict[str, float] = {}
    for b in s.scalars(select(Budget)):
        if b.month in (None, month) and b.amount:
            if b.month == month or b.category_id not in base:
                base[b.category_id] = float(b.amount)
    out: dict[str, float] = defaultdict(float)
    for cid, v in base.items():
        out[cid] += v
        c = cats.get(cid)
        while c is not None and c.parent_id:
            out[c.parent_id] += v
            c = cats.get(c.parent_id)
    return out


def _mean(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    return statistics.mean(vals) if vals else None


def dre_gerencial(s: Session, month: str | None = None) -> dict:
    month = month or month_key(today_brt())
    months = month_list(month, 13)          # mês + 12 anteriores
    prev6, prev12 = months[-7:-1], months[:-1]
    ytd = [m for m in months if m[:4] == month[:4]]
    d = dre(s, months, with_valuation=False)
    cats = {c.id: c for c in s.scalars(select(Category))}
    budgets = _budgets(s, month, cats)
    rec_now = next(r for r in d["rows"] if r["key"] == "receita_liquida")["values"][month]
    rec_avg = _mean([next(r for r in d["rows"] if r["key"] == "receita_liquida")["values"][m] for m in prev6])

    def cols(values: dict, cid: str | None, sign: int) -> dict:
        cur = values.get(month, 0.0)
        avg6 = _mean([values.get(m, 0.0) for m in prev6])
        avg12 = _mean([values.get(m, 0.0) for m in prev12])
        delta = None if avg6 is None else cur - avg6
        # orçamento é teto de gasto (valor positivo); compara com o gasto do mês (sinal invertido)
        bud = budgets.get(cid) if cid else None
        spent = -cur if sign < 0 else cur
        return {
            "mes": round(cur, 2), "media6": None if avg6 is None else round(avg6, 2),
            "delta": None if delta is None else round(delta, 2),
            "delta_pct": (delta / abs(avg6)) if delta is not None and avg6 not in (None, 0) else None,
            "orcamento": round(bud, 2) if bud else None,
            "execucao": (spent / bud) if bud else None,
            "av": (cur / rec_now) if rec_now and rec_now > 0 else None,
            "ytd": round(sum(values.get(m, 0.0) for m in ytd), 2),
            "media12": None if avg12 is None else round(avg12, 2),
        }

    rows = []
    for r in d["rows"]:
        sign = -1 if r["key"] in EXPENSE_LINES else 1
        rows.append({"key": r["key"], "label": r["label"], "level": 0, "subtotal": r["subtotal"],
                     "final": r["key"] in ("resultado_liquido", "resultado_total"), **cols(r["values"], None, sign)})
        for c in r.get("children", []):
            rows.append({"key": f'{r["key"]}:{c["id"]}', "id": c["id"], "label": c["label"], "level": 1,
                         **cols(c["values"], c["id"], sign)})
            for leaf in c.get("children", []):
                rows.append({"key": f'{r["key"]}:{leaf["id"]}', "id": leaf["id"], "label": leaf["label"], "level": 2,
                             **cols(leaf["values"], leaf["id"], sign)})

    # indicadores
    vals = {r["key"]: r["values"] for r in d["rows"]}
    def series(key):
        return [vals[key].get(m, 0.0) for m in prev6]
    desp6 = [-sum(vals[k].get(m, 0.0) for k in EXPENSE_LINES) for m in prev6]
    burn = _mean(desp6)
    ess6 = _mean([-v for v in series("essenciais")])
    pos = current_position(s)
    liquid = reserva_liquida(s, pos)
    inst = future_installments(s)
    inst_next = inst["by_month"][0]["amount"] if inst["by_month"] else 0.0
    poup = [d["savings_rate"][m] for m in prev6 if d["savings_rate"][m] is not None]
    indicadores = {
        "taxa_poupanca_mes": d["savings_rate"][month],
        "taxa_poupanca_6m": _mean(poup),
        "receita_recorrente_6m": rec_avg,
        "gasto_medio_6m": burn,
        "essenciais_6m": ess6,
        "peso_essenciais": (ess6 / rec_avg) if ess6 and rec_avg else None,
        "reserva_liquida": round(liquid, 2),
        "meses_de_reserva": (liquid / burn) if burn else None,
        "meses_de_essenciais": (liquid / ess6) if ess6 else None,
        "parcelas_proximo_mes": inst_next,
        "comprometimento_parcelas": (inst_next / rec_avg) if rec_avg else None,
        "extraordinarios_ano": round(sum(vals["extraordinarios"].get(m, 0.0) for m in ytd), 2),
    }
    return {"month": month, "parcial": month == month_key(today_brt()), "media_de": prev6, "ytd_de": ytd, "rows": rows, "indicadores": indicadores,
            "notas": ["Média = 6 meses fechados anteriores; YTD = acumulado do ano até o mês.",
                      "Resultado recorrente exclui itens extraordinários (herança, doações); a taxa de poupança usa só o recorrente.",
                      "Reserva líquida = caixa + investimentos com liquidez D0/D1."]}
