"""Carteira: posições, alocação, FGC, vencimentos, performance realizada e risco ex-ante."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.reviews import ReviewCandidate, fmt_brl
from app.categorization.text import norm
from app.config.settings import get_settings
from app.models import (Asset, AssetPrice, FinancialEvent, Institution, Investment, InvestmentBalance,
                        InvestmentTransaction, Item)
from app.portfolio import metrics as M
from app.portfolio.classification import RISK_BUCKET, classify
from app.portfolio.market import BENCHMARKS, accumulated, cdi_daily, ipca_accumulated, price_frame, series_frame
from app.utils.time import today_brt


# ------------------------------------------------------------------ classificação
def classify_investments(s: Session) -> int:
    assets = {a.key: a for a in s.scalars(select(Asset))}
    n = 0
    for inv in s.scalars(select(Investment)):
        c = classify({k: getattr(inv, k) for k in ("type", "subtype", "code", "isin", "rate_type", "issuer",
                                                     "name", "rate", "due_date")})
        a = assets.get(c["key"])
        if a is None:
            a = Asset(key=c["key"], name=inv.name, asset_class=c["asset_class"], indexer=c["indexer"],
                      liquidity=c["liquidity"], issuer=c["issuer"], fgc_covered=c["fgc_covered"],
                      yahoo_symbol=c["yahoo_symbol"], risk_proxy=c["risk_proxy"], origin="auto")
            s.add(a)
            s.flush()
            assets[a.key] = a
        elif a.origin == "auto":  # usuário pode sobrescrever (origin=user)
            for k in ("asset_class", "indexer", "liquidity", "fgc_covered", "yahoo_symbol", "risk_proxy"):
                setattr(a, k, c[k])
            a.issuer = a.issuer or c["issuer"]
        if inv.asset_id != a.id:
            inv.asset_id = a.id
            n += 1
    s.flush()
    return n


def _issuer_key(name: str | None, cnpj: str | None) -> str:
    if cnpj:
        return cnpj[:8]  # raiz do CNPJ = conglomerado
    n = norm(name).split(" - ")[0]
    return " ".join(n.split()[:3]) or "desconhecido"


# ------------------------------------------------------------------ posições
def positions(s: Session) -> list[dict]:
    insts = {i.id: i.name for i in s.scalars(select(Institution))}
    items = {i.id: (i.nickname or insts.get(i.institution_id, "")) for i in s.scalars(select(Item))}
    assets = {a.id: a for a in s.scalars(select(Asset))}
    cdi = cdi_daily(s, today_brt() - timedelta(days=365 * 6))
    today = today_brt()
    out = []
    for inv in s.scalars(select(Investment).where(Investment.removed_at.is_(None))):
        if (inv.status or "ACTIVE") == "TOTAL_WITHDRAWAL" or not (inv.balance or 0) > 0.005:
            continue
        a = assets.get(inv.asset_id)
        bal = inv.balance or 0.0
        cost = inv.amount_original
        profit = inv.amount_profit if inv.amount_profit is not None else (bal - cost if cost else None)
        start = inv.purchase_date or inv.issue_date
        ret = (bal / cost - 1) if cost else None
        ann = None
        pct_cdi = None
        if ret is not None and start and (today - start).days >= 30:
            yrs = (today - start).days / 365.0
            ann = (1 + ret) ** (1 / yrs) - 1 if ret > -1 else None
            cdi_acc = accumulated(cdi, start, today) if not cdi.empty else None
            if cdi_acc and cdi_acc > 0 and ret > -1:
                pct_cdi = math.log(1 + ret) / math.log(1 + cdi_acc)
        out.append({
            "id": inv.id, "name": inv.name, "code": inv.code, "isin": inv.isin, "type": inv.type,
            "subtype": inv.subtype, "institution": items.get(inv.item_id, ""),
            "asset_class": a.asset_class if a else "Outros", "bucket": RISK_BUCKET.get(a.asset_class if a else "Outros"),
            "indexer": a.indexer if a else None, "liquidity": a.liquidity if a else None,
            "issuer": (a.issuer if a else None) or inv.issuer, "issuer_key": _issuer_key(inv.issuer, inv.issuer_cnpj),
            "fgc_covered": bool(a.fgc_covered) if a else False, "yahoo_symbol": a.yahoo_symbol if a else None,
            "risk_proxy": a.risk_proxy if a else "CDI", "asset_id": inv.asset_id,
            "balance": bal, "gross": inv.amount, "cost": cost, "profit": profit, "return_total": ret,
            "return_ann": ann, "pct_cdi": pct_cdi, "quantity": inv.quantity, "unit_price": inv.value,
            "rate": inv.rate, "rate_type": inv.rate_type, "fixed_rate": inv.fixed_annual_rate,
            "last_12m_rate": inv.last_12m_rate, "due_date": inv.due_date, "purchase_date": start,
            "taxes": (inv.taxes or 0) + (inv.taxes2 or 0),
        })
    total = sum(p["balance"] for p in out) or 1.0
    for p in out:
        p["weight"] = p["balance"] / total
    return sorted(out, key=lambda p: -p["balance"])


def allocation(pos: list[dict]) -> dict:
    total = sum(p["balance"] for p in pos)

    def group(key) -> list[dict]:
        agg: dict[str, float] = defaultdict(float)
        for p in pos:
            agg[key(p) or "—"] += p["balance"]
        return [{"label": k, "value": v, "pct": v / total if total else 0}
                for k, v in sorted(agg.items(), key=lambda kv: -kv[1])]

    usd = sum(p["balance"] for p in pos if p["asset_class"] in ("ETF Internacional",))
    weights = pd.Series({p["id"]: p["balance"] for p in pos}, dtype=float)
    top5 = float(weights.sort_values(ascending=False).head(5).sum() / total) if total else 0
    return {
        "total": total, "by_class": group(lambda p: p["asset_class"]), "by_bucket": group(lambda p: p["bucket"]),
        "by_indexer": group(lambda p: {"CDI": "CDI", "SELIC": "Selic", "IPCA": "IPCA", "PRE": "Prefixado",
                                       "VAR": "Renda variável"}.get(p["indexer"] or "", "Outros")),
        "by_liquidity": group(lambda p: p["liquidity"]), "by_institution": group(lambda p: p["institution"]),
        "by_issuer": group(lambda p: p["issuer"]),
        "concentration": {"hhi": M.hhi(weights) if total else 0, "effective_n": 1 / M.hhi(weights) if total else 0,
                          "top5": top5, "usd_exposure": usd / total if total else 0},
    }


def fgc_exposure(pos: list[dict]) -> list[dict]:
    limit = get_settings().fgc_limit
    agg: dict[str, dict] = {}
    for p in pos:
        if not p["fgc_covered"]:
            continue
        g = agg.setdefault(p["issuer_key"], {"issuer": p["issuer"], "value": 0.0, "count": 0})
        g["value"] += p["gross"] or p["balance"]
        g["count"] += 1
    out = [{**g, "limit": limit, "usage": g["value"] / limit, "excess": max(0.0, g["value"] - limit)}
           for g in agg.values()]
    return sorted(out, key=lambda x: -x["value"])


def maturity_ladder(pos: list[dict]) -> list[dict]:
    agg: dict[str, float] = defaultdict(float)
    today = today_brt()
    for p in pos:
        d = p["due_date"]
        if not d:
            continue
        if d <= today + timedelta(days=365):
            k = "≤ 1 ano"
        else:
            k = str(d.year)
        agg[k] += p["balance"]
    return [{"bucket": k, "value": v} for k, v in sorted(agg.items(), key=lambda kv: ("0" if kv[0].startswith("≤") else kv[0]))]


# ------------------------------------------------------------------ retornos diários (proxy)
def asset_returns(s: Session, pos: list[dict], start: date) -> pd.DataFrame:
    """Retorno diário de cada posição: preço (Yahoo) ou CDI/Selic × % contratado. Proxies identificados."""
    sf = series_frame(s, ["CDI", "SELIC"], start)
    if sf.empty or "CDI" not in sf:
        return pd.DataFrame()
    idx = sf.index
    symbols = sorted({p["risk_proxy"] for p in pos if p["risk_proxy"] and any(c in p["risk_proxy"] for c in ".^=")})
    prices = price_frame(s, symbols, start - timedelta(days=10))
    cols = {}
    for p in pos:
        proxy = p["risk_proxy"] or "CDI"
        if proxy in ("CDI", "SELIC"):
            base = sf[proxy if proxy in sf else "CDI"] / 100
            mult = (p["rate"] / 100) if p["indexer"] == "CDI" and p["rate"] and p["rate"] > 10 else 1.0
            cols[p["id"]] = base * mult
        elif proxy in prices:
            px = prices[proxy].reindex(prices.index.union(idx)).sort_index().ffill().reindex(idx)
            cols[p["id"]] = clean_returns(px.pct_change())
    df = pd.DataFrame(cols, index=idx).iloc[1:]
    return df.fillna(0.0)


def clean_returns(r: pd.Series, limit: float = 0.25) -> pd.Series:
    """Saltos diários > 25% em ETFs/ações são quase sempre falha de dado (lacuna na fonte) — zerados."""
    return r.where(r.abs() <= limit, 0.0)


def risk_report(s: Session, years: int = 2) -> dict:
    pos = positions(s)
    if not pos:
        return {"available": False, "reason": "sem posições"}
    start = today_brt() - timedelta(days=365 * years)
    rets = asset_returns(s, pos, start)
    if rets.empty or len(rets) < 30:
        return {"available": False, "reason": "séries de mercado ainda não sincronizadas"}
    w = pd.Series({p["id"]: p["balance"] for p in pos if p["id"] in rets.columns}, dtype=float)
    w = w / w.sum()
    port = (rets[w.index] * w).sum(axis=1)
    cdi = cdi_daily(s, start).reindex(port.index).fillna(0)
    bench_px = price_frame(s, list(BENCHMARKS), start - timedelta(days=10))
    ibov = clean_returns(bench_px["^BVSP"].reindex(bench_px.index.union(port.index)).ffill().reindex(port.index).pct_change()) \
        if "^BVSP" in bench_px else None
    stats = M.risk_stats(port, cdi, ibov)

    by_id = {p["id"]: p for p in pos}
    rc = M.risk_contributions(rets, w)
    contrib = []
    if not rc.empty:
        for pid, row in rc.sort_values("risk_contribution", ascending=False).iterrows():
            contrib.append({"id": pid, "name": by_id[pid]["name"], "asset_class": by_id[pid]["asset_class"],
                            "weight": float(row["weight"]), "vol_ann": float(row["vol_ann"]),
                            "risk_contribution": float(row["risk_contribution"])})

    # correlação por classe (retorno ponderado dentro da classe)
    class_rets = {}
    for cls in sorted({p["asset_class"] for p in pos}):
        ids = [p["id"] for p in pos if p["asset_class"] == cls and p["id"] in rets.columns]
        if ids:
            ww = w[ids] / w[ids].sum()
            class_rets[cls] = (rets[ids] * ww).sum(axis=1)
    cr = pd.DataFrame(class_rets)
    corr = cr.corr().round(3) if cr.shape[1] > 1 else pd.DataFrame()

    # curva acumulada vs benchmarks
    curves = {"Carteira (pesos atuais)": M.cumulative(port), "CDI": M.cumulative(cdi)}
    for sym, label in (("^BVSP", "Ibovespa"), ("IVVB11.SA", "S&P 500 em BRL"), ("IMAB11.SA", "IMA-B")):
        if sym in bench_px:
            b = clean_returns(bench_px[sym].reindex(bench_px.index.union(port.index)).ffill().reindex(port.index).pct_change().fillna(0))
            curves[label] = M.cumulative(b)
    step = max(1, len(port) // 260)
    curve_rows = [{"date": d.isoformat(), **{k: round(float(v.loc[d]) * 100, 3) for k, v in curves.items()}}
                  for d in port.index[::step]]
    dd = (1 + port).cumprod()
    drawdown = [{"date": d.isoformat(), "dd": round(float(v) * 100, 3)} for d, v in (dd / dd.cummax() - 1)[::step].items()]
    proxies = sorted({f"{p['asset_class']}: {p['risk_proxy']}" for p in pos if not p["yahoo_symbol"]})
    return {
        "available": True, "years": years, "stats": _clean(stats), "risk_contribution": contrib,
        "correlation": {"labels": list(corr.columns), "matrix": corr.values.tolist()} if not corr.empty else None,
        "curves": curve_rows, "drawdown": drawdown,
        "assumptions": [
            "Risco ex-ante: pesos atuais aplicados ao histórico de retornos diários (não é o retorno que você obteve).",
            "Renda fixa pós usa CDI × % contratado; IPCA+ usa IMAB11 e pré usa IRFM11 como proxy de marcação.",
            *[f"Proxy — {x}" for x in proxies],
        ],
    }


def performance(s: Session) -> dict:
    """Retorno realizado: TWR a partir dos snapshots diários + TIR dos fluxos do período."""
    rows = s.execute(select(InvestmentBalance.date, InvestmentBalance.balance)).all()
    if not rows:
        return {"available": False}
    df = pd.DataFrame(rows, columns=["date", "balance"]).groupby("date")["balance"].sum().sort_index()
    ev = s.execute(select(FinancialEvent.competence_date, FinancialEvent.amount)
                   .where(FinancialEvent.event_type.in_(["INVESTMENT_CONTRIBUTION", "INVESTMENT_REDEMPTION"]),
                          FinancialEvent.is_removed.is_(False))).all()
    flows = pd.Series({}, dtype=float)
    if ev:
        fd = pd.DataFrame(ev, columns=["date", "amount"])
        flows = (-fd.groupby("date")["amount"].sum()).sort_index()  # aporte (saída do caixa) = fluxo + p/ carteira
    out = {"available": True, "snapshots": int(len(df)), "first": df.index[0], "last": df.index[-1]}
    if len(df) >= 2:
        from app.portfolio.transit import detect_exits
        # saída sem contrapartida mantida em trânsito: o valor segue no numerador (não é perda); saída explícita
        # para conta não conectada é fluxo de resgate no dia da saída
        for e in detect_exits(s):
            if e["state"] in ("pending", "custody_transferred", "provider_error"):
                df = df + pd.Series({d: (e["amount"] if d >= e["date"] else 0.0) for d in df.index})
            elif e["state"] == "not_connected_account" and e["date"] in df.index:
                flows = flows.add(pd.Series({e["date"]: -e["amount"]}), fill_value=0.0)
        r = M.twr_from_snapshots(df, flows)
        twr, twr_reason = M.guarded_twr(r)
        cdi = cdi_daily(s, df.index[0])
        cdi_acc = accumulated(cdi, df.index[0], df.index[-1]) if not cdi.empty else None
        pct_cdi, pct_reason = M.pct_of_cdi(twr, cdi_acc, (df.index[-1] - df.index[0]).days)
        out.update(twr=twr, twr_reason=twr_reason, cdi=cdi_acc, pct_cdi=pct_cdi, pct_cdi_reason=pct_reason,
                   ipca=ipca_accumulated(s, df.index[0], df.index[-1]),
                   series=[{"date": d.isoformat(), "value": float(v)} for d, v in df.items()])
        cfs = [(d, -float(v)) for d, v in flows[(flows.index > df.index[0]) & (flows.index <= df.index[-1])].items()]
        cfs = [(df.index[0], -float(df.iloc[0]))] + cfs + [(df.index[-1], float(df.iloc[-1]))]
        out["xirr"] = M.xirr(cfs) if twr is not None else None
    return _clean(out)


def reconstruct_history(s: Session, days: int = 400) -> pd.Series:
    """Valor total investido reconstruído para trás (INFERIDO): V_{t−1} = (V_t − F_t) / (1 + r_t),
    com r_t do proxy da carteira atual e F_t os aportes líquidos do ledger. Usado só onde não há snapshot."""
    pos = positions(s)
    if not pos:
        return pd.Series(dtype=float)
    start = today_brt() - timedelta(days=days)
    rets = asset_returns(s, pos, start)
    if rets.empty:
        return pd.Series(dtype=float)
    w = pd.Series({p["id"]: p["balance"] for p in pos if p["id"] in rets.columns}, dtype=float)
    port = (rets[w.index] * (w / w.sum())).sum(axis=1)
    ev = s.execute(select(FinancialEvent.competence_date, FinancialEvent.amount)
                   .where(FinancialEvent.event_type.in_(["INVESTMENT_CONTRIBUTION", "INVESTMENT_REDEMPTION"]),
                          FinancialEvent.is_removed.is_(False), FinancialEvent.competence_date >= start)).all()
    flows: dict[date, float] = defaultdict(float)
    for d, amt in ev:
        flows[d] += -amt
    value = sum(p["balance"] for p in pos)
    out = {today_brt(): value}
    cal = pd.date_range(start, today_brt(), freq="D").date[::-1]
    for i in range(len(cal) - 1):
        d, prev = cal[i], cal[i + 1]
        r = float(port.get(d, 0.0)) if d in port.index else 0.0
        value = max(0.0, (value - flows.get(d, 0.0)) / (1 + r))
        out[prev] = value
    return pd.Series(out).sort_index()


def portfolio_reviews(s: Session) -> list[ReviewCandidate]:
    out: list[ReviewCandidate] = []
    pos = positions(s)
    for g in fgc_exposure(pos):
        if g["excess"] > 0:
            out.append(ReviewCandidate(f"fgc:{g['issuer']}", "fgc_limit", "high", "issuer", None,
                                       f"Exposição a {g['issuer']} de {fmt_brl(g['value'])} acima do limite FGC",
                                       f"Excede {fmt_brl(g['excess'])} do limite de {fmt_brl(g['limit'])} por instituição."))
    from app.portfolio.transit import exit_reviews
    out += exit_reviews(s)
    recent = today_brt() - timedelta(days=10)
    have = {sym for (sym,) in s.execute(select(AssetPrice.symbol).where(AssetPrice.date >= recent).distinct())}
    any_prices = bool(s.scalar(select(AssetPrice.symbol).limit(1)))
    if any_prices:
        for p in pos:
            if p["yahoo_symbol"] and p["yahoo_symbol"] not in have:
                out.append(ReviewCandidate(f"price:{p['yahoo_symbol']}", "missing_price", "info", "investment", p["id"],
                                           f"Sem cotação recente para {p['yahoo_symbol']}",
                                           "Confira o ticker em Configurações → Ativos."))
    return out


def investment_movements(s: Session, limit: int = 300) -> list[dict]:
    rows = s.execute(select(InvestmentTransaction, Investment.name, Investment.code)
                     .join(Investment, Investment.id == InvestmentTransaction.investment_id)
                     .order_by(InvestmentTransaction.date.desc()).limit(limit)).all()
    return [{"date": t.date, "type": t.type, "movement_type": t.movement_type, "amount": t.amount,
             "net_amount": t.net_amount, "quantity": t.quantity, "value": t.value, "name": name, "code": code,
             "description": t.description} for t, name, code in rows]


def _clean(d):
    if isinstance(d, dict):
        return {k: _clean(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_clean(v) for v in d]
    if isinstance(d, (np.floating, float)):
        return None if (d is None or math.isnan(d) or math.isinf(d)) else float(d)
    if isinstance(d, (np.integer,)):
        return int(d)
    if isinstance(d, pd.Timestamp):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    return d
