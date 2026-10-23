"""Demonstrativos: DRE (competência) e DFC (caixa, método direto), mensais, com drill-down por categoria."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

import pandas as pd
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.accounting.effective import STALE, SUPERSEDED
from app.categorization.chart import DRE_LINES
from app.models import Account, AccountBalance, Category, EventType, FinancialEvent
from app.utils.time import month_add, month_bounds, month_key, today_brt

_EVENT_FALLBACK_LINE = {
    "INCOME": "outras_receitas", "INVESTMENT_INCOME": "receitas_financeiras", "EXPENSE": "nao_classificado",
    "FINANCIAL_EXPENSE": "despesas_financeiras", "TAX": "impostos_renda", "REFUND": "nao_classificado",
}
SUBTOTALS = [
    ("receita_liquida", "Receita líquida", ["receita_operacional", "outras_receitas", "impostos_renda"]),
    ("margem_essenciais", "Margem após essenciais", ["receita_liquida", "essenciais"]),
    ("resultado_operacional", "Resultado operacional", ["margem_essenciais", "estilo_vida", "terceiros", "nao_classificado"]),
    ("resultado_liquido", "Resultado recorrente (poupança)", ["resultado_operacional", "receitas_financeiras", "despesas_financeiras"]),
    ("resultado_total", "Resultado total", ["resultado_liquido", "extraordinarios", "entradas_a_classificar"]),
]
# "Despesas" em todas as telas = linhas abaixo da receita líquida (impostos sobre a renda já saem da receita),
# de modo que receita líquida − despesas + receitas financeiras = resultado recorrente
SPENDING_LINES = ["essenciais", "estilo_vida", "terceiros", "nao_classificado", "despesas_financeiras"]
DRE_ORDER = ["receita_operacional", "outras_receitas", "impostos_renda", "receita_liquida", "essenciais",
             "margem_essenciais", "estilo_vida", "terceiros", "nao_classificado", "resultado_operacional",
             "receitas_financeiras", "despesas_financeiras", "resultado_liquido", "extraordinarios", "entradas_a_classificar",
             "resultado_total"]


def month_list(end: str | None = None, n: int = 12) -> list[str]:
    end = end or month_key(today_brt())
    return [month_add(end, -k) for k in range(n - 1, -1, -1)]


def _events_frame(s: Session, start: date, end: date, types: set[str] | None = None,
                  bank_only: bool = False, date_col: str = "competence_date") -> pd.DataFrame:
    col = getattr(FinancialEvent, date_col)
    q = (select(FinancialEvent.source_id, FinancialEvent.amount, FinancialEvent.event_type,
                FinancialEvent.category_id, col.label("d"), Account.type.label("acc_type"))
         .join(Account, Account.id == FinancialEvent.account_id)
         .where(FinancialEvent.is_removed.is_(False), col >= start, col <= end,
                # pendente duplicado (já efetivado com outro id) ou velho sem efetivação nunca foi dinheiro
                or_(FinancialEvent.rule_id.is_(None), FinancialEvent.rule_id.not_in([SUPERSEDED, STALE]))))
    if types:
        q = q.where(FinancialEvent.event_type.in_(types))
    if bank_only:
        q = q.where(Account.type == "BANK")
    rows = s.execute(q).all()
    df = pd.DataFrame(rows, columns=["source_id", "amount", "event_type", "category_id", "d", "acc_type"])
    if not df.empty:
        df["month"] = df["d"].map(lambda x: f"{x.year:04d}-{x.month:02d}")
    return df


def dre(s: Session, months: list[str], with_valuation: bool = True) -> dict:
    start, _ = month_bounds(months[0])
    _, end = month_bounds(months[-1])
    cats = {c.id: c for c in s.scalars(select(Category))}
    df = _events_frame(s, start, end, EventType.PNL)

    def line_of(row) -> str:
        c = cats.get(row["category_id"])
        return (c.dre_line if c and c.dre_line else None) or _EVENT_FALLBACK_LINE.get(row["event_type"], "nao_classificado")

    def root_of(cid: str | None) -> str:
        c = cats.get(cid or "")
        while c and c.parent_id:
            c = cats.get(c.parent_id)
        return c.id if c else "nc"

    values: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    tree: dict[str, dict[str, dict[str, dict[str, float]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(float))))
    if not df.empty:
        df["line"] = df.apply(line_of, axis=1)
        df["root"] = df["category_id"].map(root_of)
        for (line, root, cat, m), v in df.groupby(["line", "root", "category_id", "month"])["amount"].sum().items():
            values[line][m] += v
            tree[line][root][cat][m] += v
    for key, _, parts in SUBTOTALS:
        for m in months:
            values[key][m] = sum(values[p][m] for p in parts)

    labels = {k: lbl for k, lbl, _ in DRE_LINES} | {k: lbl for k, lbl, _ in SUBTOTALS}
    rows = []
    for key in DRE_ORDER:
        is_sub = key in {k for k, _, _ in SUBTOTALS}
        children = []
        for root, subcats in sorted(tree.get(key, {}).items(), key=lambda kv: sum(sum(v.values()) for v in kv[1].values())):
            leafs = [{"id": cid, "label": cats[cid].name if cid in cats else cid,
                      "values": {m: round(vals.get(m, 0.0), 2) for m in months},
                      "total": round(sum(vals.get(m, 0.0) for m in months), 2)}
                     for cid, vals in sorted(subcats.items(), key=lambda kv: sum(kv[1].values()))]
            rv = {m: round(sum(l["values"][m] for l in leafs), 2) for m in months}
            children.append({"id": root, "label": cats[root].name if root in cats else root, "values": rv,
                             "total": round(sum(rv.values()), 2), "children": leafs if len(leafs) > 1 or leafs[0]["id"] != root else []})
        vals = {m: round(values[key].get(m, 0.0), 2) for m in months}
        rows.append({"key": key, "label": labels.get(key, key), "subtotal": is_sub, "values": vals,
                     "total": round(sum(vals.values()), 2), "children": children})

    rec_liq = {m: values["receita_liquida"][m] for m in months}
    savings = {m: (values["resultado_liquido"][m] / rec_liq[m]) if rec_liq[m] > 0 else None for m in months}
    out = {"months": months, "rows": rows, "savings_rate": savings, "valuation": None}
    for r in rows:  # análise vertical sobre receita líquida
        r["av"] = {m: (r["values"][m] / rec_liq[m]) if rec_liq[m] > 0 else None for m in months}
    if with_valuation:
        out["valuation"] = portfolio_valuation(s, months)
        econ = {}
        for m in months:
            v = out["valuation"]["values"].get(m)
            econ[m] = round(values["resultado_total"][m] + v, 2) if v is not None else None
        out["economic_result"] = econ
    return out


def portfolio_valuation(s: Session, months: list[str]) -> dict:
    """Valorização da carteira por mês = V_fim − V_início − aportes líquidos. Usa snapshots; sem eles, reconstrução (inferida)."""
    from app.models import InvestmentBalance
    from app.portfolio.service import reconstruct_history

    snaps = s.execute(select(InvestmentBalance.date, InvestmentBalance.balance)).all()
    snap = pd.DataFrame(snaps, columns=["date", "balance"]).groupby("date")["balance"].sum() if snaps else pd.Series(dtype=float)
    recon = reconstruct_history(s, days=31 * len(months) + 40)
    start, _ = month_bounds(months[0])
    _, end = month_bounds(months[-1])
    flows = _events_frame(s, month_bounds(month_add(months[0], -1))[0], end,
                          {"INVESTMENT_CONTRIBUTION", "INVESTMENT_REDEMPTION"})

    def value_at(d: date) -> tuple[float | None, bool]:
        if d in snap.index:
            return float(snap[d]), False
        if len(recon) and d in recon.index:
            return float(recon[d]), True
        return None, True

    vals, inferred = {}, {}
    for m in months:
        a, b = month_bounds(m)
        prev_end = month_bounds(month_add(m, -1))[1]
        b = min(b, today_brt())
        if a > today_brt():
            vals[m] = None
            continue
        v0, i0 = value_at(prev_end)
        v1, i1 = value_at(b)
        if v0 is None or v1 is None:
            vals[m] = None
            continue
        net = -float(flows[flows["month"] == m]["amount"].sum()) if not flows.empty else 0.0
        vals[m] = round(v1 - v0 - net, 2)
        inferred[m] = i0 or i1
    return {"values": vals, "inferred": inferred,
            "note": "Valorização = valor final − inicial − aportes líquidos. Meses sem snapshot usam reconstrução por proxy (estimada)."}


DFC_LINES = [
    ("operacional", "Atividades operacionais", [
        ("recebimentos", "Recebimentos (receitas e reembolsos)", {"INCOME", "INVESTMENT_INCOME", "REFUND"}),
        ("pagamentos_conta", "Despesas pagas em conta", {"EXPENSE", "FINANCIAL_EXPENSE", "TAX"}),
        ("faturas", "Pagamento de faturas de cartão", {"CARD_PAYMENT"}),
    ]),
    ("investimento", "Atividades de investimento", [
        ("aportes", "Aportes", {"INVESTMENT_CONTRIBUTION"}),
        ("resgates", "Resgates", {"INVESTMENT_REDEMPTION"}),
    ]),
    ("financiamento", "Atividades de financiamento", [
        ("emprestimos", "Empréstimos (entradas − parcelas)", {"LOAN_IN", "LOAN_PAYMENT"}),
        ("contas_externas", "Contas próprias não conectadas", {"EXTERNAL_OWN_TRANSFER"}),
    ]),
    ("outros", "Outros", [
        ("internas", "Transferências internas (deve zerar)", {"INTERNAL_TRANSFER"}),
        ("ignorados", "Ignorados", {"IGNORE"}),
    ]),
]


def dfc(s: Session, months: list[str]) -> dict:
    start, _ = month_bounds(months[0])
    _, end = month_bounds(months[-1])
    df = _events_frame(s, start, end, bank_only=True, date_col="cash_date")
    # recebimentos e despesas separados por sentido
    sections = []
    total = {m: 0.0 for m in months}
    for skey, slabel, lines in DFC_LINES:
        out_lines = []
        stot = {m: 0.0 for m in months}
        for lkey, llabel, types in lines:
            sub = df[df["event_type"].isin(types)] if not df.empty else df
            vals = {m: round(float(sub[sub["month"] == m]["amount"].sum()) if not sub.empty else 0.0, 2) for m in months}
            for m in months:
                stot[m] += vals[m]
            out_lines.append({"key": lkey, "label": llabel, "values": vals, "total": round(sum(vals.values()), 2)})
        for m in months:
            total[m] += stot[m]
        sections.append({"key": skey, "label": slabel, "lines": out_lines,
                         "values": {m: round(v, 2) for m, v in stot.items()}, "total": round(sum(stot.values()), 2)})

    # saldo de caixa (contas BANK): atual − fluxos posteriores = reconstrução; conferência contra snapshots reais
    cash_now = sum(a.balance or 0 for a in s.scalars(select(Account).where(Account.type == "BANK", Account.removed_at.is_(None))))
    all_after = _events_frame(s, start, date(2100, 1, 1), bank_only=True, date_col="cash_date")
    opening, closing, check = {}, {}, {}
    snaps = s.execute(select(AccountBalance.date, AccountBalance.balance).join(Account, Account.id == AccountBalance.account_id)
                      .where(Account.type == "BANK", AccountBalance.is_inferred.is_(False))).all()
    snap = pd.DataFrame(snaps, columns=["date", "balance"]).groupby("date")["balance"].sum() if snaps else pd.Series(dtype=float)
    for m in months:
        a, b = month_bounds(m)
        after_b = float(all_after[all_after["d"] > b]["amount"].sum()) if not all_after.empty else 0.0
        closing[m] = round(cash_now - after_b, 2)
        opening[m] = round(closing[m] - total[m], 2)
        check[m] = round(float(snap[b]) - closing[m], 2) if b in snap.index else None
    return {"months": months, "sections": sections, "net_change": {m: round(v, 2) for m, v in total.items()},
            "opening_cash": opening, "closing_cash": closing, "check_vs_reported": check,
            "notes": ["Somente contas correntes (caixa). Compras no cartão entram no caixa quando a fatura é paga.",
                      "Saldo inicial/final reconstruído a partir do saldo atual; 'conferência' compara com saldos "
                      "efetivamente coletados (snapshot) quando existem."]}


def sankey(s: Session, month: str) -> dict:
    """Fluxo do mês por competência: fontes de receita → orçamento → destinos (categorias, investimento, sobra)."""
    a, b = month_bounds(month)
    cats = {c.id: c for c in s.scalars(select(Category))}
    df = _events_frame(s, a, b, EventType.PNL | {"INVESTMENT_CONTRIBUTION", "INVESTMENT_REDEMPTION"})
    if df.empty:
        return {"nodes": [], "links": []}

    def root_name(cid):
        c = cats.get(cid or "")
        while c and c.parent_id:
            c = cats.get(c.parent_id)
        return c.name if c else "A classificar"

    links: dict[tuple[str, str], float] = defaultdict(float)
    pnl = df[df["event_type"].isin(EventType.PNL)]
    inc = pnl[pnl["amount"] > 0].copy()
    exp = pnl[pnl["amount"] < 0].copy()
    # reembolsos reduzem a categoria de despesa em vez de virar fonte
    refunds = inc[inc["event_type"] == "REFUND"]
    inc = inc[inc["event_type"] != "REFUND"]
    for cid, v in inc.groupby("category_id")["amount"].sum().items():
        links[(root_name(cid) if cats.get(cid) and cats[cid].nature != "receita" else (cats[cid].name if cid in cats else "Receitas"), "Entradas do mês")] += v
    exp_by = defaultdict(float)
    for cid, v in exp.groupby("category_id")["amount"].sum().items():
        exp_by[root_name(cid)] += -v
    for cid, v in refunds.groupby("category_id")["amount"].sum().items():
        exp_by[root_name(cid)] -= v
    total_in = sum(v for (src, dst), v in links.items())
    for name, v in sorted(exp_by.items(), key=lambda kv: -kv[1]):
        if v > 0.5:
            links[("Entradas do mês", name)] += v
    inv = df[df["event_type"].isin(["INVESTMENT_CONTRIBUTION", "INVESTMENT_REDEMPTION"])]
    net_inv = -float(inv["amount"].sum()) if not inv.empty else 0.0
    if net_inv > 0:
        links[("Entradas do mês", "Investimentos (líquido)")] += net_inv
    left = total_in - sum(v for (src, _), v in links.items() if src == "Entradas do mês")
    if left > 0.5:
        links[("Entradas do mês", "Sobra em caixa")] += left
    elif left < -0.5:
        links[("Caixa/resgates", "Entradas do mês")] += -left
    nodes = sorted({n for k in links for n in k})
    return {"nodes": [{"name": n} for n in nodes],
            "links": [{"source": s_, "target": t, "value": round(v, 2)} for (s_, t), v in links.items() if v > 0.5]}
