"""Controle do patrimônio: rótulo de instituição, liquidez de 1 dia, visão consolidada, bolsos, metas, aportes,
ponte do patrimônio, ativos manuais, evolução e projeção."""


def test_rotulo_unico_de_instituicao(db_reset):
    from app.accounting.institutions import institution_labels
    from app.models import Account, Institution, Item
    s = db_reset()
    s.add_all([Institution(id=1, name="MeuPluggy"), Institution(id=2, name="Banco Inter")])
    s.flush()
    s.add_all([Item(id="agg", institution_id=1), Item(id="inter", institution_id=2),
               Item(id="apelido", institution_id=1, nickname="Nubank")])
    s.flush()
    s.add_all([Account(id="c1", item_id="agg", type="CREDIT", name="Nubank Ultravioleta"),
               Account(id="b1", item_id="agg", type="BANK", name="NU PAGAMENTOS S.A. - INSTITUIÇÃO DE PAGAMENTO"),
               Account(id="b2", item_id="inter", type="BANK", name="Conta Inter")])
    s.flush()
    labels = institution_labels(s)
    assert labels == {"agg": "Nu Pagamentos", "inter": "Banco Inter", "apelido": "Nubank"}


def test_disponivel_em_um_dia_nao_passa_do_patrimonio(synced):
    from app.accounting.balance import current_position
    from app.accounting.management import reserva_liquida
    with synced["sf"]() as s:
        pos = current_position(s)
        t = pos["totals"]
        assert t["liquid_net_worth"] == reserva_liquida(s, pos)
        assert t["liquid_net_worth"] <= t["financial_net_worth"]
        assert t["liquid_net_worth"] < t["cash"] + t["investments"]  # CDB no vencimento, ETF etc. ficam de fora


# ---------------------------------------------------------------- bolsos
def _pos(cash=(("b1", 5000.0),), inv=(("cdb", 10000.0, "RF Pós", "D0"), ("etf", 8000.0, "ETF Ações BR", "D2"))):
    return {"cash": [{"account_id": a, "name": a, "institution": "Banco", "balance": v} for a, v in cash],
            "positions": [{"id": i, "name": i, "institution": "Banco", "balance": v, "asset_class": c, "liquidity": lq}
                          for i, v, c, lq in inv],
            "manual_assets": [], "totals": {"cash": sum(v for _, v in cash), "net_worth": 0, "investments": 18000},
            "investments_by_class": {}}


def test_fonte_nao_passa_de_100_por_cento_entre_bolsos(db_reset):
    import pytest
    from app.analytics.bolsos import bucket_values, set_allocations
    from app.models import Bucket
    s = db_reset()
    a, b = Bucket(name="Viagem", kind="objetivo"), Bucket(name="Carro", kind="objetivo")
    s.add_all([a, b])
    s.flush()
    set_allocations(s, a.id, [{"source_type": "investment", "source_id": "cdb", "pct": 0.6}])
    with pytest.raises(ValueError):
        set_allocations(s, b.id, [{"source_type": "investment", "source_id": "cdb", "pct": 0.5}])
    set_allocations(s, b.id, [{"source_type": "investment", "source_id": "cdb", "pct": 0.4}])
    vals = bucket_values(s, _pos())["by_bucket"]
    assert vals == {a.id: 6000.0, b.id: 4000.0}   # os 10 mil do CDB divididos, nunca contados duas vezes


def test_conta_com_finalidade_reserva_vale_como_bolso(db_reset):
    from app.analytics.bolsos import bucket_values, ensure_reserve_bucket
    from app.models import Account, AccountSetting, Item
    s = db_reset()
    s.add(Item(id="i1"))
    s.flush()
    s.add(Account(id="b1", item_id="i1", type="BANK"))
    s.add(AccountSetting(account_id="b1", purpose="reserva"))
    ensure_reserve_bucket(s)
    s.flush()
    assert bucket_values(s, _pos())["reserve"] == 5000.0


