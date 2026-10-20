"""Métricas de carteira (funções puras sobre séries de retornos diários)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def annualize_return(r: pd.Series) -> float | None:
    r = r.dropna()
    if len(r) < 2:
        return None
    growth = float((1 + r).prod())
    return growth ** (TRADING_DAYS / len(r)) - 1 if growth > 0 else None


def cumulative(r: pd.Series) -> pd.Series:
    return (1 + r.fillna(0)).cumprod() - 1


def max_drawdown(r: pd.Series) -> tuple[float, object, object]:
    """(drawdown máximo, data do pico, data do vale)."""
    wealth = (1 + r.fillna(0)).cumprod()
    peak = wealth.cummax()
    dd = wealth / peak - 1
    if dd.empty:
        return 0.0, None, None
    trough = dd.idxmin()
    peak_date = wealth.loc[:trough].idxmax()
    return float(dd.min()), peak_date, trough


def risk_stats(r: pd.Series, rf: pd.Series | None = None, bench: pd.Series | None = None) -> dict:
    r = r.dropna()
    n = len(r)
    if n < 20:
        return {"n_days": n, "insufficient": True}
    rf = (rf.reindex(r.index).fillna(0) if rf is not None else pd.Series(0.0, index=r.index))
    ann = annualize_return(r)
    rf_ann = annualize_return(rf) or 0.0
    vol = float(r.std(ddof=1) * math.sqrt(TRADING_DAYS))
    excess = r - rf
    downside = excess[excess < 0]
    dvol = float(math.sqrt((downside ** 2).sum() / n) * math.sqrt(TRADING_DAYS)) if len(downside) else 0.0
    mdd, peak, trough = max_drawdown(r)
    q = float(r.quantile(0.05))
    m21 = (1 + r).rolling(21).apply(np.prod, raw=True).dropna() - 1
    out = {
        "n_days": n, "start": r.index[0], "end": r.index[-1],
        "return_ann": ann, "return_total": float((1 + r).prod() - 1), "rf_ann": rf_ann,
        "vol_ann": vol, "sharpe": ((ann or 0) - rf_ann) / vol if vol > 1e-9 else None,
        "sortino": ((ann or 0) - rf_ann) / dvol if dvol > 1e-9 else None,
        "max_drawdown": mdd, "dd_peak": peak, "dd_trough": trough,
        "var95_1d": -q, "cvar95_1d": float(-r[r <= q].mean()) if (r <= q).any() else None,
        "var95_21d": float(-m21.quantile(0.05)) if len(m21) > 30 else None,
        "best_day": float(r.max()), "worst_day": float(r.min()),
        "positive_days": float((r > 0).mean()),
    }
    if bench is not None:
        b = bench.reindex(r.index).dropna()
        rr = r.reindex(b.index)
        if len(b) > 20 and b.var() > 0:
            out["beta"] = float(rr.cov(b) / b.var())
            out["correlation"] = float(rr.corr(b))
            te = (rr - b).std() * math.sqrt(TRADING_DAYS)
            out["tracking_error"] = float(te)
    return out


def risk_contributions(returns: pd.DataFrame, weights: pd.Series) -> pd.DataFrame:
    """Contribuição de cada ativo à variância da carteira (soma = 100%)."""
    cols = [c for c in returns.columns if c in weights.index]
    if not cols:
        return pd.DataFrame()
    w = weights[cols] / weights[cols].sum()
    cov = returns[cols].cov() * TRADING_DAYS
    port_var = float(w @ cov @ w)
    if port_var <= 0:
        return pd.DataFrame()
    marginal = cov @ w
    rc = w * marginal / port_var
    vol = np.sqrt(np.diag(cov))
    return pd.DataFrame({"weight": w, "vol_ann": vol, "risk_contribution": rc})


def hhi(weights: pd.Series) -> float:
    w = weights / weights.sum()
    return float((w ** 2).sum())


def twr_from_snapshots(values: pd.Series, flows: pd.Series) -> pd.Series:
    """Retornos por período entre snapshots: r_t = (V_t − F_t) / V_{t−1} − 1, com F_t = aportes − resgates do período."""
    v = values.sort_index()
    f = flows.groupby(level=0).sum() if not flows.empty else flows
    rets = {}
    prev_date, prev_val = None, None
    for d, val in v.items():
        if prev_date is not None and prev_val and prev_val > 0:
            period_flow = float(f[(f.index > prev_date) & (f.index <= d)].sum()) if not f.empty else 0.0
            rets[d] = (val - period_flow) / prev_val - 1
        prev_date, prev_val = d, val
    return pd.Series(rets, dtype=float)


MAX_SUBPERIOD_RETURN = 0.5  # |retorno| acima disso entre dois snapshots indica fluxo não explicado
MIN_DAYS_PCT_CDI = 30


def guarded_twr(rets: pd.Series) -> tuple[float | None, str | None]:
    """TWR acumulado ou (None, motivo) se algum subperíodo tiver retorno implausível (fluxo não explicado)."""
    if rets.empty:
        return None, "sem subperíodos válidos"
    bad = rets[(rets.abs() > MAX_SUBPERIOD_RETURN) | rets.isna()]
    if not bad.empty:
        d, v = bad.index[0], bad.iloc[0]
        return None, (f"n/d: variação de {v * 100:.0f}% em {d:%d/%m/%Y} sem fluxo que a explique "
                      "(possível saída sem contrapartida)")
    return float((1 + rets).prod() - 1), None


def pct_of_cdi(twr: float | None, cdi_acc: float | None, days: int) -> tuple[float | None, str | None]:
    """% do CDI = ln(1+TWR)/ln(1+CDI); só com TWR válido, CDI do período > 0 e período ≥ 1 mês."""
    if twr is None:
        return None, "n/d: retorno indisponível"
    if days < MIN_DAYS_PCT_CDI:
        return None, "n/d: período inferior a 1 mês"
    if not cdi_acc or cdi_acc <= 0:
        return None, "n/d: CDI do período não positivo"
    if twr <= -1:
        return None, "n/d: retorno inválido"
    return math.log(1 + twr) / math.log(1 + cdi_acc), None


def xirr(cashflows: list[tuple[object, float]]) -> float | None:
    """TIR anualizada (fluxos: −aporte, +resgate/valor final)."""
    if len(cashflows) < 2 or not any(c < 0 for _, c in cashflows) or not any(c > 0 for _, c in cashflows):
        return None
    t0 = min(d for d, _ in cashflows)
    years = [((d - t0).days / 365.0, c) for d, c in cashflows]

    def npv(rate: float) -> float:
        return sum(c / (1 + rate) ** t for t, c in years)

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
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2
