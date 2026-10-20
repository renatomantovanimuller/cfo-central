"""Saída de investimento sem contrapartida: valores em trânsito, revisão high, resolução e salvaguardas do TWR."""
from datetime import date

import pandas as pd
from sqlalchemy import select

D0, D1, D2 = date(2026, 10, 7), date(2026, 10, 8), date(2026, 10, 10)


def _seed(s, *, withdraw: bool = True):
    from app.models import Investment, InvestmentBalance, Item
    from app.models import Account
    s.add(Item(id="it1", nickname="Inter"))
    s.flush()
    s.add(Account(id="acc1", item_id="it1", type="BANK", name="Conta"))
    s.flush()
    s.add(Investment(id="inv-tesouro", item_id="it1", name="Tesouro Selic 2031", type="FIXED_INCOME",
                     status="TOTAL_WITHDRAWAL" if withdraw else "ACTIVE", balance=0.0 if withdraw else 80000.0))
    s.add(Investment(id="inv-cdb", item_id="it1", name="CDB", type="FIXED_INCOME", status="ACTIVE", balance=50000.0))
    for d, tes in ((D0, 79930.0), (D1, 80000.0), (D2, 0.0)):
        s.add(InvestmentBalance(investment_id="inv-tesouro", date=d, balance=tes))
        s.add(InvestmentBalance(investment_id="inv-cdb", date=d, balance=50000.0))
    s.flush()


def _credit(s, amount, sid="tx-credito", etype="INVESTMENT_REDEMPTION", d=D2):
    from app.models import FinancialEvent
    s.add(FinancialEvent(source_id=sid, account_id="acc1", competence_date=d, cash_date=d, amount=amount,
                         event_type=etype, rule_source="manual", confidence=1.0,
                         description="Resgate Tesouro"))
    s.flush()


def test_saida_sem_contrapartida_gera_transito_e_review_high(db_reset):
    from app.accounting.balance import current_position
    from app.portfolio.service import performance, portfolio_reviews
    with db_reset() as s:
        _seed(s)
        t = current_position(s)["totals"]
        assert abs(t["in_transit"] - 80000.0) < 0.01
        assert abs(t["net_worth"] - (50000.0 + 80000.0)) < 0.01  # o PL não cai
        rv = [r for r in portfolio_reviews(s) if r.kind == "exit_no_counterpart"]
        assert len(rv) == 1 and rv[0].severity == "high"
        assert {o["id"] for o in rv[0].data["options"]} >= {"not_connected_account", "custody_transferred",
                                                           "provider_error", "loss"}
        perf = performance(s)
        assert perf["twr"] is not None and perf["twr"] > -0.01  # nada de −60%


def test_saida_com_resgate_creditado_nao_gera_transito(db_reset):
    from app.accounting.balance import current_position
    from app.portfolio.service import portfolio_reviews
    with db_reset() as s:
        _seed(s)
        _credit(s, 80000.0 * 1.01)  # dentro de ±2%
        assert current_position(s)["totals"]["in_transit"] == 0
        assert not [r for r in portfolio_reviews(s) if r.kind == "exit_no_counterpart"]


def test_saida_com_venda_registrada_nao_gera_transito(db_reset):
    from app.models import InvestmentTransaction
    from app.portfolio.transit import detect_exits
    with db_reset() as s:
        _seed(s)
        s.add(InvestmentTransaction(id="sell1", investment_id="inv-tesouro", type="SELL", amount=80000.0, date=D2))
        s.flush()
        assert detect_exits(s) == []


def test_resolucao_conta_nao_conectada_sai_do_pl_como_movimento_patrimonial(db_reset):
    from app.accounting.balance import current_position
    from app.portfolio.transit import detect_exits, set_resolution
    with db_reset() as s:
        _seed(s)
        (e,) = detect_exits(s)
        set_resolution(s, e["key"], "not_connected_account")
        t = current_position(s)["totals"]
        assert t["in_transit"] == 0
        assert abs(t["perimeter_exits"] - 80000.0) < 0.01
        assert abs(t["net_worth"] - 50000.0) < 0.01
        assert not [r for r in __import__("app.portfolio.service", fromlist=["x"]).portfolio_reviews(s)
                    if r.kind == "exit_no_counterpart"]


def test_resolucoes_que_mantem_ativo_e_perda(db_reset):
    from app.accounting.balance import current_position
    from app.portfolio.transit import detect_exits, set_resolution
    with db_reset() as s:
        _seed(s)
        (e,) = detect_exits(s)
        set_resolution(s, e["key"], "custody_transferred")
        assert abs(current_position(s)["totals"]["net_worth"] - (50000.0 + 80000.0)) < 0.01
        set_resolution(s, e["key"], "loss")
        t = current_position(s)["totals"]
        assert abs(t["writeoffs"] - 80000.0) < 0.01 and abs(t["net_worth"] - 50000.0) < 0.01


def test_twr_com_fluxo_nao_explicado_nao_retorna_valor_absurdo():
    from app.portfolio import metrics as M
    values = pd.Series({D0: 130000.0, D1: 130100.0, D2: 50000.0})
    r = M.twr_from_snapshots(values, pd.Series(dtype=float))
    twr, reason = M.guarded_twr(r)
    assert twr is None and "n/d" in reason
    pct, why = M.pct_of_cdi(twr, 0.002, 40)
    assert pct is None and why
    # retorno normal passa; % do CDI exige CDI > 0 e período ≥ 1 mês
    ok, _ = M.guarded_twr(pd.Series({D1: 0.001, D2: 0.002}))
    assert ok is not None
    assert M.pct_of_cdi(ok, 0.01, 10)[0] is None
    assert M.pct_of_cdi(ok, 0.0, 60)[0] is None
    assert abs(M.pct_of_cdi(0.012, 0.01, 60)[0] - 1.2) < 0.01