def test_metas_pelo_bolso_e_meta_antiga_marcada(db_reset, monkeypatch):
    from datetime import date
    from app.analytics import metas
    from app.analytics.bolsos import set_allocations
    from app.models import Bucket, FinancialGoal
    monkeypatch.setattr(metas, "today_brt", lambda: date(2026, 10, 1))
    s = db_reset()
    g1 = FinancialGoal(name="Viagem", target_amount=12000, target_date=date(2027, 10, 1), basis="bucket",
                       expected_return_aa=0.0, priority=1)
    g2 = FinancialGoal(name="Tudo", target_amount=50000, basis="investments", priority=2)
    s.add_all([g1, g2])
    s.flush()
    b = Bucket(name="Viagem", kind="objetivo", goal_id=g1.id)
    s.add(b)
    s.flush()
    set_allocations(s, b.id, [{"source_type": "investment", "source_id": "etf", "pct": 0.75}])
    st = {g["name"]: g for g in metas.goals_status(s, _pos())}
    assert st["Viagem"]["current"] == 6000.0 and st["Viagem"]["monthly_needed"] == 500.0  # 6 mil em 12 meses
    assert st["Viagem"]["avisos"] and "renda variável" in st["Viagem"]["avisos"][0]       # prazo curto em ETF
    assert st["Tudo"]["legacy"] and "mesmo dinheiro" in st["Tudo"]["avisos"][0]


def test_plano_de_aportes_reserva_metas_por_prioridade_e_carteira():
    from app.analytics.metas import contribution_plan
    reserva = {"proximo_degrau": {"nome": "Colchão inicial", "meses": 1.0, "falta": 300.0}}
    goals = [{"id": 1, "name": "A", "monthly_needed": 500.0, "legacy": False, "target_date": None},
             {"id": 2, "name": "B", "monthly_needed": 400.0, "legacy": False, "target_date": None}]
    plan = contribution_plan(1000.0, reserva, goals, [], 0.0)
    assert [(d["destino"], d["valor"]) for d in plan["destinos"]] == [("Reserva de emergência", 300.0), ("A", 500.0),
                                                                     ("B", 200.0)]
    m = {x["name"]: x for x in plan["metas"]}
    assert m["A"]["status"] == "no ritmo" and m["B"]["status"] == "atrasada" and m["B"]["falta_aporte"] == 200.0
    assert plan["falta_para_metas"] == 200.0
    folga = contribution_plan(2000.0, {"proximo_degrau": None}, goals, [], 0.0)
    assert folga["destinos"][-1]["destino"] == "Carteira (livre)" and folga["destinos"][-1]["valor"] == 1100.0


def test_api_meta_cria_bolso_edita_e_apaga(synced):
    from app.api import routes_reports as R
    from app.models import Bucket
    with synced["sf"]() as s:
        res = R.create_goal(R.GoalBody(name="Entrada do apê", target_amount=80000), db=s)
        s.commit()
        assert s.get(Bucket, res["bucket_id"]).name == "Entrada do apê"
        R.patch_goal(res["id"], R.GoalPatch(name="Entrada do apartamento", priority=1, kind="prazo"), db=s)
        s.commit()
        assert s.get(Bucket, res["bucket_id"]).name == "Entrada do apartamento"
        sug = R.suggest_reserve(db=s)
        assert not sug["criado"] and "manualmente" in sug["motivo"]  # massa fictícia: CDB só no vencimento
        reserva = sug["bolsos"]["bolsos"][0]
        assert reserva["tipo"] == "reserva"
        cdb = next(f for f in sug["bolsos"]["fontes"] if f["classe"] == "RF Pós")
        R.put_allocations(reserva["id"], [R.AllocationItem(source_type="investment", source_id=cdb["id"], pct=0.5)],
                          db=s)
        p = R.planning(db=s)
        assert p["politica"]["reserva"]["fonte"] == "bolso"
        meta = next(g for g in p["goals"] if g["name"] == "Entrada do apartamento")
        assert meta["bucket_id"] == res["bucket_id"] and meta["current"] == 0.0
        R.delete_goal(res["id"], db=s)
        s.commit()
        assert s.get(Bucket, res["bucket_id"]) is None


