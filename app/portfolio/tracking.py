"""Acompanhamento da carteira: série diária por investimento, performance por período e por grupo (instituição,
classe, ativo), comparação com referências e evolução do patrimônio investido.

O cálculo está em `tracking_core` (biblioteca padrão). Aqui ficam a leitura do banco e a montagem do relatório.
Tudo é bruto de IR/IOF; proventos entram no retorno porque a cotação usada é a ajustada (retorno total).
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (Account, AccountSetting, Asset, AssetPrice, FinancialEvent, Institution, Investment,
                        InvestmentBalance, InvestmentTransaction, Item, MarketSeries)
from app.portfolio import tracking_core as T
from app.portfolio.classification import ETF_RF_INDEXER
from app.portfolio.realized import RV_TEXT, _is_rv
from app.utils.time import today_brt

MAX_YEARS = 3
PERIODS = [("mes", "No mês"), ("3m", "3 meses"), ("6m", "6 meses"), ("ano", "No ano"), ("12m", "12 meses"),
           ("inicio", "Desde o início")]
# ETF de renda fixa com cotação defeituosa recua pelo indexador de referência (sem marcação a mercado)
RF_ETF_FALLBACK = {"IPCA": ("IPCA", 6.5), "PRE": ("PRE", 12.0), "SELIC": ("SELIC", None), "CDI": ("CDI", 100.0)}
BENCH_PRICES = [("Ibovespa", ["BOVA11.SA", "^BVSP"]), ("S&P 500 em BRL", ["IVVB11.SA"]), ("IMA-B", ["IMAB11.SA"])]
KNOWN_INSTITUTIONS = [("nubank", "Nubank"), ("nu pagamentos", "Nubank"), ("nu financeira", "Nubank"),
                      ("nu invest", "Nubank"), ("banco inter", "Inter"), ("inter ", "Inter"), ("itau", "Itaú"),
                      ("bradesco", "Bradesco"), ("santander", "Santander"), ("btg", "BTG Pactual"),
                      ("xp invest", "XP"), ("rico ", "Rico"), ("clear ", "Clear"), ("c6 ", "C6 Bank"),
                      ("banco do brasil", "Banco do Brasil"), ("caixa economica", "Caixa"), ("picpay", "PicPay"),
                      ("mercado pago", "Mercado Pago"), ("sicoob", "Sicoob"), ("sicredi", "Sicredi"),
                      ("pagbank", "PagBank"), ("avenue", "Avenue"), ("toro ", "Toro"), ("genial", "Genial"),
                      ("orama", "Órama"), ("modal", "Modal")]


# ------------------------------------------------------------------ rótulos
def institution_labels(s: Session) -> dict[str, str]:
    """Nome legível de cada conexão: apelido da conexão > prefixo do apelido das contas ("Nubank · Conta") >
    nome das contas reconhecido > nome do conector (que no MeuPluggy é sempre "MeuPluggy")."""
    from app.categorization.text import norm
    insts = {i.id: i.name for i in s.scalars(select(Institution))}
    nick = {x.account_id: x.nickname for x in s.scalars(select(AccountSetting)) if x.nickname}
    accs: dict[str, list[Account]] = defaultdict(list)
    for a in s.scalars(select(Account)):
        accs[a.item_id].append(a)
    out = {}
    for it in s.scalars(select(Item)):
        label = it.nickname
        if not label:
            pref = [nick[a.id].split(" · ")[0].strip() for a in accs[it.id] if a.id in nick and " · " in nick[a.id]]
            if pref:
                label = max(set(pref), key=pref.count)
        if not label:
            text = " " + " ".join(norm(f"{a.name or ''} {a.marketing_name or ''}") for a in accs[it.id]) + " "
            label = next((lab for k, lab in KNOWN_INSTITUTIONS if k in text), None)
        out[it.id] = label or insts.get(it.institution_id) or it.id[:8]
    return out


def holding_label(inv: Investment) -> str:
    code = (inv.code or "").strip()
    if code and len(code) <= 7:
        return code
    name = (inv.name or "").strip()
    if (inv.subtype or "").upper() == "TREASURY" or name.lower().startswith("tesouro"):
        return name
    issuer = (inv.issuer or name).split(" - ")[0].strip().title().replace(" S.A.", "").replace(" S.a.", "")
    kind = (inv.subtype or inv.type or "").upper().replace("_", " ")
    rate = ""
    if (inv.rate_type or "").upper() in ("CDI", "DI") and inv.rate:
        rate = f" {inv.rate:g}% CDI"
    elif inv.fixed_annual_rate:
        rate = f" {inv.fixed_annual_rate:g}% a.a."
    due = f" · vence {inv.due_date:%m/%Y}" if inv.due_date else ""
    return f"{kind} {issuer}{rate}{due}".strip()


# ------------------------------------------------------------------ carga
def _months_back(d: date, k: int) -> date:
    y, m = d.year, d.month - k
    while m <= 0:
        m += 12
        y -= 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


def load(s: Session, years: int = MAX_YEARS) -> dict | None:
    today = today_brt()
    invs = list(s.scalars(select(Investment).where(Investment.removed_at.is_(None))))
    if not invs:
        return None
    assets = {a.id: a for a in s.scalars(select(Asset))}
    labels = institution_labels(s)
    txs: dict[str, list[InvestmentTransaction]] = defaultdict(list)
    for t in s.scalars(select(InvestmentTransaction).where(InvestmentTransaction.removed_at.is_(None))):
        if t.date:
            txs[t.investment_id].append(t)
    snaps: dict[str, list[InvestmentBalance]] = defaultdict(list)
    for b in s.scalars(select(InvestmentBalance)):
        snaps[b.investment_id].append(b)
    dates = [t.date for v in txs.values() for t in v] + [b.date for v in snaps.values() for b in v]
    start = min(dates) if dates else today
    start = max(start, today - timedelta(days=365 * years))
    snap_dates = [b.date for v in snaps.values() for b in v]
    end = min(max(max(snap_dates) if snap_dates else today, start + timedelta(days=1)), today)
    days = T.day_range(start, end)

    m = T.Market()
    for code, d, val in s.execute(select(MarketSeries.code, MarketSeries.date, MarketSeries.value)
                                  .where(MarketSeries.date >= start - timedelta(days=40))):
        if code == "CDI":
            m.cdi[d] = val / 100.0
        elif code == "SELIC":
            m.selic[d] = val / 100.0
        elif code == "IPCA":
            m.ipca[(d.year, d.month)] = val / 100.0
    symbols = {a.yahoo_symbol for a in assets.values() if a.yahoo_symbol}
    for _, syms in BENCH_PRICES:
        symbols.update(syms)
    for sym, d, close in s.execute(select(AssetPrice.symbol, AssetPrice.date, AssetPrice.close)
                                   .where(AssetPrice.symbol.in_(sorted(symbols)),
                                          AssetPrice.date >= start - timedelta(days=30))):
        if close and close > 0:
            m.prices.setdefault(sym, {})[d] = float(close)
    quality = {}
    for sym, px in m.prices.items():
        m.clean_from[sym], quality[sym] = T.price_quality(px, start)

    # débito/crédito bancário de renda variável: valor que de fato saiu/entrou da conta numa negociação
    rv_cash = [e for e in s.scalars(select(FinancialEvent).where(
        FinancialEvent.is_removed.is_(False),
        FinancialEvent.event_type.in_(["INVESTMENT_CONTRIBUTION", "INVESTMENT_REDEMPTION"]),
        FinancialEvent.competence_date >= start - timedelta(days=5)))
        if any(k in (e.description or "").lower() for k in RV_TEXT)]
    used_cash: set = set()

    transit: dict[str, date] = {}
    try:
        from app.portfolio.transit import detect_exits
        for e in detect_exits(s):
            if e["state"] in ("pending", "custody_transferred", "provider_error"):
                transit[e["investment_id"]] = e["date"]
    except Exception:  # noqa: BLE001 — sem snapshots suficientes
        pass

    holdings: list[T.Holding] = []
    meta: dict[str, dict] = {}
    for inv in invs:
        a = assets.get(inv.asset_id)
        rv = _is_rv(inv) or bool(a and a.indexer == "VAR")
        cls = a.asset_class if a else "Outros"
        indexer = (a.indexer if a else None) or ""
        index = "PRICE" if rv else {"CDI": "CDI", "SELIC": "SELIC", "IPCA": "IPCA", "PRE": "PRE"}.get(indexer, "FLAT")
        if index == "CDI":
            rate = inv.rate
        elif index in ("PRE", "IPCA"):
            rate = inv.fixed_annual_rate or inv.annual_rate
        else:
            rate = None
        label = holding_label(inv)
        h = T.Holding(inv.id, label, T.RV if rv else T.RF, index, rate, a.yahoo_symbol if a else None,
                      {"instituicao": labels.get(inv.item_id, "—"), "classe": cls, "ativo": label})
        if rv and cls == "ETF Renda Fixa":
            ref = ETF_RF_INDEXER.get((inv.code or "").upper(), "IPCA")
            h.fallback_index, h.fallback_rate = RF_ETF_FALLBACK.get(ref, ("IPCA", 6.5))
        for b in snaps.get(inv.id, []):
            val = b.amount if b.amount is not None else b.balance
            if val is not None:
                h.obs[b.date] = float(val)
            if rv and b.quantity is not None:
                h.qty_obs[b.date] = float(b.quantity)
        for t in txs.get(inv.id, []):
            typ = (t.type or "").upper()
            if typ not in ("BUY", "SELL"):
                continue
            sign = 1 if typ == "BUY" else -1
            amt = abs(t.amount if t.amount is not None else (t.net_amount or 0.0)) or abs((t.quantity or 0) * (t.value or 0))
            src = "pluggy"
            if rv:  # usa o valor do débito/crédito em conta quando bate (inclui custos da negociação)
                for e in rv_cash:
                    if e.source_id in used_cash or (e.amount < 0) != (sign > 0):
                        continue
                    if t.date <= e.competence_date <= t.date + timedelta(days=3) and amt and \
                            abs(abs(e.amount) - amt) / amt <= 0.03:
                        used_cash.add(e.source_id)
                        amt, src = abs(e.amount), "banco"
                        break
            h.trades.append(T.Trade(t.date, sign * amt, sign * abs(t.quantity or 0.0) if rv else 0.0, src))
        h.current_value = float((inv.amount if inv.amount is not None else inv.balance) or 0.0)
        h.current_qty = inv.quantity
        h.closed = (inv.status or "") == "TOTAL_WITHDRAWAL" or (inv.balance or 0.0) <= 0.005
        h.transit_since = transit.get(inv.id)
        holdings.append(h)
        meta[inv.id] = {"classe": cls, "instituicao": h.groups["instituicao"], "rotulo": label,
                        "ativo_id": inv.asset_id, "codigo": inv.code}
    first_snap = min(snap_dates) if snap_dates else None
    return {"days": days, "market": m, "holdings": holdings, "meta": meta, "quality": quality,
            "first_snapshot": first_snap}


# ------------------------------------------------------------------ relatório
def _period_index(days: list[date], key: str) -> tuple[int, bool]:
    end = days[-1]
    if key == "mes":
        d = end.replace(day=1) - timedelta(days=1)
    elif key == "3m":
        d = _months_back(end, 3)
    elif key == "6m":
        d = _months_back(end, 6)
    elif key == "ano":
        d = date(end.year - 1, 12, 31)
    elif key == "12m":
        d = _months_back(end, 12)
    else:
        return 0, False
    i = (d - days[0]).days
    return max(0, i), i < 0  # (índice, janela menor que o período)


def _num(x):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(x, 6) if isinstance(x, float) else x


def performance_report(s: Session, years: int = MAX_YEARS) -> dict:
    data = load(s, years)
    if not data:
        return {"available": False, "reason": "sem investimentos"}
    days, m, holdings, meta = data["days"], data["market"], data["holdings"], data["meta"]
    n = len(days)
    if n < 2:
        return {"available": False, "reason": "histórico de um dia só"}
    cache: dict = {}
    series = {h.id: T.build_series(h, days, m, cache) for h in holdings}
    snap0 = data["first_snapshot"]
    snap_idx = (snap0 - days[0]).days if snap0 and snap0 >= days[0] else 0

    cdi = T.dense_rate(m.cdi, days)
    ipca = T.dense_ipca(m.ipca, days)
    bench_px = {}
    for label, syms in BENCH_PRICES:
        for sym in syms:
            if sym in m.prices and m.clean_from.get(sym) is not None:
                bench_px[(label if sym != "^BVSP" else "Ibovespa (só preço)", sym)] = T.dense_price(m.prices[sym], days)
                break

    periods = []
    for key, label in PERIODS:
        i0, short = _period_index(days, key)
        periods.append({"key": key, "label": label, "i0": i0, "inicio": days[i0].isoformat(),
                        "janela_menor": short})

    def bench_for(i0: int) -> dict:
        out = {"CDI": _num(T.accumulated(cdi, i0, n - 1)), "IPCA": _num(T.accumulated(ipca, i0, n - 1))}
        for (label, sym), px in bench_px.items():
            cf = m.clean_from.get(sym)
            if cf and cf > days[i0]:
                out[label] = None  # cotação sem qualidade no começo do período
            else:
                out[label] = _num(T.price_return(px, i0, n - 1))
        return out

    def group_rows(dim: str | None) -> list[dict]:
        groups: dict[str, list] = defaultdict(list)
        for h in holdings:
            key = "Carteira" if dim is None else h.groups.get(dim, "—")
            groups[key].append(h)
        total_now = sum(series[h.id].v[-1] for h in holdings) or 1.0
        rows = []
        for key, members in groups.items():
            V, F = T.aggregate([series[h.id] for h in members], n)
            row = {"nome": key, "valor": round(V[-1], 2), "peso": V[-1] / total_now if total_now else 0.0,
                   "ativo": V[-1] > 0.005, "posicoes": sum(1 for h in members if series[h.id].v[-1] > 0.005),
                   "periodos": {}}
            for p in periods:
                st = T.period_stats(days, V, F, p["i0"], n - 1, snap_idx)
                cdi_p = T.accumulated(cdi, (date.fromisoformat(st["inicio"]) - days[0]).days, n - 1) \
                    if st.get("inicio") else None
                span = (days[-1] - date.fromisoformat(st["inicio"])).days if st.get("inicio") else 0
                held = sum(1 for i in range(p["i0"] + 1, n) if V[i - 1] > 0.01)
                st.update(pct_cdi=T.pct_of_cdi(st.get("twr"), cdi_p, span), dias_com_posicao=held,
                          dias=n - 1 - p["i0"])
                row["periodos"][p["key"]] = {k: _num(v) for k, v in st.items()}
            rows.append(row)
        rows.sort(key=lambda r: (-r["valor"], r["nome"]))
        return rows

    # por ativo: posições abertas uma a uma; encerradas somadas por classe
    asset_rows = []
    closed_by_class: dict[str, list] = defaultdict(list)
    open_h = [h for h in holdings if series[h.id].v[-1] > 0.005]
    for h in holdings:
        if series[h.id].v[-1] <= 0.005 and series[h.id].start is not None:
            closed_by_class[h.groups["classe"]].append(h)
    total_now = sum(series[h.id].v[-1] for h in holdings) or 1.0
    for label, members, extra in ([(h.label, [h], {"classe": h.groups["classe"], "instituicao": h.groups["instituicao"],
                                                   "id": h.id}) for h in open_h] +
                                  [(f"Encerrados · {c}", hs, {"classe": c, "encerrados": len(hs)})
                                   for c, hs in closed_by_class.items()]):
        V, F = T.aggregate([series[h.id] for h in members], n)
        row = {"nome": label, "valor": round(V[-1], 2), "peso": V[-1] / total_now, **extra, "periodos": {},
               "notas": sorted({x for h in members for x in series[h.id].notes})}
        for p in periods:
            st = T.period_stats(days, V, F, p["i0"], n - 1, snap_idx)
            if st.get("inicio"):
                i_eff = (date.fromisoformat(st["inicio"]) - days[0]).days
                st["pct_cdi"] = T.pct_of_cdi(st.get("twr"), T.accumulated(cdi, i_eff, n - 1), n - 1 - i_eff)
            row["periodos"][p["key"]] = {k: _num(v) for k, v in st.items()}
        asset_rows.append(row)
    asset_rows.sort(key=lambda r: (r.get("encerrados") is not None, -r["valor"]))

    # curva acumulada da carteira × referências (desde o início da janela)
    V, F = T.aggregate(list(series.values()), n)
    curve, g = [], 1.0
    cum_cdi = cum_ipca = 1.0
    step = max(1, n // 200)
    first_bench = {k: next((x for x in px if x is not None), None) for k, px in bench_px.items()}
    for i in range(n):
        if i and V[i - 1] > 0.01:
            g *= (V[i] - F[i]) / V[i - 1]
        if i:
            cum_cdi *= 1 + cdi[i]
            cum_ipca *= 1 + ipca[i]
        if i % step == 0 or i == n - 1:
            row = {"date": days[i].isoformat(), "Carteira": round((g - 1) * 100, 3),
                   "CDI": round((cum_cdi - 1) * 100, 3), "IPCA": round((cum_ipca - 1) * 100, 3),
                   "reconstruido": i < snap_idx}
            for (label, sym), px in bench_px.items():
                cf = m.clean_from.get(sym)
                if px[i] is not None and first_bench[(label, sym)] and not (cf and cf > days[0]):
                    row[label] = round((px[i] / first_bench[(label, sym)] - 1) * 100, 3)
            curve.append(row)

    # evolução do valor por classe (fim de mês + último dia)
    by_class: dict[str, list] = defaultdict(list)
    for h in holdings:
        by_class[h.groups["classe"]].append(series[h.id])
    class_v = {c: T.aggregate(ss, n)[0] for c, ss in by_class.items()}
    evol = []
    for i, d in enumerate(days):
        if i == n - 1 or (d + timedelta(days=1)).day == 1:
            evol.append({"date": d.isoformat(), "reconstruido": i < snap_idx,
                         **{c: round(v[i], 2) for c, v in class_v.items() if abs(v[i]) > 0.005}})

    inferred = []
    notes = set()
    for h in holdings:
        s_ = series[h.id]
        for d, val, why in s_.inferred_flows:
            inferred.append({"data": d.isoformat(), "ativo": h.label, "valor": val, "motivo": why})
        for x in s_.notes:
            if "já existia" not in x:
                notes.add(f"{h.label}: {x}")
    for sym, issues in data["quality"].items():
        if issues and m.clean_from.get(sym) != days[0]:
            notes.add(f"Cotação de {sym} com defeitos na fonte ({'; '.join(issues[:2])}); "
                      f"usada só a partir de {m.clean_from[sym].isoformat() if m.clean_from.get(sym) else 'nunca'}.")
    return {
        "available": True, "inicio": days[0].isoformat(), "fim": days[-1].isoformat(),
        "snapshots_desde": snap0.isoformat() if snap0 else None,
        "periodos": [{k: p[k] for k in ("key", "label", "inicio", "janela_menor")} for p in periods],
        "referencias": {p["key"]: bench_for(p["i0"]) for p in periods},
        "total": group_rows(None)[0],
        "por_instituicao": group_rows("instituicao"), "por_classe": group_rows("classe"), "por_ativo": asset_rows,
        "curva": curve, "evolucao": evol, "aportes": flow_evolution(days, V, F, snap_idx),
        "fluxos_inferidos": sorted(inferred, key=lambda x: x["data"], reverse=True)[:40],
        "notas": sorted(notes),
        "premissas": [
            "Retorno ponderado no tempo (TWR) sobre o valor bruto de IR/IOF: aportes e resgates não contam como ganho.",
            "Antes do primeiro saldo coletado o valor é reconstruído: renda variável = quantidade × fechamento "
            "(com proventos reinvestidos na cotação ajustada); renda fixa = recuo pelo indexador e pelas "
            "movimentações do próprio título. Esses trechos aparecem como reconstruídos.",
            "Variação entre dois saldos que o indexador não explica, ou mudança de quantidade sem negociação, "
            "vira fluxo inferido (listado abaixo), nunca ganho ou perda.",
            "A janela começa na movimentação mais antiga que a Pluggy entrega (cerca de 12 meses).",
        ],
    }


def flow_evolution(days: list[date], V: list[float], F: list[float], snap_idx: int = 0) -> list[dict]:
    """Fim de cada mês: valor, saldo de partida, aportes líquidos acumulados e rendimento acumulado
    (valor − partida − aportes), mais o aporte e o rendimento do próprio mês."""
    out, cum, prev_v, month_flow = [], 0.0, V[0] if V else 0.0, 0.0
    n = len(days)
    for i, d in enumerate(days):
        if i:
            cum += F[i]
            month_flow += F[i]
        if i == n - 1 or (d + timedelta(days=1)).day == 1:
            out.append({"date": d.isoformat(), "valor": round(V[i], 2), "partida": round(V[0], 2),
                        "aportes_acumulados": round(cum, 2), "rendimento_acumulado": round(V[i] - V[0] - cum, 2),
                        "aporte_mes": round(month_flow, 2), "rendimento_mes": round(V[i] - prev_v - month_flow, 2),
                        "parcial": i == n - 1 and (d + timedelta(days=1)).day != 1, "reconstruido": i < snap_idx})
            prev_v, month_flow = V[i], 0.0
    return out


def holding_detail(s: Session, hid: str, years: int = MAX_YEARS) -> dict:
    """Página de um ativo: valor no tempo, aportes × rendimento, retorno por período, movimentações,
    cotação, proventos e lotes (renda variável)."""
    data = load(s, years)
    if not data:
        return {"available": False, "reason": "sem investimentos"}
    days, m, meta = data["days"], data["market"], data["meta"]
    h = next((x for x in data["holdings"] if str(x.id) == str(hid)), None)
    if h is None:
        return {"available": False, "reason": "ativo não encontrado"}
    n = len(days)
    ser = T.build_series(h, days, m, {})
    V = [x or 0.0 for x in ser.v]
    F = [x or 0.0 for x in ser.f]
    snap0 = data["first_snapshot"]
    snap_idx = (snap0 - days[0]).days if snap0 and snap0 >= days[0] else 0
    recon_until = max(snap_idx, ser.inferred_until or 0)
    cdi = T.dense_rate(m.cdi, days)

    periods = []
    for key, label in PERIODS:
        i0, short = _period_index(days, key)
        st = T.period_stats(days, V, F, i0, n - 1, recon_until)
        if st.get("inicio"):
            i_eff = (date.fromisoformat(st["inicio"]) - days[0]).days
            st["pct_cdi"] = T.pct_of_cdi(st.get("twr"), T.accumulated(cdi, i_eff, n - 1), n - 1 - i_eff)
            st["cdi"] = T.accumulated(cdi, i_eff, n - 1)
        periods.append({"key": key, "label": label, "janela_menor": short, **{k: _num(v) for k, v in st.items()}})

    first = ser.start if ser.start is not None else 0
    step = max(1, (n - first) // 240)
    curve = [{"date": days[i].isoformat(), "valor": round(V[i], 2), "reconstruido": i < recon_until}
             for i in range(first, n) if (i - first) % step == 0 or i == n - 1]
    price = []
    if h.symbol and h.symbol in m.prices:
        px = T.dense_price(m.prices[h.symbol], days)
        price = [{"date": days[i].isoformat(), "close": round(px[i], 4)}
                 for i in range(first, n) if px[i] is not None and ((i - first) % step == 0 or i == n - 1)]

    flows = [{"data": t.d.isoformat(), "valor": round(t.flow, 2), "quantidade": round(t.dq, 6) if t.dq else None,
              "origem": t.source} for t in sorted(h.trades, key=lambda t: t.d, reverse=True)]
    inferred = [{"data": d.isoformat(), "valor": round(v, 2), "motivo": why} for d, v, why in ser.inferred_flows]

    from app.portfolio.service import positions
    pos = next((p for p in positions(s) if str(p["id"]) == str(hid)), None)
    code = (pos or {}).get("code") or ""
    income, lots = [], None
    if h.kind == T.RV and code:
        from app.portfolio.income import received
        from app.portfolio.realized import equity_lots
        income = [{**r, "data": r["data"].isoformat() if hasattr(r["data"], "isoformat") else r["data"]}
                  for r in received(s, 36) if (r.get("ticker") or "").upper() == code.upper()]
        lots = next((x for x in equity_lots(s)["ativos"] if str(x.get("investment_id")) == str(hid)), None)

    return {
        "available": True, "id": h.id, "nome": h.label, "tipo": "Renda variável" if h.kind == T.RV else "Renda fixa",
        "indexador": h.index, "taxa": h.rate, "simbolo": h.symbol, "encerrado": V[-1] <= 0.005,
        **{k: meta.get(h.id, {}).get(k) for k in ("classe", "instituicao")},
        "posicao": P_clean(pos) if pos else None,
        "inicio": days[first].isoformat(), "fim": days[-1].isoformat(),
        "periodos": periods, "curva": curve, "cotacao": price,
        "aportes": flow_evolution(days[first:], V[first:], F[first:], max(0, recon_until - first)),
        "movimentacoes": flows, "fluxos_inferidos": inferred, "proventos": income, "lotes": lots,
        "notas": sorted(set(ser.notes)),
        "premissas": ["Retorno ponderado no tempo (TWR), bruto de IR/IOF.",
                      "Trechos antes do primeiro saldo coletado são reconstruídos e aparecem marcados."],
    }


def P_clean(d: dict) -> dict:
    from app.portfolio.service import _clean
    return _clean(d)
