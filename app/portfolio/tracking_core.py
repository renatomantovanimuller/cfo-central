"""Núcleo da série diária de valor por investimento e da performance por grupo e período.

Só biblioteca padrão, para poder ser testado e auditado isoladamente; `app.portfolio.tracking` busca os dados no
banco e chama estas funções.

Convenções
- Valor BRUTO (antes de IR/IOF), um ponto por dia corrido, no fim do dia.
- Fluxo F_d: + dinheiro que entra no investimento (aplicação/compra), − dinheiro que sai (resgate/venda/provento
  pago em conta). Retorno do dia: r_d = (V_d − F_d) / V_{d−1} − 1 (Dietz diário, fluxo no fim do dia).
  Encadeado dá o TWR; os mesmos fluxos dão a TIR e o ganho em R$.
- Antes do 1º snapshot o valor é RECONSTRUÍDO (marcado como inferido):
    renda variável: quantidade × fechamento, com a quantidade desfeita pelas negociações informadas;
    renda fixa: valor recuado pelo indexador do próprio título e pelos fluxos dele.
- Entre dois snapshots, a variação que o indexador não explica (renda fixa) ou a mudança de quantidade sem
  negociação (renda variável) vira FLUXO INFERIDO, nunca ganho ou perda.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from datetime import date, timedelta

RV, RF = "rv", "rf"


@dataclass
class Trade:
    d: date
    flow: float            # + entra no investimento, − sai
    dq: float = 0.0        # variação de quantidade (renda variável)
    source: str = "pluggy"


@dataclass
class Holding:
    id: str
    label: str
    kind: str                               # "rv" | "rf"
    index: str = "CDI"                      # CDI | SELIC | IPCA | PRE | FLAT | PRICE
    rate: float | None = None               # % do CDI (ou spread se ≤ 10); taxa fixa a.a. em % (PRE / IPCA+)
    symbol: str | None = None
    groups: dict = field(default_factory=dict)   # dimensão → rótulo (instituicao, classe, ativo…)
    obs: dict = field(default_factory=dict)      # date → valor bruto observado
    qty_obs: dict = field(default_factory=dict)  # date → quantidade observada
    trades: list = field(default_factory=list)
    current_value: float = 0.0
    current_qty: float | None = None
    closed: bool = False
    transit_since: date | None = None       # saiu sem contrapartida e segue no patrimônio "em trânsito"
    fallback_index: str | None = None       # renda variável sem cotação confiável: indexador usado para recuar
    fallback_rate: float | None = None


@dataclass
class Market:
    cdi: dict = field(default_factory=dict)      # date → taxa diária decimal
    selic: dict = field(default_factory=dict)
    ipca: dict = field(default_factory=dict)     # (ano, mês) → variação mensal decimal
    prices: dict = field(default_factory=dict)   # símbolo → {date: fechamento}
    dividends: dict = field(default_factory=dict)  # símbolo → {data-com: valor por cota} (só com preço não ajustado)
    clean_from: dict = field(default_factory=dict)  # símbolo → 1ª data com cotação confiável (ver price_quality)


@dataclass
class Series:
    id: str
    v: list
    f: list
    start: int | None = None          # 1º índice com valor (None = sem valor na janela)
    end: int = -1                     # último índice com valor conhecido
    inferred_until: int = 0           # dias com índice < isto são reconstruídos
    notes: list = field(default_factory=list)
    inferred_flows: list = field(default_factory=list)   # (data, valor, motivo)


# ------------------------------------------------------------------ calendário e taxas
def day_range(a: date, b: date) -> list[date]:
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


def dense_rate(series: dict, days: list[date]) -> list[float]:
    """Taxa diária por dia corrido: 0 em fim de semana e feriado (sem publicação). Depois da última publicação,
    repete a última taxa nos dias úteis (o BCB publica com 1–2 dias de atraso)."""
    if not series:
        return [0.0] * len(days)
    last_d = max(series)
    last_v = series[last_d]
    out = []
    for d in days:
        if d in series:
            out.append(series[d])
        elif d > last_d and d.weekday() < 5:
            out.append(last_v)
        else:
            out.append(0.0)
    return out


def _weekdays_in_month(y: int, m: int) -> int:
    d = date(y, m, 1)
    n = 0
    while d.month == m:
        n += d.weekday() < 5
        d += timedelta(days=1)
    return n


def dense_ipca(monthly: dict, days: list[date]) -> list[float]:
    """IPCA mensal distribuído pelos dias úteis do mês; meses ainda não publicados repetem o último publicado."""
    if not monthly:
        return [0.0] * len(days)
    last = monthly[max(monthly)]
    cache: dict = {}
    out = []
    for d in days:
        if d.weekday() >= 5:
            out.append(0.0)
            continue
        k = (d.year, d.month)
        if k not in cache:
            m = monthly.get(k, last)
            cache[k] = (1 + m) ** (1 / _weekdays_in_month(*k)) - 1
        out.append(cache[k])
    return out


def dense_price(px: dict, days: list[date]) -> list[float | None]:
    """Fechamento repetido para frente (fim de semana/feriado); None antes da 1ª cotação."""
    if not px:
        return [None] * len(days)
    ds = sorted(px)
    out = []
    for d in days:
        j = bisect.bisect_right(ds, d) - 1
        out.append(px[ds[j]] if j >= 0 else None)
    return out


def price_quality(px: dict, since: date, stale_run: int = 5, max_jump: float = 0.15) -> tuple[date | None, list[str]]:
    """Série gratuita com defeito não pode virar retorno. Defeitos: ≥ `stale_run` pregões seguidos com o mesmo
    fechamento (cotação congelada) ou salto diário acima de `max_jump`. Devolve a 1ª data depois do último defeito
    (None se o defeito está nos últimos 20 pregões: série inteira descartada) e a lista de defeitos."""
    ds = sorted(d for d in px if d >= since - timedelta(days=15))
    if len(ds) < 3:
        return (ds[0] if ds else None), []
    issues, last_bad = [], None
    run = 1
    for a, b in zip(ds, ds[1:]):
        va, vb = px[a], px[b]
        if vb == va:
            run += 1
            if run == stale_run:
                issues.append(f"cotação congelada a partir de {a.isoformat()}")
            if run >= stale_run:
                last_bad = b
        else:
            run = 1
            if va and abs(vb / va - 1) > max_jump:
                issues.append(f"salto de {vb / va - 1:+.0%} em {b.isoformat()}")
                last_bad = b
    if last_bad is None:
        return ds[0], issues
    after = [d for d in ds if d > last_bad]
    if len(after) < 20:
        return None, issues
    return after[0], issues


def proxy_rates(h: Holding, days: list[date], m: Market, _cache: dict | None = None) -> list[float]:
    cache = _cache if _cache is not None else {}

    def get(key, fn):
        if key not in cache:
            cache[key] = fn()
        return cache[key]

    if h.index == "CDI":
        cdi = get("CDI", lambda: dense_rate(m.cdi, days))
        rate = h.rate
        if rate is None or rate <= 0:
            return list(cdi)
        if rate > 10:  # % do CDI
            k = rate / 100.0
            return [c * k for c in cdi]
        spread = (1 + rate / 100.0) ** (1 / 252) - 1  # CDI + spread
        return [((1 + c) * (1 + spread) - 1) if c > 0 else 0.0 for c in cdi]
    if h.index == "SELIC":
        return list(get("SELIC", lambda: dense_rate(m.selic or m.cdi, days)))
    if h.index == "IPCA":
        ip = get("IPCA", lambda: dense_ipca(m.ipca, days))
        real = (1 + (h.rate or 0.0) / 100.0) ** (1 / 252) - 1
        return [((1 + x) * (1 + real) - 1) if d.weekday() < 5 else 0.0 for x, d in zip(ip, days)]
    if h.index == "PRE":
        g = (1 + (h.rate or 0.0) / 100.0) ** (1 / 252) - 1
        return [g if d.weekday() < 5 else 0.0 for d in days]
    return [0.0] * len(days)


# ------------------------------------------------------------------ série por investimento
def _trade_arrays(h: Holding, days: list[date]) -> tuple[list[float], list[float], int | None, list[str]]:
    n = len(days)
    first, last = days[0], days[-1]
    tf, tq = [0.0] * n, [0.0] * n
    first_idx = None
    notes = []
    skipped = 0.0
    for t in h.trades:
        if t.d < first or t.d > last:
            if t.d < first:
                skipped += t.flow
            continue
        i = (t.d - first).days
        tf[i] += t.flow
        tq[i] += t.dq
        first_idx = i if first_idx is None else min(first_idx, i)
    if abs(skipped) > 0.005:
        notes.append("movimentações anteriores ao início da janela não entram no cálculo")
    return tf, tq, first_idx, notes


def build_series(h: Holding, days: list[date], m: Market, cache: dict | None = None) -> Series:
    if h.kind == RV and h.symbol and m.prices.get(h.symbol):
        return _build_rv(h, days, m)
    return _build_rf(h, days, m, cache)


def _build_rf(h: Holding, days: list[date], m: Market, cache: dict | None) -> Series:
    n = len(days)
    first = days[0]
    r = proxy_rates(h, days, m, cache)
    tf, _, first_trade, notes = _trade_arrays(h, days)
    s = Series(h.id, [0.0] * n, [0.0] * n, notes=notes)
    obs = sorted((d, v) for d, v in h.obs.items() if first <= d <= days[-1])
    if h.transit_since:
        obs = [(d, v) for d, v in obs if d < h.transit_since]
    trade_idx = sorted(i for i in range(n) if abs(tf[i]) > 1e-9)

    # âncora
    if obs:
        a_idx, a_val = (obs[0][0] - first).days, float(obs[0][1])
    elif h.closed:
        if not trade_idx:
            return s  # encerrado e sem nada na janela
        a_idx, a_val = trade_idx[-1], 0.0
    else:
        a_idx, a_val = n - 1, float(h.current_value or 0.0)
    v = s.v
    v[a_idx] = a_val
    end = a_idx

    # para frente: entre snapshots, o que o indexador não explica vira fluxo inferido
    for (da, va), (db, vb) in zip(obs, obs[1:]):
        ia, ib = (da - first).days, (db - first).days
        x = v[ia]
        for i in range(ia + 1, ib):
            x = x * (1 + r[i]) + tf[i]
            v[i] = max(x, 0.0) if abs(x) < 0.01 else x
        expected = x * (1 + r[ib]) + tf[ib]
        growth = expected - v[ia] - sum(tf[ia + 1:ib + 1])
        tol = 0.5 + 0.002 * max(abs(v[ia]), abs(vb)) + 0.3 * abs(growth)
        diff = float(vb) - expected
        if abs(diff) > tol:
            tf[ib] += diff
            s.inferred_flows.append((db, round(diff, 2), "variação sem movimentação correspondente"))
        v[ib] = float(vb)
        end = ib
    if h.transit_since or (not obs and not h.closed):
        last_known = end
        stop = n - 1 if (h.transit_since or not obs) else end
        for i in range(last_known + 1, stop + 1):
            v[i] = v[i - 1] * (1 + r[i]) + tf[i]
            end = i
        if h.transit_since:
            s.notes.append(f"em trânsito desde {h.transit_since.isoformat()}: valor segue pelo indexador")
    if h.closed and not h.transit_since:
        # depois do último fluxo/observação o título não existe mais
        for i in range(end + 1, n):
            v[i] = 0.0

    # para trás: desfaz fluxos e rendimento
    start = 0
    neg_tol = lambda i: 1.0 + 0.005 * max(abs(v[i]), abs(tf[i]))  # noqa: E731
    for i in range(a_idx, 0, -1):
        prev = (v[i] - tf[i]) / (1 + r[i])
        if prev < -neg_tol(i):
            start = i
            tf[i] = 0.0  # v[i] passa a ser o valor inicial (sem fluxo de criação)
            s.notes.append(f"reconstrução inconsistente antes de {days[i].isoformat()} (valor negativo): série começa aí")
            break
        earlier_trades = first_trade is not None and first_trade < i
        if abs(prev) <= max(1.0, 0.003 * abs(tf[i])) and not earlier_trades:
            prev = 0.0
            v[i - 1] = 0.0
            start = i
            break
        v[i - 1] = prev
    else:
        start = 0
        if v[0] > 0.005:
            s.notes.append("já existia no início da janela")
    for i in range(start):
        v[i] = 0.0
        tf[i] = 0.0
    _entry_flow(s, v, tf, start, days)
    s.f = [tf[i] if i >= start else 0.0 for i in range(n)]
    nz = [i for i in range(n) if abs(v[i]) > 0.005 or abs(s.f[i]) > 0.005]
    s.start = nz[0] if nz else None
    s.end = end
    s.inferred_until = a_idx if obs else n
    return s


def _entry_flow(s: Series, v: list, tf: list, start: int, days: list[date]) -> None:
    """Série que começa no meio da janela sem aporte registrado: o valor inicial entra como aporte (inferido),
    senão o retorno do grupo daria um salto no dia em que ela aparece."""
    if start > 0 and abs(tf[start]) < 0.005 and v[start] > 0.005:
        tf[start] = v[start]
        s.inferred_flows.append((days[start], round(v[start], 2), "valor inicial tratado como aporte"))


def _build_rv(h: Holding, days: list[date], m: Market) -> Series:
    n = len(days)
    first = days[0]
    px = dense_price(m.prices[h.symbol], days)
    tf, tq, first_trade, notes = _trade_arrays(h, days)
    s = Series(h.id, [0.0] * n, [0.0] * n, notes=notes)
    if h.symbol in m.clean_from:
        cf = m.clean_from[h.symbol]
        if cf is None:
            px = [None] * n
            s.notes.append("cotação descartada (defeitos recentes na fonte)")
        elif cf > first:
            for i in range(min(n, (cf - first).days)):
                px[i] = None
            s.notes.append(f"cotação confiável só a partir de {cf.isoformat()}")
    proxy = None
    if h.fallback_index:
        proxy = proxy_rates(Holding(h.id, h.label, RF, h.fallback_index, h.fallback_rate), days, m)
    q = [0.0] * n
    qobs = sorted((d, x) for d, x in h.qty_obs.items() if first <= d <= days[-1] and x is not None)
    if h.transit_since:
        qobs = [(d, x) for d, x in qobs if d < h.transit_since]
    trade_idx = sorted(i for i in range(n) if abs(tq[i]) > 1e-9 or abs(tf[i]) > 1e-9)
    if qobs:
        a_idx, a_q = (qobs[0][0] - first).days, float(qobs[0][1])
    elif h.closed:
        if not trade_idx:
            return s
        a_idx, a_q = trade_idx[-1], 0.0
    else:
        a_idx, a_q = n - 1, float(h.current_qty or 0.0)
    q[a_idx] = a_q
    # para frente
    obs_map = {(d - first).days: float(x) for d, x in qobs}
    for i in range(a_idx + 1, n):
        expected = q[i - 1] + tq[i]
        if i in obs_map and abs(obs_map[i] - expected) > 1e-6:
            dq = obs_map[i] - expected
            price = px[i] or 0.0
            tf[i] += dq * price
            tq[i] += dq
            s.inferred_flows.append((days[i], round(dq * price, 2),
                                     f"quantidade mudou {dq:+g} sem negociação informada (valor pelo fechamento)"))
            expected = obs_map[i]
        q[i] = expected
    # para trás
    start = 0
    for i in range(a_idx, 0, -1):
        prev = q[i] - tq[i]
        if prev < -1e-6:
            start = i
            s.notes.append(f"quantidade negativa antes de {days[i].isoformat()}: série começa aí")
            tf[i] = 0.0
            break
        if px[i - 1] is None and prev > 1e-9:
            if proxy is not None and px[i] is not None:
                return _rv_proxy_tail(h, s, days, px, q, tf, tq, i, proxy, first_trade, a_idx, bool(qobs))
            start = i
            tf[i] = 0.0
            s.notes.append(f"sem cotação antes de {days[i].isoformat()}")
            break
        earlier = first_trade is not None and first_trade < i
        if prev <= 1e-9 and not earlier:
            q[i - 1] = 0.0
            start = i
            break
        q[i - 1] = prev
    else:
        if q[0] > 1e-9:
            s.notes.append("já existia no início da janela")
    # proventos pagos em conta (só quando a série de preço não é ajustada)
    divs = m.dividends.get(h.symbol) or {}
    for d, per_share in divs.items():
        if first < d <= days[-1]:
            i = (d - first).days
            held = q[i - 1]
            if held > 1e-9 and i >= start:
                tf[i] -= held * per_share
    last_px = max((i for i in range(n) if px[i] is not None), default=-1)
    for i in range(n):
        if i < start:
            s.v[i] = 0.0
            continue
        s.v[i] = q[i] * (px[i] or 0.0)
    _entry_flow(s, s.v, tf, start, days)
    s.f = [tf[i] if i >= start else 0.0 for i in range(n)]
    nz = [i for i in range(n) if abs(s.v[i]) > 0.005 or abs(s.f[i]) > 0.005]
    s.start = nz[0] if nz else None
    s.end = min(n - 1, last_px) if not h.closed else (max(nz) if nz else -1)
    s.inferred_until = a_idx if qobs else n
    return s


def _rv_proxy_tail(h: Holding, s: Series, days: list[date], px: list, q: list, tf: list, tq: list, i_switch: int,
                  proxy: list[float], first_trade: int | None, a_idx: int, has_obs: bool) -> Series:
    """Renda variável sem cotação confiável antes de i_switch: daí para trás o valor recua pelo indexador de
    referência (ex.: ETF de IPCA+ por IPCA + taxa), como um título de renda fixa. Marcado como proxy."""
    n = len(days)
    v = s.v
    for i in range(n):
        v[i] = q[i] * (px[i] or 0.0) if i >= i_switch else 0.0
    start = 0
    for i in range(i_switch, 0, -1):
        prev = (v[i] - tf[i]) / (1 + proxy[i])
        earlier = first_trade is not None and first_trade < i
        if prev <= max(1.0, 0.003 * abs(tf[i])) and not earlier:
            v[i - 1] = 0.0
            start = i
            break
        v[i - 1] = max(prev, 0.0)
    for i in range(start):
        v[i] = 0.0
    s.notes.append(f"antes de {days[i_switch].isoformat()} o valor segue o indexador de referência "
                   f"({h.fallback_index}{' + ' + str(h.fallback_rate).replace('.', ',') + '% a.a.' if h.fallback_rate else ''}), "
                   "sem marcação a mercado")
    _entry_flow(s, v, tf, start, days)
    s.f = [tf[i] if i >= start else 0.0 for i in range(n)]
    nz = [i for i in range(n) if abs(v[i]) > 0.005 or abs(s.f[i]) > 0.005]
    s.start = nz[0] if nz else None
    last_px = max((i for i in range(n) if px[i] is not None), default=-1)
    s.end = min(n - 1, last_px)
    s.inferred_until = a_idx if has_obs else n
    return s


# ------------------------------------------------------------------ agregação e períodos
def aggregate(series: list[Series], n: int) -> tuple[list[float], list[float]]:
    V, F = [0.0] * n, [0.0] * n
    for s in series:
        for i in range(n):
            V[i] += s.v[i]
            F[i] += s.f[i]
    return V, F


def daily_returns(V: list[float], F: list[float]) -> list[float | None]:
    out: list[float | None] = [None]
    for i in range(1, len(V)):
        out.append((V[i] - F[i]) / V[i - 1] - 1 if V[i - 1] > 0.01 else None)
    return out


def xirr(cashflows: list[tuple[date, float]]) -> float | None:
    cfs = [(d, c) for d, c in cashflows if abs(c) > 1e-9]
    if len(cfs) < 2 or not any(c < 0 for _, c in cfs) or not any(c > 0 for _, c in cfs):
        return None
    t0 = min(d for d, _ in cfs)
    span = (max(d for d, _ in cfs) - t0).days
    if span < 30:
        return None
    ys = [((d - t0).days / 365.0, c) for d, c in cfs]

    def npv(rate: float) -> float:
        return sum(c / (1 + rate) ** t for t, c in ys)

    lo, hi = -0.99, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7:
            break
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def period_stats(days: list[date], V: list[float], F: list[float], i0: int, i1: int,
                 inferred_until: int | None = None) -> dict:
    """Retorno do grupo em (i0, i1]. Se o grupo começa depois de i0, o período efetivo começa no 1º dia com valor."""
    i0 = max(0, i0)
    if i1 <= i0:
        return {"twr": None, "motivo": "período vazio"}
    eff = i0
    if V[i0] <= 0.01:
        nz = [i for i in range(i0, i1 + 1) if V[i] > 0.01]
        if not nz:
            return {"twr": None, "valor_inicial": 0.0, "valor_final": round(V[i1], 2), "motivo": "sem posição no período"}
        eff = max(i0, nz[0] - 1)  # véspera do 1º dia com valor: o aporte de criação entra como fluxo
    growth, valid = 1.0, 0
    for i in range(eff + 1, i1 + 1):
        if V[i - 1] > 0.01:
            growth *= (V[i] - F[i]) / V[i - 1]
            valid += 1
    flows = sum(F[eff + 1:i1 + 1])
    gain = V[i1] - V[eff] - flows
    cfs = [(days[eff], -V[eff])] + [(days[i], -F[i]) for i in range(eff + 1, i1 + 1) if abs(F[i]) > 0.005] + \
          [(days[i1], V[i1])]
    out = {
        "twr": growth - 1 if valid else None,
        "inicio": days[eff].isoformat(), "fim": days[i1].isoformat(),
        "inicio_efetivo_posterior": eff > i0,
        "valor_inicial": round(V[eff], 2), "valor_final": round(V[i1], 2),
        "aportes_liquidos": round(flows, 2), "ganho": round(gain, 2),
        "tir_aa": xirr(cfs),
        "reconstruido": inferred_until is not None and eff < inferred_until,
    }
    return out


def accumulated(rates: list[float], i0: int, i1: int) -> float | None:
    if i1 <= i0:
        return None
    g = 1.0
    for x in rates[i0 + 1:i1 + 1]:
        g *= 1 + x
    return g - 1


def price_return(px: list[float | None], i0: int, i1: int) -> float | None:
    a, b = px[i0], px[i1]
    if a is None:
        later = [i for i in range(i0, i1 + 1) if px[i] is not None]
        if not later:
            return None
        a = px[later[0]]
    if not a or b is None:
        return None
    return b / a - 1


def pct_of_cdi(twr: float | None, cdi: float | None, days: int) -> float | None:
    if twr is None or cdi is None or cdi <= 0 or twr <= -1 or days < 30:
        return None
    return math.log(1 + twr) / math.log(1 + cdi)


# ------------------------------------------------------------------ % do CDI de um título (multiplicador)
def cdi_multiplier(flows: list[tuple[date, float]], end: date, end_value: float, cdi: dict) -> float | None:
    """k tal que aplicar os fluxos a k × CDI resulta no valor final bruto. flows: (+ aplicação, − resgate bruto).
    É o número comparável à taxa contratada (ex.: 1,20 para um CDB de 120% do CDI)."""
    flows = [(d, x) for d, x in flows if abs(x) > 1e-9 and d <= end]
    if not flows or not any(x > 0 for _, x in flows):
        return None
    start = min(d for d, _ in flows)
    if (end - start).days < 30:
        return None
    days = day_range(start, end)
    rates = dense_rate({d: v for d, v in cdi.items() if start <= d <= end + timedelta(days=5)} or cdi, days)
    by_day: dict = {}
    for d, x in flows:
        by_day[(d - start).days] = by_day.get((d - start).days, 0.0) + x

    def fv(k: float) -> float:
        v = 0.0
        for i in range(len(days)):
            if i:
                v *= 1 + k * rates[i]
            v += by_day.get(i, 0.0)
        return v

    lo, hi = 0.0, 4.0
    if (fv(lo) - end_value) * (fv(hi) - end_value) > 0:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if fv(mid) < end_value:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
