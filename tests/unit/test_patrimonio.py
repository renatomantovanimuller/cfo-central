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
