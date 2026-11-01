"""Performance, proventos e rebalanceamento sobre a sincronização do cliente falso."""
from datetime import date, timedelta


def test_performance_report_tem_grupos_periodos_e_referencias(synced):
    from app.portfolio.tracking import performance_report
    with synced["sf"]() as s:
        rep = performance_report(s)
    assert rep["available"]
    assert {p["key"] for p in rep["periodos"]} == {"mes", "3m", "6m", "ano", "12m", "inicio"}
    assert rep["total"]["nome"] == "Carteira" and rep["por_classe"] and rep["por_instituicao"] and rep["por_ativo"]
    total_classes = sum(r["valor"] for r in rep["por_classe"])
    assert abs(total_classes - rep["total"]["valor"]) < 0.05
    assert "CDI" in rep["referencias"]["inicio"]


def test_rotulo_de_instituicao_usa_apelido_das_contas(db_reset):
    from app.models import Account, AccountSetting, Institution, Item
    from app.portfolio.tracking import institution_labels
    with db_reset() as s:
        s.add(Institution(id=200, name="MeuPluggy"))
        s.flush()
        s.add_all([Item(id="a", institution_id=200), Item(id="b", institution_id=200)])
        s.flush()
        s.add_all([Account(id="a1", item_id="a", type="BANK", name="Nu Pagamentos S.A."),
                   Account(id="b1", item_id="b", type="BANK", name="CONTA X")])
        s.flush()
        s.add(AccountSetting(account_id="b1", nickname="Inter · Conta"))
        s.flush()
        labels = institution_labels(s)
    assert labels == {"a": "Nubank", "b": "Inter"}


def test_proventos_lidos_da_descricao(db_reset):
    from app.models import FinancialEvent
    from app.portfolio.income import income_report, parse_provento
    p = parse_provento("Crédito Evento B3 - * Prov * Juros S/capital 18                 Pssa3")
    assert p == {"ticker": "PSSA3", "tipo": "JCP", "quantidade": 18.0}
    assert parse_provento("Cashback - Loja - 123") is None
    with db_reset() as s:
        d = date.today() - timedelta(days=20)
        s.add(FinancialEvent(source_id="p1", competence_date=d, cash_date=d, amount=8.62, event_type="INVESTMENT_INCOME",
                             rule_source="pluggy", confidence=1.0,
                             description="Crédito Evento B3 - * Prov * Dividendos 18                 Pssa3"))
        s.flush()
        rep = income_report(s)
    row = next(r for r in rep["por_ativo"] if r["ativo"] == "PSSA3")
    assert row["recebido_12m"] == 8.62 and not row["na_carteira"]
    assert rep["total_12m"] == 8.62


def test_aporte_vai_para_a_classe_abaixo_do_alvo(synced):
    from app.analytics.plano import put_setting, set_targets
    from app.portfolio.rebalance import suggest
    from app.portfolio.service import allocation, positions
    with synced["sf"]() as s:
        put_setting(s, "plano", {"reserva_meses_minima": 0})
        alloc = allocation(positions(s))
        classes = [x["label"] for x in alloc["by_class"]]
        assert len(classes) >= 2
        # alvo: tudo na menor classe → o aporte inteiro vai para ela
        set_targets(s, [{"asset_class": classes[-1], "target_pct": 0.9}, {"asset_class": classes[0], "target_pct": 0.1}])
        out = suggest(s, 1000.0)
    assert out["available"]
    rows = {r["classe"]: r for r in out["aporte_sem_venda"]}
    assert abs(rows[classes[-1]]["aplicar"] - 1000.0) < 0.01 and rows[classes[0]]["aplicar"] == 0
    ops = {o["classe"]: o for o in out["rebalanceamento_completo"]["operacoes"]}
    assert ops[classes[0]]["operacao"] == "vender"


def test_rotas_novas_respondem(synced):
    from app.api import routes_reports as R
    with synced["sf"]() as s:
        assert R.portfolio_performance(years=3, db=s)["available"]
        assert "por_ativo" in R.portfolio_income(db=s)
        assert R.portfolio_rebalance(aporte=None, db=s)["available"] is False  # sem alvos definidos