def _fund(s, inv_id, typ, rows, name="Fundo"):
    from app.models import Account, Investment, InvestmentBalance, Item
    if s.get(Item, "it1") is None:
        s.add(Item(id="it1", nickname="Banco"))
        s.flush()
        s.add(Account(id="acc1", item_id="it1", type="BANK", name="Conta"))
    s.add(Investment(id=inv_id, item_id="it1", name=name, type=typ, status="ACTIVE", balance=rows[-1][1]))
    s.flush()
    for d, bal, q in rows:
        s.add(InvestmentBalance(investment_id=inv_id, date=d, balance=bal, quantity=q, value=(bal / q if q else None)))
    s.flush()


def test_oscilacao_de_preco_de_etf_nao_e_saida(db_reset):
    from app.portfolio.transit import detect_exits
    with db_reset() as s:
        _fund(s, "divo", "ETF", [(D0, 147 * 100.0, 147), (D1, 147 * 97.5, 147)], "DIVO11")
        assert detect_exits(s) == []


def test_queda_de_quantidade_de_etf_e_saida_pelo_preco_anterior(db_reset):
    from app.portfolio.transit import detect_exits
    with db_reset() as s:
        _fund(s, "divo", "ETF", [(D0, 14700.0, 147), (D1, 7350.0, 73.5)], "DIVO11")
        (e,) = detect_exits(s)
        assert abs(e["amount"] - 7350.0) < 0.01


def test_resgate_parcial_com_dois_lotes_e_um_credito_nao_gera_saida(db_reset):
    from app.models import Investment, InvestmentBalance
    from app.portfolio.transit import detect_exits
    with db_reset() as s:
        _fund(s, "lote1", "FIXED_INCOME", [(D0, 2722.0, None), (D1, 0.0, None)])
        _fund(s, "lote2", "FIXED_INCOME", [(D0, 10000.0, None), (D1, 9722.0, None)])
        _credit(s, 3000.0, d=D1)
        assert detect_exits(s) == []


def test_resgate_mais_aporte_no_mesmo_dia_compara_soma_liquida(db_reset):
    from app.portfolio.transit import detect_exits
    with db_reset() as s:
        _fund(s, "lote1", "FIXED_INCOME", [(D0, 3000.0, None), (D1, 0.0, None)])
        _credit(s, 5000.0, sid="r", d=D1)
        _credit(s, -2000.0, sid="a", etype="INVESTMENT_CONTRIBUTION", d=D1)
        assert detect_exits(s) == []


def test_um_credito_nao_casa_com_duas_saidas(db_reset):
    from app.portfolio.transit import detect_exits
    with db_reset() as s:
        _fund(s, "a", "FIXED_INCOME", [(D0, 3000.0, None), (D1, 0.0, None)])
        _fund(s, "b", "FIXED_INCOME", [(D0, 3000.0, None), (D2, 0.0, None)])
        _credit(s, 3000.0, d=D1)
        assert [e["investment_id"] for e in detect_exits(s)] == ["b"]


def test_contrapartida_tardia_fecha_a_saida(db_reset):
    from app.portfolio.transit import detect_exits
    with db_reset() as s:
        _seed(s)
        assert len(detect_exits(s)) == 1
        _credit(s, 80000.0, d=date(2026, 10, 16))  # > 7 dias depois
        assert detect_exits(s) == []


def test_investimento_removido_do_payload_e_saida(db_reset):
    from app.models import Investment
    from app.utils.time import utcnow
    from app.portfolio.transit import detect_exits
    with db_reset() as s:
        _fund(s, "sumiu", "FIXED_INCOME", [(D0, 5000.0, None), (D1, 5000.0, None)])
        s.get(Investment, "sumiu").removed_at = utcnow()
        s.flush()
        (e,) = detect_exits(s)
        assert abs(e["amount"] - 5000.0) < 0.01


def test_income_de_outra_instituicao_nao_e_contrapartida(db_reset):
    from app.models import Account, Item
    from app.portfolio.transit import detect_exits
    with db_reset() as s:
        _seed(s)
        s.add(Item(id="it2", nickname="Outro"))
        s.flush()
        s.add(Account(id="acc2", item_id="it2", type="BANK", name="Outra"))
        s.flush()
        _credit(s, 80000.0, etype="INCOME")
        s.flush()
        from app.models import FinancialEvent
        ev = s.scalars(select(FinancialEvent)).first()
        ev.account_id = "acc2"
        s.flush()
        assert len(detect_exits(s)) == 1


def test_historico_soma_transito_desde_a_saida(db_reset):
    from app.accounting.balance import history
    from app.models import DailyNetWorth
    from app.utils.time import today_brt
    with db_reset() as s:
        _seed(s)
        s.add(DailyNetWorth(date=today_brt(), cash=0, investments=50000.0, net_worth=50000.0))
        s.flush()
        row = [h for h in history(s, 1) if not h["inferred"]]
        assert row and abs(row[-1]["net_worth"] - (50000.0 + 80000.0)) < 0.01
