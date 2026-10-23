"""Tela Hoje: missões, XP, sequência de dias, novidades desde a última conclusão e conquistas."""
from datetime import date


def test_sequencia_de_dias():
    from app.analytics.hoje import streak
    hoje = date(2026, 10, 23)
    assert streak([], hoje) == 0
    assert streak(["2026-10-21", "2026-10-22"], hoje) == 2              # hoje ainda pode ser concluído
    assert streak(["2026-10-21", "2026-10-22", "2026-10-23"], hoje) == 3
    assert streak(["2026-10-20", "2026-10-22"], hoje) == 1              # buraco no dia 21 quebra a sequência
    assert streak(["2026-10-20"], hoje) == 0


def test_dia_completo_com_xp_novidades_e_conquistas(synced):
    from app.analytics.hoje import acknowledge, check_in, today_view
    with synced["sf"]() as s:
        v = today_view(s)
        ids = {m["id"]: m for m in v["missoes"]}
        assert {"decisoes", "novidades", "ontem"} <= set(ids)
        assert v["novidades"]["quantidade"] > 0 and not ids["novidades"]["feito"]   # primeira visita: tudo é novo
        assert v["nivel"] == 1 and v["sequencia"] == 0 and not v["concluido_hoje"]
        assert {b["id"] for b in v["conquistas"]} >= {"colchao", "revisao_zero", "sequencia_7"}
        assert v["inventario"]["patrimonio_liquido"] and v["inventario"]["bolsos"][-1]["nome"] == "Livre"

        acknowledge(s, "novidades")
        acknowledge(s, "ontem")
        s.commit()
        v = today_view(s)
        feitos = [m for m in v["missoes"] if m["feito"]]
        assert {"novidades", "ontem"} <= {m["id"] for m in feitos}
        esperado = sum(m["xp"] for m in feitos)
        assert v["xp_disponivel"] == esperado

        r = check_in(s)
        s.commit()
        assert r["xp_ganho"] == esperado and r["sequencia"] == 1
        assert check_in(s)["xp_ganho"] == 0                                      # XP só uma vez por dia
        s.commit()
        v = today_view(s)
        assert v["concluido_hoje"] and v["sequencia"] == 1 and v["xp_total"] == esperado
        assert v["novidades"]["quantidade"] == 0                                  # contadas a partir da conclusão
