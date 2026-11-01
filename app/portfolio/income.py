"""Proventos e renda passiva.

- Recebidos: créditos de proventos no razão (INVESTMENT_INCOME), com ticker, tipo e quantidade lidos da descrição
  ("Crédito Evento B3 - * Prov * Dividendos 18 Pssa3").
- Informados pela fonte de cotações: valor por cota por data-com (`asset_events`), multiplicado pela quantidade
  que você tinha na véspera. ETF que reinveste não distribui e aparece assim.
- Renda fixa: rendimento bruto estimado do próximo mês pelo indexador de cada título.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AssetEvent, FinancialEvent
from app.portfolio.market import cdi_daily
from app.utils.time import month_add, month_key, today_brt

PROV_RE = re.compile(r"(dividend|juros s/?\s*c|jcp|rendiment|amortiza|provento|evento b3|\bprov\b)", re.I)
NOT_PROV_RE = re.compile(r"(cashback|reembolso|rendimento (da|de) (conta|caixinha|saldo))", re.I)
TICKER_RE = re.compile(r"\b([A-Za-z]{4}\d{1,2})\b")
QTY_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s+([A-Za-z]{4}\d{1,2})\s*$")
KINDS = [("juros s", "JCP"), ("jcp", "JCP"), ("dividend", "Dividendos"), ("rendiment", "Rendimentos"),
         ("amortiza", "Amortização")]
RV_CLASSES = {"Ações BR", "ETF Ações BR", "FIIs", "ETF Internacional", "ETF Renda Fixa", "Cripto"}


def parse_provento(description: str | None) -> dict | None:
    d = description or ""
    if NOT_PROV_RE.search(d) or not PROV_RE.search(d):
        return None
    tickers = [t.upper() for t in TICKER_RE.findall(d)]
    low = d.lower()
    kind = next((k for key, k in KINDS if key in low), "Provento")
    qty = None
    m = QTY_RE.search(d.strip())
    if m:
        try:
            qty = float(m.group(1).replace(",", "."))
        except ValueError:
            qty = None
    return {"ticker": tickers[-1] if tickers else None, "tipo": kind, "quantidade": qty}


def received(s: Session, months: int = 24) -> list[dict]:
    since = date.fromisoformat(month_add(month_key(today_brt()), -months) + "-01")
    out = []
    for e in s.scalars(select(FinancialEvent).where(
            FinancialEvent.is_removed.is_(False), FinancialEvent.event_type == "INVESTMENT_INCOME",
            FinancialEvent.competence_date >= since, FinancialEvent.amount > 0)
            .order_by(FinancialEvent.competence_date.desc())):
        p = parse_provento(e.description)
        if not p:
            continue
        out.append({"data": e.competence_date, "valor": round(e.amount, 2), "descricao": e.description, **p})
    return out


def income_report(s: Session) -> dict:
    from app.portfolio.service import positions
    today = today_brt()
    pos = positions(s)
    rec = received(s, 24)
    y_ago = today - timedelta(days=365)
    months = [month_add(month_key(today), -i) for i in range(11, -1, -1)]

    by_month: dict[str, dict] = {m: defaultdict(float) for m in months}
    by_ticker: dict[str, dict] = defaultdict(lambda: {"recebido_12m": 0.0, "recebido_24m": 0.0, "pagamentos": 0,
                                                     "ultimo": None, "tipos": set()})
    for r in rec:
        t = r["ticker"] or "Outros"
        mk = month_key(r["data"])
        if mk in by_month:
            by_month[mk][t] += r["valor"]
        b = by_ticker[t]
        b["recebido_24m"] += r["valor"]
        if r["data"] >= y_ago:
            b["recebido_12m"] += r["valor"]
            b["pagamentos"] += 1
        b["ultimo"] = max(b["ultimo"], r["data"]) if b["ultimo"] else r["data"]
        b["tipos"].add(r["tipo"])

    # posições de renda variável e o que a fonte informa por cota
    held = {}
    for p in pos:
        if p["asset_class"] in RV_CLASSES and p.get("code"):
            k = p["code"].upper()
            h = held.setdefault(k, {"saldo": 0.0, "quantidade": 0.0, "simbolo": p.get("yahoo_symbol"),
                                    "classe": p["asset_class"], "preco": p.get("unit_price"), "custo": 0.0,
                                    "custo_conhecido": True})
            h["saldo"] += p["balance"]
            h["quantidade"] += p.get("quantity") or 0.0
            if p.get("cost"):
                h["custo"] += p["cost"]
            else:
                h["custo_conhecido"] = False
    try:
        from app.portfolio.realized import equity_lots
        for a in equity_lots(s)["ativos"]:
            k = (a["ativo"] or "").upper()
            if k in held and a.get("custo_completo") and a.get("custo_conhecido"):
                held[k]["custo"], held[k]["custo_conhecido"] = a["custo_conhecido"], True
    except Exception:  # noqa: BLE001
        pass
    symbols = {h["simbolo"]: k for k, h in held.items() if h["simbolo"]}
    events: dict[str, list] = defaultdict(list)
    if symbols:
        for ev in s.scalars(select(AssetEvent).where(AssetEvent.symbol.in_(list(symbols)), AssetEvent.kind == "div",
                                                     AssetEvent.date >= today - timedelta(days=400))):
            events[symbols[ev.symbol]].append(ev)

    rows = []
    for k in sorted(set(held) | set(by_ticker)):
        h = held.get(k)
        b = by_ticker.get(k, {"recebido_12m": 0.0, "recebido_24m": 0.0, "pagamentos": 0, "ultimo": None, "tipos": set()})
        evs = sorted(events.get(k, []), key=lambda e: e.date)
        dps_12m = sum(e.value for e in evs if y_ago < e.date <= today)
        upcoming = [e for e in evs if e.date > today]
        row = {
            "ativo": k, "na_carteira": h is not None, "classe": h["classe"] if h else None,
            "saldo": round(h["saldo"], 2) if h else None, "quantidade": h["quantidade"] if h else None,
            "recebido_12m": round(b["recebido_12m"], 2), "recebido_24m": round(b["recebido_24m"], 2),
            "pagamentos_12m": b["pagamentos"], "ultimo_pagamento": b["ultimo"], "tipos": sorted(b["tipos"]),
            "dy_12m": (b["recebido_12m"] / h["saldo"]) if h and h["saldo"] > 0 and b["recebido_12m"] else None,
            "yoc_12m": (b["recebido_12m"] / h["custo"]) if h and h["custo_conhecido"] and h["custo"] > 0
            and b["recebido_12m"] else None,
            "por_cota_12m_fonte": round(dps_12m, 6) if evs else None,
            "dy_12m_fonte": (dps_12m / h["preco"]) if h and h.get("preco") and evs else None,
            "estimado_12m_fonte": round(dps_12m * h["quantidade"], 2) if h and evs else None,
            "proximos": [{"data_com": e.date, "por_cota": e.value,
                          "estimado": round(e.value * (h["quantidade"] if h else 0), 2)} for e in upcoming],
            "distribui": bool(evs) or b["recebido_24m"] > 0,
        }
        if h and not row["distribui"] and h["classe"] in ("ETF Ações BR", "ETF Internacional", "ETF Renda Fixa"):
            row["observacao"] = "ETF que reinveste os proventos na cota (o ganho aparece no preço)"
        elif not h:
            row["observacao"] = "provento de ativo que não está na carteira conectada (outra corretora ou já vendido)"
        rows.append(row)
    rows.sort(key=lambda r: (-(r["recebido_12m"] or 0), -(r["saldo"] or 0)))

    # renda fixa: rendimento bruto estimado para os próximos 30 dias pelo indexador
    cdi = cdi_daily(s, today - timedelta(days=45))
    cdi_month = float((1 + cdi.tail(21)).prod() - 1) if len(cdi) else None
    rf_month = 0.0
    rf_rows = []
    for p in pos:
        if p["asset_class"] in RV_CLASSES:
            continue
        val = p.get("gross") or p["balance"]
        if p["indexer"] == "CDI" and cdi_month is not None:
            k = (p["rate"] / 100.0) if p.get("rate") and p["rate"] > 10 else 1.0
            r = cdi_month * k
        elif p["indexer"] == "SELIC" and cdi_month is not None:
            r = cdi_month
        elif p.get("fixed_rate"):
            r = (1 + p["fixed_rate"] / 100.0) ** (1 / 12) - 1
        elif p.get("last_12m_rate"):
            r = (1 + p["last_12m_rate"] / 100.0) ** (1 / 12) - 1
        else:
            continue
        rf_month += val * r
        rf_rows.append({"ativo": p["code"] or p["name"], "valor": round(val, 2), "taxa_mes": r,
                        "rendimento_mes": round(val * r, 2)})
    prov_12m = sum(r["recebido_12m"] for r in rows)
    return {
        "por_mes": [{"mes": mk, "total": round(sum(v.values()), 2), "por_ativo": {k: round(x, 2) for k, x in v.items()}}
                    for mk, v in by_month.items()],
        "por_ativo": rows, "recebidos": rec[:60],
        "total_12m": round(prov_12m, 2), "media_mensal_12m": round(prov_12m / 12, 2),
        "renda_fixa_mes_estimada": round(rf_month, 2), "renda_fixa_titulos": sorted(rf_rows, key=lambda x: -x["rendimento_mes"]),
        "renda_passiva_mes_estimada": round(rf_month + prov_12m / 12, 2),
        "cdi_mes": cdi_month,
        "nota": "Recebidos = créditos de proventos no seu extrato. 'Fonte' = valor por cota informado pela fonte de "
                "cotações × sua quantidade (estimativa; o crédito real pode vir líquido de IR, como no JCP). "
                "Renda fixa = rendimento bruto dos próximos 30 dias pelo CDI atual e pela taxa de cada título.",
    }
