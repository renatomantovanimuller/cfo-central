"""Leitura de gastos por janela e página por ativo, sobre a sincronização do cliente falso."""


def _months_with_spend(sf):
    from sqlalchemy import func, select
    from app.models import FinancialEvent
    with sf() as s:
        rows = s.execute(select(func.min(FinancialEvent.competence_date), func.max(FinancialEvent.competence_date))
                         .where(FinancialEvent.event_type == "EXPENSE")).one()
    return rows


def test_gastos_somam_igual_ao_painel(synced):
    from app.analytics.overview import overview
    from app.analytics.spending import spending_report
    _, last = _months_with_spend(synced["sf"])
    month = last.strftime("%Y-%m")
    with synced["sf"]() as s:
        rep = spending_report(s, month, 1)
        ov = overview(s, month)
    assert rep["months"] == 1 and rep["range"]["start"].startswith(month)
    total_cats = sum(c["value"] for c in rep["categories"])
    assert abs(total_cats - rep["totals"]["value"]) < 0.05
    assert abs(sum(x["value"] for x in ov["top_categories"]) - sum(c["value"] for c in rep["categories"] if c["value"] > 0)) < 0.05
    assert abs(sum(d["value"] for d in rep["daily"]) - rep["totals"]["value"]) < 0.05
    for c in rep["categories"]:
        assert abs(sum(k["value"] for k in c["children"]) - c["value"]) < 0.05
    assert len(rep["weekday"]) == 7


def test_janela_e_periodo_anterior_nao_se_sobrepoem(synced):
    from app.analytics.spending import spending_report
    _, last = _months_with_spend(synced["sf"])
    month = last.strftime("%Y-%m")
    with synced["sf"]() as s:
        rep3 = spending_report(s, month, 3)
        rep1 = spending_report(s, month, 1)
    assert len(rep3["series"]) == 3 and rep3["series"][-1]["month"] == month
    assert rep3["previous_range"]["end"] < rep3["range"]["start"]
    assert abs(sum(r["total"] for r in rep3["series"]) - rep3["totals"]["value"]) < 0.05
    assert rep3["totals"]["value"] >= rep1["totals"]["value"] - 0.05 or rep3["totals"]["value"] < 0


def test_evolucao_de_aportes_fecha_com_o_valor(synced):
    from app.portfolio.tracking import performance_report
    with synced["sf"]() as s:
        rep = performance_report(s)
    ap = rep["aportes"]
    assert ap and ap[-1]["valor"] == rep["total"]["valor"]
    for r in ap:
        assert abs(r["partida"] + r["aportes_acumulados"] + r["rendimento_acumulado"] - r["valor"]) < 0.05


def test_pagina_do_ativo(synced):
    from app.portfolio.tracking import holding_detail, performance_report
    with synced["sf"]() as s:
        rep = performance_report(s)
        hid = next(r["id"] for r in rep["por_ativo"] if r.get("id"))
        det = holding_detail(s, hid)
        missing = holding_detail(s, "nao-existe")
    assert det["available"] and det["curva"] and det["periodos"]
    assert {p["key"] for p in det["periodos"]} >= {"mes", "12m", "inicio"}
    row = next(r for r in rep["por_ativo"] if r.get("id") == hid)
    assert abs(det["curva"][-1]["valor"] - row["valor"]) < 0.05
    assert not missing["available"]


def test_rotas_novas(synced):
    from app.api import routes_reports as R
    with synced["sf"]() as s:
        sp = R.spending(None, 3, None, s)
        perf = R.portfolio_performance(3, s)
        hid = next(r["id"] for r in perf["por_ativo"] if r.get("id"))
        det = R.portfolio_holding(hid, s)
        alvos = R.get_targets(s)
    assert "classes" in alvos and "reserva" in alvos
    assert sp["months"] == 3 and "categories" in sp
    assert det["available"] and det["id"] == hid