def test_visao_consolidada_soma_o_patrimonio_liquido(synced):
    from app.analytics.patrimonio import consolidated
    with synced["sf"]() as s:
        v = consolidated(s)
        assert abs(v["total"] - v["patrimonio_liquido"]) < 0.02
        faixas = {i["faixa"] for i in v["itens"]}
        assert {"Em 1 dia", "Dívida"} <= faixas and faixas <= set(v["faixas"])
        etf = next(i for i in v["itens"] if i["classe"] == "ETF Ações BR")
        assert etf["faixa"] == "Até 30 dias, com oscilação" and etf["bolsos"][0]["nome"] == "Livre"
        conta = next(i for i in v["itens"] if i["tipo"] == "conta")
        assert conta["conferencia"]["status"] in ("ok", "atencao", "falha")


# ---------------------------------------------------------------- itens manuais, ponte, evolução, projeção
def test_item_manual_com_historico_e_aquisicao(db_reset):
    from datetime import date
    from types import SimpleNamespace
    from app.accounting.manual import value_at
    casa = SimpleNamespace(as_of=date(2026, 10, 1), value=500000.0, acquired_at=date(2020, 3, 1), growth_aa=0.05)
    pts = [(date(2026, 10, 1), 500000.0)]
    assert value_at(casa, pts, date(2019, 12, 31)) == 0.0                       # antes da compra não existia
    assert round(value_at(casa, pts, date(2027, 10, 1))) == round(500000 * 1.05 ** (365 / 365.25))
    assert value_at(casa, pts, date(2025, 10, 1)) < 500000.0                     # recuado pelo índice
    carro = SimpleNamespace(as_of=date(2026, 10, 1), value=80000.0, acquired_at=None, growth_aa=-0.1)
    assert value_at(carro, [(date(2026, 10, 1), 80000.0)], date(2026, 9, 1)) == 0.0  # sem data: não inventa o passado
    assert value_at(carro, [(date(2026, 10, 1), 80000.0), (date(2027, 4, 1), 70000.0)], date(2027, 4, 1)) == 70000.0


def test_cadastro_manual_nao_altera_patrimonio_passado(synced):
    from datetime import date
    from app.accounting.balance import history
    from app.api import routes_reports as R
    with synced["sf"]() as s:
        antes = {h["date"]: h["net_worth"] for h in history(s, 6)}
        R.create_manual(R.ManualBody(kind="asset", name="Apartamento", value=400000.0), db=s)
        s.commit()
        depois = {h["date"]: h["net_worth"] for h in history(s, 6)}
        meses_passados = [d for d in antes if date.fromisoformat(d) < date.today().replace(day=1)]
        assert meses_passados and all(abs(depois[d] - antes[d]) < 0.01 for d in meses_passados)
        lista = R.manual_assets(db=s)
        assert lista[0]["valor_atual"] == 400000.0 and len(lista[0]["historico"]) == 1


def test_ponte_evolucao_e_projecao(synced):
    from app.analytics.patrimonio import bridge, evolution, projection
    with synced["sf"]() as s:
        b = bridge(s, 6)
        assert b["meses"]
        for m in b["meses"]:
            parts = m["poupanca"] + m["extraordinarios"] + (m["valorizacao"] or 0) + m["manuais"] + m["nao_explicado"]
            assert abs((m["fim"] - m["inicio"]) - parts) < 0.05      # a ponte sempre fecha
        e = evolution(s, 6)
        assert e["meses_com_dado"] >= 1 and e["por_classe"]
        p = projection(s, years=10, alvo=1_000_000)
        assert [m["anos"] for m in p["marcos"]] == [1, 5, 10]
        assert p["marcos"][0]["p10"] <= p["marcos"][0]["p50"] <= p["marcos"][0]["p90"]
        assert 0 <= p["probabilidade_alvo"] <= 1
