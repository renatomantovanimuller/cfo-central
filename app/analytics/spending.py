"""Leitura de gastos para uma janela de meses: árvore de categorias, mês a mês, calendário, dia da semana,
comerciantes e maiores gastos, sempre contra a janela anterior de mesmo tamanho.

Gasto = −valor dos eventos de despesa (EXPENSE, FINANCIAL_EXPENSE, TAX) e estornos (REFUND, que reduzem),
por data de competência — a mesma base do DRE e do painel."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounting.statements import month_list
from app.analytics.overview import EXPENSE_LIKE, _root_map
from app.models import Account, AccountSetting, Budget, FinancialEvent, Merchant
from app.utils.time import month_add, month_bounds, month_key, today_brt

NC = "nc"
TOP_SERIES = 6
GROUP_LABELS = {"essenciais": "Essencial", "estilo_vida": "Estilo de vida", "terceiros": "Transferências a terceiros",
                "despesas_financeiras": "Juros e tarifas", "impostos": "Impostos"}
WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def _window(end: str, months: int) -> tuple[list[str], date, date]:
    ms = month_list(end, months)
    return ms, month_bounds(ms[0])[0], month_bounds(ms[-1])[1]


def _budgets(s: Session, ms: list[str]) -> dict[str, float]:
    """Orçamento por categoria somado na janela (valor do mês específico vence o padrão)."""
    default: dict[str, float] = {}
    specific: dict[tuple[str, str], float] = {}
    for b in s.scalars(select(Budget)):
        if b.month:
            specific[(b.category_id, b.month)] = b.amount
        else:
            default[b.category_id] = b.amount
    out: dict[str, float] = defaultdict(float)
    for cid in set(default) | {c for c, _ in specific}:
        for m in ms:
            v = specific.get((cid, m), default.get(cid))
            if v:
                out[cid] += v
    return out


def spending_report(s: Session, end: str | None = None, months: int = 1, account: str | None = None) -> dict:
    end = end or month_key(today_brt())
    months = max(1, min(months, 24))
    ms, a, b = _window(end, months)
    pms, pa, pb = _window(month_add(ms[0], -1), months)
    today = today_brt()
    last_day = min(b, today)
    cats, roots = _root_map(s)

    cond = [FinancialEvent.is_removed.is_(False), FinancialEvent.competence_date.between(pa, b),
            FinancialEvent.event_type.in_(EXPENSE_LIKE)]
    if account:
        cond.append(FinancialEvent.account_id == account)
    rows = s.execute(select(FinancialEvent.source_id, FinancialEvent.competence_date, FinancialEvent.amount,
                            FinancialEvent.category_id, FinancialEvent.merchant_id, FinancialEvent.description,
                            FinancialEvent.account_id, FinancialEvent.installment_key).where(*cond)).all()

    def root_of(cid):
        return roots.get(cid, NC) if cid else NC

    def name_of(cid):
        return cats[cid].name if cid in cats else "A classificar"

    tree: dict[str, dict] = {}
    by_month: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    daily: dict[date, float] = defaultdict(float)
    groups: dict[str, float] = defaultdict(float)
    groups_prev: dict[str, float] = defaultdict(float)
    merch: dict[int, dict] = {}
    merch_prev: dict[int, float] = defaultdict(float)
    by_account: dict[str, float] = defaultdict(float)
    biggest = []
    total = prev_total = installments = 0.0
    n_cur = n_prev = 0

    for sid, d, amt, cid, mid, desc, acc, inst in rows:
        v = -amt
        r = root_of(cid)
        cur = d >= a
        node = tree.setdefault(r, {"id": r, "name": name_of(r) if r != NC else "A classificar", "value": 0.0,
                                   "prev": 0.0, "count": 0, "children": {}})
        child_id = cid if cid and cid != r else f"{r}:direto"
        child = node["children"].setdefault(child_id, {"id": cid or r, "name": name_of(cid) if cid and cid != r
                                                       else f"{node['name']} (geral)", "value": 0.0, "prev": 0.0,
                                                       "count": 0})
        c = cats.get(cid)
        line = (c.dre_line if c and c.dre_line else (cats[r].dre_line if r in cats else None)) or "outros"
        g = GROUP_LABELS.get(line, "Outros")
        if cur:
            node["value"] += v
            child["value"] += v
            node["count"] += 1
            child["count"] += 1
            total += v
            n_cur += 1
            by_month[month_key(d)][r] += v
            daily[d] += v
            groups[g] += v
            if acc:
                by_account[acc] += v
            if inst:
                installments += v
            if mid:
                m = merch.setdefault(mid, {"total": 0.0, "count": 0, "cats": Counter()})
                m["total"] += v
                if v > 0:
                    m["count"] += 1
                    m["cats"][r] += 1
            if v > 0:
                biggest.append((v, sid, d, desc, cid, mid))
        else:
            node["prev"] += v
            child["prev"] += v
            prev_total += v
            n_prev += 1
            groups_prev[g] += v
            if mid:
                merch_prev[mid] += v

    budgets = _budgets(s, ms)

    def budget_for(cid: str) -> float | None:
        own = budgets.get(cid)
        if own:
            return round(own, 2)
        kids = [budgets[k] for k, c in cats.items() if c.parent_id == cid and budgets.get(k)]
        return round(sum(kids), 2) if kids else None

    cat_rows = []
    for node in tree.values():
        kids = sorted(node.pop("children").values(), key=lambda x: -x["value"])
        node["children"] = [{**k, "value": round(k["value"], 2), "prev": round(k["prev"], 2)}
                            for k in kids if abs(k["value"]) > 0.005 or abs(k["prev"]) > 0.005]
        node.update(value=round(node["value"], 2), prev=round(node["prev"], 2),
                    share=node["value"] / total if total > 0 else None,
                    budget=budget_for(node["id"]) if node["id"] != NC else None,
                    color=cats[node["id"]].color if node["id"] in cats else None)
        if abs(node["value"]) > 0.005 or abs(node["prev"]) > 0.005:
            cat_rows.append(node)
    cat_rows.sort(key=lambda x: -x["value"])

    top_ids = [c["id"] for c in cat_rows if c["value"] > 0][:TOP_SERIES]
    names = {c["id"]: c["name"] for c in cat_rows}
    series = []
    for m in ms:
        vals = by_month.get(m, {})
        row = {"month": m, "total": round(sum(vals.values()), 2)}
        row["by"] = {names[i]: round(vals.get(i, 0.0), 2) for i in top_ids}
        rest = sum(v for k, v in vals.items() if k not in top_ids)
        if abs(rest) > 0.005:
            row["by"]["Outras"] = round(rest, 2)
        series.append(row)

    days = [a + timedelta(days=i) for i in range((last_day - a).days + 1)] if last_day >= a else []
    wk_sum = [0.0] * 7
    wk_days = [0] * 7
    for d in days:
        wk_sum[d.weekday()] += daily.get(d, 0.0)
        wk_days[d.weekday()] += 1
    weekday = [{"dia": WEEKDAYS[i], "total": round(wk_sum[i], 2),
                "media": round(wk_sum[i] / wk_days[i], 2) if wk_days[i] else None} for i in range(7)]

    mnames = {m.id: m.canonical_name for m in s.scalars(select(Merchant).where(Merchant.id.in_(
        list(merch) + list(merch_prev) or [-1])))}
    merchants = []
    for mid, m in sorted(merch.items(), key=lambda kv: -kv[1]["total"])[:20]:
        if m["total"] <= 0.005:
            continue
        top_root = m["cats"].most_common(1)[0][0] if m["cats"] else None
        merchants.append({"id": mid, "name": mnames.get(mid, str(mid)), "total": round(m["total"], 2),
                          "count": m["count"], "ticket": round(m["total"] / m["count"], 2) if m["count"] else None,
                          "prev": round(merch_prev.get(mid, 0.0), 2),
                          "share": m["total"] / total if total > 0 else None,
                          "category": names.get(top_root) if top_root else None})
    new_merchants = sum(1 for mid in merch if merch[mid]["total"] > 0 and merch_prev.get(mid, 0.0) <= 0.005)

    accs = {x.id: x for x in s.scalars(select(Account))}
    nick = {x.account_id: x.nickname for x in s.scalars(select(AccountSetting))}
    accounts = [{"id": k, "name": nick.get(k) or (accs[k].name if k in accs else k),
                 "type": accs[k].type if k in accs else None, "total": round(v, 2)}
                for k, v in sorted(by_account.items(), key=lambda kv: -kv[1]) if abs(v) > 0.005]

    biggest.sort(key=lambda x: -x[0])
    big_rows = [{"id": sid, "date": d.isoformat(), "description": desc, "value": round(v, 2),
                 "category": name_of(cid), "merchant": mnames.get(mid) if mid else None}
                for v, sid, d, desc, cid, mid in biggest[:12]]

    elapsed = len(days) or 1
    return {
        "end": end, "months": months, "range": {"start": a.isoformat(), "end": b.isoformat(),
                                                "last_day": last_day.isoformat(), "partial": b > today},
        "previous_range": {"start": pa.isoformat(), "end": pb.isoformat()},
        "account": account,
        "totals": {"value": round(total, 2), "prev": round(prev_total, 2), "count": n_cur, "prev_count": n_prev,
                   "per_month": round(total / months, 2), "per_day": round(total / elapsed, 2),
                   "installments": round(installments, 2), "new_merchants": new_merchants,
                   "budget": round(sum(c["budget"] or 0 for c in cat_rows), 2) or None},
        "groups": [{"name": k, "value": round(v, 2), "prev": round(groups_prev.get(k, 0.0), 2)}
                   for k, v in sorted(groups.items(), key=lambda kv: -kv[1]) if abs(v) > 0.005],
        "categories": cat_rows,
        "series": series,
        "daily": [{"date": d.isoformat(), "value": round(daily.get(d, 0.0), 2)} for d in days],
        "weekday": weekday,
        "merchants": merchants,
        "accounts": accounts,
        "biggest": big_rows,
    }
