from datetime import date

from app.analytics import overview
from app.models import Account, FinancialEvent, Item


def _event(i, d, amount, et, cat, acc="b1"):
    return FinancialEvent(source_id=f"t{i}", account_id=acc, competence_date=d, amount=amount, event_type=et,
                          category_id=cat, rule_source="manual", confidence=1.0)


def test_forecast_income_ignores_inheritance_and_bonus(db_reset, monkeypatch):
    s = db_reset()
    monkeypatch.setattr(overview, "today_brt", lambda: date(2026, 10, 16))
    monkeypatch.setattr(overview, "current_position", lambda _s: {
        "totals": {"cash": 1000.0, "card_current": 0.0}, "installments": {"by_month": []}})
    s.add(Item(id="i1"))
    s.flush()
    s.add(Account(id="b1", item_id="i1", type="BANK"))
    i = 0
    for month in range(4, 10):
        i += 1
        s.add(_event(i, date(2026, month, 5), 4000.0, "INCOME", "rec.salario"))
        i += 1
        s.add(_event(i, date(2026, month, 10), -2500.0, "EXPENSE", "des.mercado"))
    s.add(_event(100, date(2026, 8, 19), 60000.0, "INCOME", "rec.heranca"))
    s.add(_event(101, date(2026, 8, 20), 10000.0, "INCOME", "rec.bonus"))
    s.add(_event(102, date(2026, 8, 21), 7000.0, "INCOME", "rec.bonus"))
    s.add(_event(103, date(2026, 10, 2), 50000.0, "INCOME", "rec.heranca"))  # mês corrente parcial
    s.flush()

    out = overview.liquidity_forecast(s, horizon=3)

    assert out["months"][1]["income"] == 4000.0
    assert out["months"][1]["bank_expenses"] == 2500.0
    basis = out["assumptions_basis"]
    assert basis["income_basis"] == "salario_ultimo_valor"
    assert basis["expense_basis"] == "mediana_meses_completos"
    assert basis["months"] == 6
    assert out["months"][2]["end_cash"] < 10000.0
