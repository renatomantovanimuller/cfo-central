from datetime import timedelta


def test_guia_facts_are_prioritized_and_stable(synced):
    from app.analytics.guia import NIVEIS, guia
    sf = synced["sf"]
    with sf() as s:
        a, b = guia(s), guia(s)
    assert a["itens"], "o cliente falso gera ao menos um aviso"
    niveis = [NIVEIS[i["nivel"]] for i in a["itens"]]
    assert niveis == sorted(niveis)
    assert [i["chave"] for i in a["itens"]] == [i["chave"] for i in b["itens"]]
    assert a["briefing"] is None and a["manchete"]["texto"]


def test_briefing_only_accepts_known_items_and_values(synced):
    from app.analytics.guia import guia, publicar_briefing, valores_permitidos
    sf = synced["sf"]
    with sf() as s:
        g = guia(s)
        alvo = g["itens"][-1]
        r = publicar_briefing(s, "Sobram R$ 123.456,78 este mês.")
        assert not r["ok"] and "R$ 123.456,78" in r["problemas"][0]
        r = publicar_briefing(s, "Ok.", [{"id": "inventado", "texto": "x"}])
        assert not r["ok"] and "inventado" in r["problemas"][0]
        valor = max(valores_permitidos(g))
        real = f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        r = publicar_briefing(s, f"Ponto principal envolve {real}.", [{"id": alvo["id"], "texto": "Faça isto primeiro."}])
        assert r["ok"], r
        s.commit()
        g2 = guia(s)
    assert g2["briefing"]["resumo"].startswith("Ponto principal")
    assert g2["itens"][0]["id"] == alvo["id"] and g2["itens"][0]["texto_claude"] == "Faça isto primeiro."
    assert {i["id"] for i in g2["itens"]} == {i["id"] for i in g["itens"]}  # o Claude reordena, não remove


def test_stale_briefing_falls_back_to_facts(synced):
    from app.analytics.guia import BRIEFING_KEY, guia, publicar_briefing
    from app.models import AppSetting
    from app.utils.time import utcnow
    sf = synced["sf"]
    with sf() as s:
        assert publicar_briefing(s, "Resumo de ontem.")["ok"]
        row = s.get(AppSetting, BRIEFING_KEY)
        row.value = {**row.value, "gerado_em": (utcnow() - timedelta(hours=40)).isoformat()}
        s.commit()
        g = guia(s)
    assert g["briefing"] is None and g["briefing_ultimo"]
    assert not any("texto_claude" in i for i in g["itens"])
