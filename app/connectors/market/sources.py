"""Fontes de mercado gratuitas: BCB/SGS (oficial) e Yahoo Finance (endpoint de chart, o mesmo usado pelo yfinance)."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

import httpx

SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
SGS_SERIES = {"CDI": 12, "SELIC": 11, "IPCA": 433}  # CDI/Selic: % a.d. · IPCA: % a.m.
_UA = {"User-Agent": "Mozilla/5.0 (CFO Central; uso pessoal)"}


def sgs(code: int, start: date, end: date) -> list[tuple[date, float]]:
    out: list[tuple[date, float]] = []
    cur = start
    with httpx.Client(timeout=40, headers=_UA) as http:
        while cur <= end:  # SGS limita janelas longas em séries diárias
            chunk_end = min(end, cur + timedelta(days=365 * 5))
            params = {"formato": "json", "dataInicial": cur.strftime("%d/%m/%Y"), "dataFinal": chunk_end.strftime("%d/%m/%Y")}
            data = None
            for attempt in range(4):  # a API do BCB às vezes devolve HTML/erro transitório
                r = http.get(SGS_URL.format(code=code), params=params)
                if r.status_code == 404:
                    data = []
                    break
                try:
                    r.raise_for_status()
                    data = r.json()
                    break
                except (httpx.HTTPError, ValueError):
                    time.sleep(2 * (attempt + 1))
            if isinstance(data, dict):  # {"erro": ...} quando não há dados no intervalo
                data = []
            if data is None:
                raise RuntimeError(f"SGS {code}: resposta inválida após 4 tentativas (HTTP {r.status_code})")
            for row in data:
                d = datetime.strptime(row["data"], "%d/%m/%Y").date()
                out.append((d, float(str(row["valor"]).replace(",", "."))))
            cur = chunk_end + timedelta(days=1)
    return out


def yahoo_history(symbol: str, start: date, end: date | None = None) -> list[tuple[date, float]]:
    end = end or date.today() + timedelta(days=1)
    p1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp())
    with httpx.Client(timeout=40, headers=_UA) as http:
        r = http.get(YAHOO_URL.format(symbol=symbol), params={
            "period1": p1, "period2": p2, "interval": "1d", "events": "div,splits", "includeAdjustedClose": "true"})
        if r.status_code == 404:
            return []
        r.raise_for_status()
        res = (r.json().get("chart") or {}).get("result") or []
    if not res:
        return []
    res = res[0]
    ts = res.get("timestamp") or []
    ind = res.get("indicators") or {}
    adj = ((ind.get("adjclose") or [{}])[0] or {}).get("adjclose")
    close = ((ind.get("quote") or [{}])[0] or {}).get("close")
    series = adj or close or []
    gmtoff = (res.get("meta") or {}).get("gmtoffset") or 0
    out = []
    for t, v in zip(ts, series):
        if v is None:
            continue
        d = datetime.fromtimestamp(t + gmtoff, tz=timezone.utc).date()
        out.append((d, float(v)))
    return out
