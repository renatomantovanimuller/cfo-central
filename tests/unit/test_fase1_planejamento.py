"""Fase 1 do roteiro: custos anuais, reserva em degraus, aporte que sobe com aumento, aporte direcionado,
calendário fiscal e revisão por valor da informação."""
from datetime import date, timedelta

import pytest


def _setup(s):
    from app.categorization.chart import seed_chart
    from app.models import Account, Item
    seed_chart(s)
    s.add(Item(id="i1"))
    s.flush()
    s.add(Account(id="b1", item_id="i1", type="BANK", balance=0.0))
    s.flush()


def _ev(sid, d, amount, cat, et="EXPENSE", desc="", mid=None):
    from app.models import FinancialEvent
    return FinancialEvent(source_id=sid, account_id="b1", competence_date=d, amount=amount, event_type=et,
                          category_id=cat, rule_source="manual", confidence=1.0, description=desc, merchant_id=mid)


# ---------------------------------------------------------------- custos verdadeiros (despesas anuais)
def test_despesa_anual_detectada_provisionada_e_avisada(db_reset):
    from app.analytics.recurring import detect_annual
    from app.models import RecurringRule
    s = db_reset()
    _setup(s)
    today = date(2026, 10, 20)
    s.add(_ev("ipva", date(2025, 12, 5), -1800.0, "transporte.seguro_impostos", desc="IPVA 2025 SP"))
    s.add(_ev("loja", date(2026, 3, 3), -900.0, "compras.diversos", desc="Loja qualquer"))  # compra avulsa: não é anual
    s.flush()
    found, cands = detect_annual(s, {}, {}, today)
    s.flush()
    rules = {r.key: r for r in s.query(RecurringRule)}
    assert found == 1 and len(rules) == 1
    r = next(iter(rules.values()))
    assert r.frequency_days == 365 and r.next_date == date(2026, 12, 5) and r.expected_amount == 1800.0
    assert [c.kind for c in cands] == ["annual_upcoming"]  # vence em 46 dias


def test_quanto_posso_gastar_separa_um_doze_avos_das_anuais(db_reset):
    from app.analytics.plano import safe_to_spend
    from app.models import RecurringRule
    s = db_reset()
    _setup(s)
    today = date(2026, 6, 10)
    s.add(RecurringRule(key="a:m:1", description="IPVA", direction="out", expected_amount=1200.0, frequency_days=365,
                        last_date=date(2026, 1, 5), next_date=date(2027, 1, 5), status="detected"))
    s.add(RecurringRule(key="a:m:2", description="Seguro", direction="out", expected_amount=600.0, frequency_days=365,
                        last_date=date(2025, 6, 25), next_date=date(2026, 6, 25), status="detected"))
    s.flush()
    sts = safe_to_spend(s, today)
    assert sts["provisao"] == 100.0                       # só o IPVA: 1200/12
    assert [p["valor"] for p in sts["recorrencias_pendentes"]] == [600.0]  # o seguro vence neste mês: valor cheio
    assert round(sts["disponivel"], 2) == round(sts["renda_prevista"] - sts["meta_aporte"] - sts["gasto_ate_hoje"]
                                                - sts["comprometido"] - sts["provisao"], 2)


# ---------------------------------------------------------------- aporte direcionado e reserva
def test_aporte_completa_reserva_e_depois_classes_abaixo_do_alvo():
    from app.analytics.plano import aporte_direcionado
    classes = [{"classe": "RF Pós", "alvo": 0.5, "valor": 6000.0}, {"classe": "Ações BR", "alvo": 0.3, "valor": 3000.0},
               {"classe": "ETF Internacional", "alvo": 0.2, "valor": 1000.0}]
    reserva = {"proximo_degrau": {"nome": "Colchão inicial", "meses": 1.0, "falta": 500.0}}
    out = aporte_direcionado(classes, 10000.0, 2000.0, reserva)
    assert out[0]["destino"].startswith("Reserva") and out[0]["valor"] == 500.0
    resto = {x["destino"]: x["valor"] for x in out[1:]}
    # total final 11.500: faltam 1.300 (ETF) e 450 (Ações); RF Pós já está acima de 50%
    assert "RF Pós" not in resto
    assert round(sum(resto.values()), 2) == 1500.0
    assert resto["ETF Internacional"] > resto["Ações BR"]
    # além de 3 meses, a reserva leva metade do aporte e a carteira a outra metade
    meta = {"proximo_degrau": {"nome": "Meta do plano", "meses": 6.0, "falta": 5000.0}}
    out = aporte_direcionado(classes, 10000.0, 2000.0, meta)
    assert out[0]["valor"] == 1000.0 and round(sum(x["valor"] for x in out[1:]), 2) == 1000.0


def test_banda_5_25_aperta_classes_pequenas(monkeypatch):
    from app.analytics.plano import BAND_ABS, BAND_REL
    assert min(BAND_ABS, BAND_REL * 0.40) == 0.05      # classe grande: 5 p.p.
    assert min(BAND_ABS, BAND_REL * 0.08) == pytest.approx(0.02)  # classe de 8%: ±2 p.p., não 3–13%


