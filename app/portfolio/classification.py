"""Classificação de investimentos Pluggy em ativos canônicos (classe, indexador, liquidez, FGC, proxy de risco)."""
from __future__ import annotations

import re

from app.categorization.text import norm

ETF_INTL = {"IVVB11", "SPXR11", "SPXI11", "NASD11", "WRLD11", "ACWI11", "EURP11", "XINA11", "BBSD11", "TECK11",
            "SMAC11", "GOLD11", "USDB11", "ASIA11", "QQQM11", "BIEM11", "IMBB11"}
ETF_BR_EQUITY = {"BOVA11", "BOVV11", "BOVX11", "SMAL11", "DIVO11", "BOVB11", "PIBB11", "ECOO11", "MATB11",
                 "FIND11", "GOVE11", "BRAX11", "XBOV11", "NSDV11", "DIVD11", "SMAB11"}
ETF_FIXED = {"B5P211", "IMAB11", "IRFM11", "FIXA11", "LFTS11", "IB5M11", "B5MB11", "IMBB11", "DEBB11",
             "NTNS11", "LFTB11", "IDKA11", "5PRE11", "ALUG11"}
ETF_CRYPTO = {"HASH11", "QBTC11", "BITH11", "ETHE11", "QETH11", "BITI11", "CRPT11", "DEFI11", "NFTS11"}
FGC_SUBTYPES = {"CDB", "LCI", "LCA", "LC", "RDB", "LCD", "LIG", "POUPANCA"}
TICKER_RE = re.compile(r"^(?=[A-Z0-9]*[A-Z])[A-Z0-9]{4}\d{1,2}[A-Z]?$")

ASSET_CLASSES = [
    "RF Pós", "RF Pré", "RF IPCA+", "Tesouro Selic", "Tesouro Prefixado", "Tesouro IPCA+",
    "ETF Renda Fixa", "Ações BR", "ETF Ações BR", "FIIs", "ETF Internacional", "Fundos",
    "Previdência", "Cripto", "COE", "Outros",
]
RISK_BUCKET = {  # para alocação estratégica
    "RF Pós": "Pós-fixado", "Tesouro Selic": "Pós-fixado", "Fundos": "Multimercado/Fundos",
    "RF Pré": "Prefixado", "Tesouro Prefixado": "Prefixado",
    "RF IPCA+": "Inflação", "Tesouro IPCA+": "Inflação", "ETF Renda Fixa": "Inflação",
    "Ações BR": "Renda variável BR", "ETF Ações BR": "Renda variável BR", "FIIs": "Imobiliário",
    "ETF Internacional": "Internacional", "Cripto": "Alternativos", "COE": "Alternativos",
    "Previdência": "Previdência", "Outros": "Outros",
}


def _indexer(rate_type: str | None) -> str | None:
    rt = (rate_type or "").upper()
    if rt in ("CDI", "DI"):
        return "CDI"
    if rt == "SELIC":
        return "SELIC"
    if rt.startswith("IPCA") or rt in ("IGPM", "INPC"):
        return "IPCA"
    if rt in ("PRE_FIXADO", "PRE", "PREFIXADO", "FIXED"):
        return "PRE"
    return None


DAILY_LIQUIDITY_HINTS = ("NU FINANCEIRA", "NUBANK", "NU PAGAMENTOS", "CAIXINHA", "LIQUIDEZ DI", "RESGATE DI")
DAILY_LIQUIDITY_SUBTYPES = {"RDB"}


def has_daily_liquidity(inv: dict) -> bool:
    """CDB/RDB com resgate diario: Nu Financeira/Nubank, caixinhas, RDB, ou historico de resgate parcial antes do vencimento."""
    if inv.get("early_redemption"):
        return True
    if (inv.get("subtype") or "").upper() in DAILY_LIQUIDITY_SUBTYPES:
        return True
    text = norm(f"{inv.get('issuer') or ''} {inv.get('name') or ''} {inv.get('institution') or ''}").upper()
    return any(h in text for h in DAILY_LIQUIDITY_HINTS)


def classify(inv: dict) -> dict:
    """inv: dicionário com campos de Investment. Retorna atributos do Asset."""
    typ, sub = (inv.get("type") or "").upper(), (inv.get("subtype") or "").upper()
    code = (inv.get("code") or "").upper().strip()
    ticker = code if TICKER_RE.match(code) else None
    indexer = _indexer(inv.get("rate_type"))
    issuer = inv.get("issuer")
    out = {"indexer": indexer, "issuer": issuer, "fgc_covered": False, "yahoo_symbol": None,
           "risk_proxy": None, "liquidity": None}

    if typ == "FIXED_INCOME":
        if sub == "TREASURY":
            cls = {"IPCA": "Tesouro IPCA+", "SELIC": "Tesouro Selic", "CDI": "Tesouro Selic"}.get(indexer or "", "Tesouro Prefixado")
            out.update(liquidity="D1", issuer="Tesouro Nacional")
        else:
            cls = {"CDI": "RF Pós", "SELIC": "RF Pós", "IPCA": "RF IPCA+"}.get(indexer or "", "RF Pré")
            out.update(fgc_covered=sub in FGC_SUBTYPES,
                       liquidity="D0" if has_daily_liquidity(inv) else "vencimento")
        key = inv.get("isin") or code or f"rf:{norm(issuer)[:40]}:{sub}:{indexer}:{inv.get('rate')}:{inv.get('due_date')}"
    elif typ in ("ETF", "EQUITY"):
        if ticker in ETF_INTL:
            cls = "ETF Internacional"
        elif ticker in ETF_FIXED:
            cls = "ETF Renda Fixa"
        elif ticker in ETF_CRYPTO:
            cls = "Cripto"
        elif ticker in ETF_BR_EQUITY or typ == "ETF":
            cls = "ETF Ações BR"
        elif sub in ("REAL_ESTATE_FUND", "FII") or (ticker and ticker.endswith("11") and typ == "EQUITY"
                                                     and sub == "REAL_ESTATE_FUND"):
            cls = "FIIs"
        else:
            cls = "Ações BR"
        indexer = "VAR"
        out.update(indexer="VAR", liquidity="D2", yahoo_symbol=f"{ticker}.SA" if ticker else None)
        key = ticker or inv.get("isin") or f"rv:{inv.get('name')}"
    elif typ == "MUTUAL_FUND":
        cls = "Fundos"
        out.update(liquidity="D30")
        key = code or inv.get("isin") or f"fundo:{norm(inv.get('name'))[:60]}"
    elif typ == "SECURITY":
        cls = "COE" if sub == "COE" else "Previdência"
        key = code or f"sec:{norm(inv.get('name'))[:60]}"
    else:
        cls = "Outros"
        key = code or f"outro:{norm(inv.get('name'))[:60]}"

    # proxy de risco diário (identificado como proxy nas telas)
    proxy = out["yahoo_symbol"]
    if not proxy:
        proxy = {"RF Pós": "CDI", "Tesouro Selic": "SELIC", "RF IPCA+": "IMAB11.SA", "Tesouro IPCA+": "IMAB11.SA",
                 "RF Pré": "IRFM11.SA", "Tesouro Prefixado": "IRFM11.SA", "Fundos": "CDI",
                 "Previdência": "CDI", "COE": "CDI", "Outros": "CDI"}.get(cls, "CDI")
    out.update(asset_class=cls, risk_proxy=proxy, key=str(key)[:80])
    return out
