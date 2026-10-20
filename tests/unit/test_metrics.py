from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.portfolio import metrics as M
from app.portfolio.classification import classify
from app.categorization.text import merchant_alias


def test_twr_neutralizes_flows():
    d = [date(2026, 1, 1) + timedelta(days=i) for i in range(3)]
    values = pd.Series([1000.0, 2010.0, 2030.1], index=d)  # aporte de 1000 no dia 2 + 1% e 1%
    flows = pd.Series([1000.0], index=[d[1]])
    r = M.twr_from_snapshots(values, flows)
    assert abs((1 + r).prod() - 1 - 0.0201) < 1e-3


def test_xirr_simple():
    cfs = [(date(2025, 1, 1), -1000.0), (date(2026, 1, 1), 1100.0)]
    assert abs(M.xirr(cfs) - 0.10) < 1e-3


def test_drawdown_and_stats():
    idx = pd.date_range("2025-01-01", periods=100, freq="B").date
    r = pd.Series(np.r_[np.full(50, 0.01), np.full(50, -0.01)], index=idx)
    mdd, _, _ = M.max_drawdown(r)
    assert -0.4 < mdd < -0.35
    st = M.risk_stats(r)
    assert st["vol_ann"] > 0 and st["var95_1d"] >= 0.0099


def test_classification():
    assert classify({"type": "ETF", "subtype": "ETF", "code": "IVVB11"})["asset_class"] == "ETF Internacional"
    assert classify({"type": "ETF", "subtype": "ETF", "code": "B5P211"})["asset_class"] == "ETF Renda Fixa"
    c = classify({"type": "FIXED_INCOME", "subtype": "CDB", "rate_type": "CDI", "rate": 120, "issuer": "X"})
    assert c["asset_class"] == "RF Pós" and c["fgc_covered"] and c["risk_proxy"] == "CDI"
    assert classify({"type": "FIXED_INCOME", "subtype": "TREASURY", "rate_type": "IPCA"})["asset_class"] == "Tesouro IPCA+"
    assert classify({"type": "EQUITY", "subtype": "REAL_ESTATE_FUND", "code": "HGLG11"})["asset_class"] == "FIIs"


def test_merchant_alias():
    assert merchant_alias("UBER *TRIP 1234 SAO PAULO") == "uber trip sao"
    assert merchant_alias("Ifd*Restaurante Sabor") == "restaurante sabor"