def test_calendario_fiscal_ir_regressivo():
    from app.analytics.plano import calendario_fiscal
    today = date(2026, 10, 20)
    pos = [{"type": "FIXED_INCOME", "subtype": "CDB", "name": "CDB X", "balance": 1000.0,
            "purchase_date": today - timedelta(days=170)},
           {"type": "FIXED_INCOME", "subtype": "LCI", "name": "LCI Y", "balance": 1000.0,
            "purchase_date": today - timedelta(days=170)},   # isenta: fora
           {"type": "FIXED_INCOME", "subtype": "CDB", "name": "CDB Z", "balance": 1000.0,
            "purchase_date": today - timedelta(days=100)},   # longe da troca de faixa
           {"type": "MUTUAL_FUND", "name": "Fundo DI", "balance": 500.0, "purchase_date": None}]
    cal = calendario_fiscal(pos, today)
    assert [(f["titulo"], f["dias"], f["de"], f["para"]) for f in cal["faixas"]] == [("CDB X", 11, 0.225, 0.20)]
    assert cal["come_cotas"] == date(2026, 11, 30)


# ---------------------------------------------------------------- poupar mais amanhã
def test_aumento_de_salario_sobe_a_meta_uma_vez(db_reset, monkeypatch):
    from app.analytics import plano
    s = db_reset()
    _setup(s)
    monkeypatch.setattr(plano, "today_brt", lambda: date(2026, 10, 15))
    for i, (y, m, v) in enumerate([(2026, 4, 5000), (2026, 5, 5000), (2026, 6, 5000), (2026, 7, 5000),
                                   (2026, 8, 5800), (2026, 9, 5800)]):
        s.add(_ev(f"s{i}", date(y, m, 5), float(v), "rec.salario", et="INCOME"))
    s.add(_ev("b13", date(2026, 7, 20), 5000.0, "rec.salario", et="INCOME"))  # pico isolado (férias): ignorado
    s.flush()
    r = plano.salary_raise(s)
    assert r == {"mes": "2026-08", "antes": 5000.0, "depois": 5800.0, "aumento": 800.0}
    # regra desligada: só pergunta
    assert [c.kind for c in plano.salary_raise_reviews(s)] == ["salary_raise"]
    plano.put_setting(s, "plano", {"meta_aporte_mensal": 1000.0, "aumento_para_aporte": 0.5})
    assert [c.kind for c in plano.salary_raise_reviews(s)] == ["salary_raise_applied"]
    assert plano.plan(s)["meta_aporte_mensal"] == 1400.0
    assert plano.salary_raise_reviews(s) == []          # o mesmo aumento não é aplicado de novo
    assert plano.plan(s)["meta_aporte_mensal"] == 1400.0


def test_mes_isolado_alto_nao_e_aumento(db_reset, monkeypatch):
    from app.analytics import plano
    s = db_reset()
    _setup(s)
    monkeypatch.setattr(plano, "today_brt", lambda: date(2027, 1, 15))
    for i, (y, m) in enumerate([(2026, 7), (2026, 8), (2026, 9), (2026, 10), (2026, 11), (2026, 12)]):
        s.add(_ev(f"s{i}", date(y, m, 5), 5000.0, "rec.salario", et="INCOME"))
    s.add(_ev("13o", date(2026, 12, 18), 5000.0, "rec.salario", et="INCOME"))  # 13º em dezembro
    s.flush()
    assert plano.salary_raise(s) is None


# ---------------------------------------------------------------- revisão por valor da informação
def test_impacto_prioriza_muito_dinheiro_incerto():
    from app.api.routes_ledger import review_impact
    grupo_incerto = {"total": -2000.0, "confidence": 0.35}          # 1.300
    lancamento_isolado = {"amount": -3000.0, "confidence": 0.9}      # 300
    salario_a_confirmar = {"amount": 4000.0, "confidence": 0.3, "monthly": True}  # 33.600 (vale o ano)
    ranked = sorted([grupo_incerto, lancamento_isolado, salario_a_confirmar], key=lambda d: -review_impact(d))
    assert ranked == [salario_a_confirmar, grupo_incerto, lancamento_isolado]
    assert review_impact(None) == 0.0


def test_previsao_inclui_anual_no_mes_do_vencimento(db_reset, monkeypatch):
    from app.analytics import overview
    from app.models import RecurringRule
    s = db_reset()
    _setup(s)
    monkeypatch.setattr(overview, "today_brt", lambda: date(2026, 10, 16))
    monkeypatch.setattr(overview, "current_position", lambda _s: {
        "totals": {"cash": 1000.0, "card_current": 0.0}, "installments": {"by_month": []}})
    s.add(RecurringRule(key="a:m:9", description="IPTU", direction="out", expected_amount=900.0, frequency_days=365,
                        last_date=date(2025, 12, 10), next_date=date(2026, 12, 10), status="detected"))
    s.flush()
    out = overview.liquidity_forecast(s, horizon=4)
    assert {m["month"]: m["annual"] for m in out["months"]} == {"2026-10": 0.0, "2026-11": 0.0, "2026-12": 900.0,
                                                               "2027-01": 0.0}
    assert out["months"][2]["end_cash"] == out["months"][1]["end_cash"] - 900.0
