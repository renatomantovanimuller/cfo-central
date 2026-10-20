"""Sincronização de séries de mercado (BCB/SGS + Yahoo) para ativos da carteira, proxies e benchmarks."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.connectors.market.sources import SGS_SERIES, sgs, yahoo_history
from app.models import Asset, AssetPrice, MarketSeries
from app.utils.time import today_brt

BENCHMARKS = {"^BVSP": "Ibovespa", "^GSPC": "S&P 500 (USD)", "BRL=X": "Dólar (BRL)", "IMAB11.SA": "IMA-B (proxy IPCA+)",
              "IRFM11.SA": "IRF-M (proxy pré)", "IVVB11.SA": "S&P 500 em BRL (IVVB11)"}
HISTORY_YEARS = 3


def _last_date(s: Session, model, col, key_col, key) -> date | None:
    return s.scalar(select(func.max(col)).where(key_col == key))


def sync_market(s: Session, rl=None) -> dict:
    today = today_brt()
    start_default = today - timedelta(days=365 * HISTORY_YEARS)
    stats = {"sgs": {}, "yahoo": {}, "errors": []}

    for code, sid in SGS_SERIES.items():
        last = _last_date(s, MarketSeries, MarketSeries.date, MarketSeries.code, code)
        start = (last + timedelta(days=1)) if last else start_default
        if start > today:
            continue
        try:
            rows = sgs(sid, start, today)
            existing = set(s.scalars(select(MarketSeries.date).where(MarketSeries.code == code,
                                                                     MarketSeries.date >= start)))
            for d, v in rows:
                if d not in existing:
                    s.add(MarketSeries(code=code, date=d, value=v))
            stats["sgs"][code] = len(rows)
            s.commit()
        except Exception as exc:  # noqa: BLE001
            s.rollback()
            stats["errors"].append(f"SGS {code}: {exc}")
            if rl:
                rl.log("warn", f"sgs:{code}", str(exc))
    s.flush()

    symbols = set(BENCHMARKS)
    for a in s.scalars(select(Asset)):
        if a.yahoo_symbol:
            symbols.add(a.yahoo_symbol)
        if a.risk_proxy and any(ch in a.risk_proxy for ch in ".^="):
            symbols.add(a.risk_proxy)
    for sym in sorted(symbols):
        last = _last_date(s, AssetPrice, AssetPrice.date, AssetPrice.symbol, sym)
        start = (last - timedelta(days=5)) if last else start_default
        try:
            rows = yahoo_history(sym, start)
            existing = {p.date: p for p in s.scalars(select(AssetPrice).where(AssetPrice.symbol == sym,
                                                                               AssetPrice.date >= start))}
            for d, v in rows:
                if d in existing:
                    existing[d].close = v
                else:
                    s.add(AssetPrice(symbol=sym, date=d, close=v, source="yahoo"))
            stats["yahoo"][sym] = len(rows)
            s.commit()
        except Exception as exc:  # noqa: BLE001
            s.rollback()
            stats["errors"].append(f"Yahoo {sym}: {exc}")
            if rl:
                rl.log("warn", f"yahoo:{sym}", str(exc))
    s.flush()
    return stats


# ------------------------------------------------------------------ leitura
def series_frame(s: Session, codes: list[str], start: date) -> pd.DataFrame:
    rows = s.execute(select(MarketSeries.code, MarketSeries.date, MarketSeries.value)
                     .where(MarketSeries.code.in_(codes), MarketSeries.date >= start)).all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["code", "date", "value"])
    return df.pivot(index="date", columns="code", values="value").sort_index()


def price_frame(s: Session, symbols: list[str], start: date) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()
    rows = s.execute(select(AssetPrice.symbol, AssetPrice.date, AssetPrice.close)
                     .where(AssetPrice.symbol.in_(symbols), AssetPrice.date >= start)).all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["symbol", "date", "close"])
    wide = df.pivot(index="date", columns="symbol", values="close").sort_index()
    return wide.apply(clean_prices)


def clean_prices(px: pd.Series, stale_run: int = 5, max_dev: float = 0.2) -> pd.Series:
    """Saneamento de séries gratuitas: preço repetido por ≥5 pregões (cotação congelada) e pontos >20% fora da
    mediana móvel viram lacuna, preenchida por interpolação. Evita saltos artificiais nas métricas de risco."""
    s = px.astype(float).copy()
    valid = s.dropna()
    if len(valid) < 10:
        return s
    run_id = (valid != valid.shift()).cumsum()
    run_len = valid.groupby(run_id).transform("size")
    s.loc[run_len[run_len >= stale_run].index] = float("nan")
    med = s.rolling(21, center=True, min_periods=5).median()
    s[(s / med - 1).abs() > max_dev] = float("nan")
    return s.interpolate(limit_area="inside")


def cdi_daily(s: Session, start: date) -> pd.Series:
    df = series_frame(s, ["CDI"], start)
    return (df["CDI"] / 100.0) if "CDI" in df else pd.Series(dtype=float)


def accumulated(rate_daily: pd.Series, start: date, end: date) -> float | None:
    r = rate_daily[(rate_daily.index > start) & (rate_daily.index <= end)]
    return float((1 + r).prod() - 1) if len(r) else None


def ipca_accumulated(s: Session, start: date, end: date) -> float | None:
    df = series_frame(s, ["IPCA"], start.replace(day=1))
    if "IPCA" not in df:
        return None
    r = df["IPCA"][(df.index >= start.replace(day=1)) & (df.index <= end)] / 100
    return float((1 + r).prod() - 1) if len(r) else None
