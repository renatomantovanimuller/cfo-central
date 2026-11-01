"""Benefício VR/VA informado: crédito e consumo mensais gerados no razão, sem tocar no caixa."""
from datetime import date

CFG = {"itens": [{"id": "vr", "nome": "Vale-refeição", "fornecedor": "Pluxee", "dia": 5,
                  "valores": [{"desde": "2026-07", "valor": 800}, {"desde": "2026-09", "valor": 900}]}]}


def test_creditos_mensais_respeitam_reajuste_e_dia():
    from app.accounting.benefits import monthly_credits, normalize
    cfg = normalize(CFG)
    got = [(c["month"], c["valor"]) for c in monthly_credits(cfg, today=date(2026, 10, 4))]
    # outubro ainda não teve crédito (dia 5)
    assert got == [("2026-07", 800.0), ("2026-08", 800.0), ("2026-09", 900.0)]
    got = monthly_credits(cfg, today=date(2026, 10, 5))
    assert got[-1]["month"] == "2026-10" and got[-1]["valor"] == 900.0


def test_configuracao_invalida_nao_gera_nada():
    from app.accounting.benefits import monthly_credits, normalize
    cfg = normalize({"itens": [{"nome": "x", "valores": [{"desde": "2026-13", "valor": 10}]},
                               {"nome": "y", "valores": [{"desde": "2026-01", "valor": -5}]}]})
    assert cfg["itens"] == [] and monthly_credits(cfg) == []
    cfg = normalize({"itens": [{"nome": "z", "dia": 31, "ativo": False, "valores": [{"desde": "2026-01", "valor": 5}]}]})
    assert cfg["itens"][0]["dia"] == 28 and monthly_credits(cfg) == []


def test_eventos_entram_na_dre_e_nao_no_caixa(db_reset):
    from sqlalchemy import select
    from app.accounting.benefits import save_config, sync_benefit_events
    from app.accounting.statements import dfc, dre
    from app.categorization.chart import seed_chart
    from app.models import FinancialEvent
    with db_reset() as s:
        seed_chart(s)
        save_config(s, CFG)
        n = sync_benefit_events(s, today=date(2026, 9, 30))
        assert n == 6
        assert sync_benefit_events(s, today=date(2026, 9, 30)) == 6  # idempotente
        evs = s.scalars(select(FinancialEvent).where(FinancialEvent.source_type == "benefit")).all()
        assert len(evs) == 6 and abs(sum(e.amount for e in evs)) < 1e-9
        d = dre(s, ["2026-09"], with_valuation=False)
        r = {x["key"]: x["values"]["2026-09"] for x in d["rows"]}
        assert r["receita_liquida"] == 900.0
        assert r["resultado_liquido"] == 0.0
        f = dfc(s, ["2026-09"])
        assert abs(f["net_change"].get("2026-09", 0.0)) < 1e-9


def test_rotas_do_beneficio(db_reset, monkeypatch):
    from app.api import routes_ledger as L
    from app.api import routes_system as R
    from app.categorization.chart import seed_chart

    class NoNet:
        def request(self, *a, **k):
            raise RuntimeError("sem rede")
    monkeypatch.setattr(type(R.pipeline), "client", property(lambda self: NoNet()))
    with db_reset() as s:
        seed_chart(s)
        out = R.save_benefits(CFG, s)
        assert out["config"]["itens"][0]["fornecedor"] == "Pluxee" and out["meses"] >= 3
        assert out["pluggy"]["erro"].startswith("RuntimeError")
        det = L.event_detail("benef:vr:2026-09:credito", s)
        assert det["benefit"] and det["transaction"] is None and det["event"]["amount"] == 900.0
