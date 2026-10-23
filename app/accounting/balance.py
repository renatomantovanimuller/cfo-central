"""Balanço patrimonial: posição atual com composição/premissas, histórico (snapshot ou reconstruído) e snapshot diário."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounting.effective import excluded_pending_ids
from app.models import (Account, AccountSetting, DailyNetWorth, FinancialEvent, Institution, Item, Loan,
                        ManualAsset, Transaction)
from app.utils.time import month_bounds, month_key, today_brt


def future_installments(s: Session) -> dict:
    """Parcelas de cartão ainda a lançar, por mês (a partir do último lançamento de cada compra)."""
    rows = s.execute(select(FinancialEvent.installment_key, FinancialEvent.account_id, FinancialEvent.description,
                            FinancialEvent.amount, FinancialEvent.competence_date, Transaction.installment_number,
                            Transaction.total_installments)
                     .join(Transaction, Transaction.id == FinancialEvent.source_id)
                     .where(FinancialEvent.installment_key.is_not(None), FinancialEvent.is_removed.is_(False),
                            FinancialEvent.event_type == "EXPENSE")).all()
    latest: dict[str, tuple] = {}
    for r in rows:
        cur = latest.get(r.installment_key)
        if cur is None or (r.installment_number or 0) > (cur.installment_number or 0):
            latest[r.installment_key] = r
    # a 1ª parcela costuma ter centavos de arredondamento diferentes e cai noutra chave: chaves da mesma compra
    # (cartão|comerciante|nº de parcelas) com valores a até R$ 1/2% são o mesmo plano, vale a parcela mais recente
    same_purchase: dict[str, list] = defaultdict(list)
    for k, r in latest.items():
        same_purchase[k.rsplit("|", 1)[0]].append(r)
    plans_latest = []
    for rs in same_purchase.values():
        rs.sort(key=lambda r: abs(r.amount))
        cluster = [rs[0]]
        for r in rs[1:]:
            if abs(abs(r.amount) - abs(cluster[-1].amount)) <= max(1.0, 0.02 * abs(r.amount)):
                cluster.append(r)
            else:
                plans_latest.append(max(cluster, key=lambda x: x.installment_number or 0))
                cluster = [r]
        plans_latest.append(max(cluster, key=lambda x: x.installment_number or 0))
    today_m = month_key(today_brt())
    by_month: dict[str, float] = defaultdict(float)
    plans = []
    for r in plans_latest:
        remaining = (r.total_installments or 0) - (r.installment_number or 0)
        if remaining <= 0:
            continue
        base = r.competence_date
        months = []
        for k in range(1, remaining + 1):
            y, m = base.year + (base.month - 1 + k) // 12, (base.month - 1 + k) % 12 + 1
            mk = f"{y:04d}-{m:02d}"
            if mk >= today_m:
                months.append(mk)
                by_month[mk] += abs(r.amount)
        if months:
            plans.append({"key": r.installment_key, "account_id": r.account_id, "description": r.description,
                          "installment": abs(r.amount), "paid": r.installment_number, "total": r.total_installments,
                          "remaining": len(months), "remaining_amount": len(months) * abs(r.amount),
                          "last_date": r.competence_date})
    return {"plans": sorted(plans, key=lambda p: -p["remaining_amount"]),
            "by_month": [{"month": k, "amount": round(v, 2)} for k, v in sorted(by_month.items())],
            "total": round(sum(by_month.values()), 2)}


def _num(v) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def card_usage(a: Account) -> tuple[float | None, float | None]:
    """(limite efetivo, limite usado) de um cartão.

    O `creditLimit` da Pluggy é o limite contratado; quando o cliente reduz o limite no app do banco, o disponível
    passa a ser calculado sobre o limite personalizado (`customizedLimitAmount`). Usado = `usedAmount` da linha de
    limite total do Open Finance; sem ela, limite efetivo − disponível.
    """
    lines = [x for x in ((a.credit_data or {}).get("disaggregatedCreditLimits") or []) if isinstance(x, dict)]
    total = [x for x in lines if x.get("creditLineLimitType") == "LIMITE_CREDITO_TOTAL"] or lines
    custom = [v for v in (_num(x.get("customizedLimitAmount")) for x in total) if v]
    limit = a.credit_limit
    if custom and (limit is None or min(custom) < limit):
        limit = min(custom)
    used_vals = [v for v in (_num(x.get("usedAmount")) for x in total) if v is not None]
    if used_vals:
        used = max(used_vals)
    elif limit is not None and a.available_credit is not None:
        used = max(0.0, limit - a.available_credit)
    else:
        used = None
    return limit, used


def current_position(s: Session) -> dict:
    from app.portfolio.service import positions

    insts = {i.id: i.name for i in s.scalars(select(Institution))}
    items = {i.id: (i.nickname or insts.get(i.institution_id, "")) for i in s.scalars(select(Item))}
    settings = {x.account_id: x for x in s.scalars(select(AccountSetting))}
    assumptions: list[str] = []
    cash, cards = [], []
    for a in s.scalars(select(Account).where(Account.removed_at.is_(None))):
        st = settings.get(a.id)
        if st and not st.include_in_net_worth:
            assumptions.append(f"Conta {st.nickname or a.name} excluída do patrimônio por configuração.")
            continue
        label = (st.nickname if st and st.nickname else a.name) or a.id[:8]
        if a.type == "CREDIT":
            current = abs(a.balance or 0)
            limit, used = card_usage(a)
            cards.append({"account_id": a.id, "name": label, "institution": items.get(a.item_id), "current": current,
                          "used_total": used, "limit": limit, "contract_limit": a.credit_limit,
                          "available": a.available_credit,
                          "close_date": a.bill_close_date, "due_date": a.bill_due_date})
        else:
            cash.append({"account_id": a.id, "name": label, "institution": items.get(a.item_id),
                         "balance": a.balance or 0.0, "subtype": a.subtype})
    inst = future_installments(s)
    card_current = sum(c["current"] for c in cards)
    used_total = sum(c["used_total"] for c in cards if c["used_total"] is not None)
    if cards and all(c["used_total"] is not None for c in cards):
        card_future = max(0.0, used_total - card_current)
        assumptions.append("Cartões: fatura atual = saldo informado pela instituição; parcelas futuras = "
                           "limite usado − fatura atual (inclui compras ainda não faturadas). Limite usado vem do Open Finance; "
                           "limite reduzido no app do banco é respeitado.")
    else:
        card_future = inst["total"]
        assumptions.append("Cartões: parcelas futuras estimadas pelas compras parceladas identificadas.")
    pos = positions(s)
    by_class: dict[str, float] = defaultdict(float)
    for p in pos:
        by_class[p["asset_class"]] += p["balance"]
    assumptions.append("Investimentos: valor líquido informado pela instituição (pode já descontar IR/IOF estimados).")
    from app.portfolio.transit import detect_exits, transit_summary
    transit = transit_summary(detect_exits(s))
    if transit["lines"]:
        assumptions.append("Valores em trânsito: investimento cujo saldo caiu sem venda registrada nem crédito em conta "
                           "conectada; mantido no patrimônio até a contrapartida aparecer ou você resolver a revisão.")
    if transit["perimeter_exits"]:
        assumptions.append(f"Saída do perímetro (conta não conectada): R$ {transit['perimeter_exits']:,.2f} "
                           "registrada como movimento patrimonial explícito, fora da valorização.")
    if transit["writeoffs"]:
        assumptions.append(f"Baixa/perda explícita de investimentos: R$ {transit['writeoffs']:,.2f}.")
    loans = [{"id": l.id, "name": l.product_name or l.type, "outstanding": l.outstanding or 0.0}
             for l in s.scalars(select(Loan).where(Loan.removed_at.is_(None)))]
    manual = list(s.scalars(select(ManualAsset).where(ManualAsset.active.is_(True))))
    m_assets = [{"id": m.id, "name": m.name, "class": m.asset_class, "value": m.value, "as_of": m.as_of}
                for m in manual if m.kind == "asset"]
    m_liab = [{"id": m.id, "name": m.name, "class": m.asset_class, "value": m.value, "as_of": m.as_of}
              for m in manual if m.kind == "liability"]
    if manual:
        assumptions.append("Itens manuais valem pelo último valor informado (data em 'as_of').")
    totals = {
        "cash": sum(c["balance"] for c in cash), "investments": sum(by_class.values()),
        "manual_assets": sum(m["value"] for m in m_assets), "in_transit": transit["in_transit"],
        "perimeter_exits": transit["perimeter_exits"], "writeoffs": transit["writeoffs"], "card_current": card_current, "card_future": card_future,
        "loans": sum(l["outstanding"] for l in loans), "manual_liabilities": sum(m["value"] for m in m_liab),
    }
    totals["assets"] = totals["cash"] + totals["investments"] + totals["in_transit"] + totals["manual_assets"]
    totals["liabilities"] = totals["card_current"] + totals["card_future"] + totals["loans"] + totals["manual_liabilities"]
    totals["net_worth"] = totals["assets"] - totals["liabilities"]
    totals["liquid_net_worth"] = totals["cash"] + sum(v for k, v in by_class.items()
                                                      if k not in ("Previdência", "COE")) - totals["card_current"]
    return {"as_of": today_brt(), "totals": totals, "cash": cash, "investments_by_class": dict(by_class),
            "positions": pos, "cards": cards, "installments": inst, "loans": loans, "manual_assets": m_assets,
            "manual_liabilities": m_liab, "in_transit": transit["lines"], "assumptions": assumptions}


def snapshot_net_worth(s: Session) -> dict:
    p = current_position(s)
    t = p["totals"]
    d = p["as_of"]
    row = s.get(DailyNetWorth, d) or DailyNetWorth(date=d)
    # a coluna `investments` inclui valores em trânsito (detalhados na composição)
    row.cash, row.investments, row.manual_assets = t["cash"], t["investments"] + t["in_transit"], t["manual_assets"]
    row.card_current, row.card_future, row.loans = t["card_current"], t["card_future"], t["loans"]
    row.manual_liabilities, row.net_worth = t["manual_liabilities"], t["net_worth"]
    row.composition = {"investments_by_class": p["investments_by_class"],
                       "cash": {c["name"]: c["balance"] for c in p["cash"]},
                       "in_transit": t["in_transit"], "perimeter_exits": t["perimeter_exits"],
                       "writeoffs": t["writeoffs"]}
    row.assumptions, row.is_inferred = p["assumptions"], False
    s.add(row)
    s.flush()
    return {"date": d.isoformat(), "net_worth": t["net_worth"]}


def history(s: Session, months: int = 12) -> list[dict]:
    """Balanço em cada fim de mês. Usa snapshot quando existe; senão reconstrói (marcado como inferido):
    contas e cartões: saldo(d) = saldo_atual − Σ fluxos após d; investimentos: reconstrução por proxy."""
    from app.portfolio.service import reconstruct_history

    today = today_brt()
    snaps = {r.date: r for r in s.scalars(select(DailyNetWorth))}
    cur = current_position(s)["totals"]
    # mesmo perímetro do saldo atual: sem contas removidas nem excluídas do patrimônio
    outside = list(s.scalars(select(AccountSetting.account_id).where(AccountSetting.include_in_net_worth.is_(False))))
    flows = s.execute(select(Transaction.date, Account.type, func.sum(Transaction.flow))
                      .join(Account, Account.id == Transaction.account_id)
                      .where(Transaction.removed_at.is_(None), Account.removed_at.is_(None),
                             Account.id.not_in(outside or ["-"]),
                             Transaction.id.not_in(excluded_pending_ids(s)))
                      .group_by(Transaction.date, Account.type)).all()
    fdf = pd.DataFrame(flows, columns=["date", "type", "flow"]) if flows else pd.DataFrame(columns=["date", "type", "flow"])
    inv_hist = reconstruct_history(s, days=31 * months + 31)
    from app.portfolio.transit import detect_exits, transit_summary
    transit_lines = transit_summary(detect_exits(s))["lines"]
    out = []
    ym = month_key(today)
    for k in range(months, -1, -1):
        y, m = today.year, today.month - k
        while m <= 0:
            y, m = y - 1, m + 12
        _, end = month_bounds(f"{y:04d}-{m:02d}")
        d = min(end, today)
        snap = snaps.get(d)
        if snap:
            # snapshots gravados antes da detecção não contêm o trânsito: soma desde a data da saída
            extra = 0.0 if "in_transit" in (snap.composition or {}) else \
                sum(e["amount"] for e in transit_lines if e["date"] <= d)
            out.append({"date": d.isoformat(), "cash": snap.cash, "investments": snap.investments + extra,
                        "cards": snap.card_current, "card_future": snap.card_future, "loans": snap.loans,
                        "manual": snap.manual_assets - snap.manual_liabilities, "net_worth": snap.net_worth + extra,
                        "inferred": False})
            continue
        after = fdf[fdf["date"] > d] if not fdf.empty else fdf
        bank_after = float(after[after["type"] == "BANK"]["flow"].sum()) if not after.empty else 0.0
        card_after = float(after[after["type"] == "CREDIT"]["flow"].sum()) if not after.empty else 0.0
        cash = cur["cash"] - bank_after
        cards = max(0.0, cur["card_current"] + card_after)  # saldo do cartão (negativo = dívida) recuado
        inv = float(inv_hist.get(d, inv_hist.iloc[0] if len(inv_hist) else cur["investments"])) \
            if len(inv_hist) else cur["investments"]
        nw = cash + inv + cur["manual_assets"] - cards - cur["loans"] - cur["manual_liabilities"]
        out.append({"date": d.isoformat(), "cash": cash, "investments": inv, "cards": cards, "card_future": None,
                    "loans": cur["loans"], "manual": cur["manual_assets"] - cur["manual_liabilities"],
                    "net_worth": nw, "inferred": True, "month": ym})
    return out
