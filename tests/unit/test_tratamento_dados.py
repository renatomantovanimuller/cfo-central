"""Regressões da revisão de tratamento de dados (datas, mapa Pluggy, conciliação, orçamento, parcelas, DFC)."""
from datetime import date
from types import SimpleNamespace

from app.categorization.chart import PLUGGY_MAP
from app.categorization.engine import TxView, keyword_category
from app.reconciliation.matching import card_payments, connected_card_issuers
from app.utils.time import local_date


def _tx(id, desc, flow, cat=None, doc=None, acc="a1", typ="BANK", d=date(2026, 1, 4), **kw):
    base = dict(id=id, account_id=acc, item_id="i1", account_type=typ, date=d, flow=flow, description=desc,
                description_raw=None, pluggy_cat=cat, merchant_name=None, merchant_cnpj=None, mcc=None,
                payment_method="PIX", counterparty_name=None, counterparty_doc=doc, payer_doc=None, receiver_doc=doc,
                status="POSTED", installment_number=None, total_installments=None, removed=False)
    return TxView(**{**base, **kw})


def test_meia_noite_utc_e_data_civil():
    # vencimento/lançamento "sem horário" não recua para o dia (e o mês) anterior
    assert local_date("2026-05-01T00:00:00.000Z") == date(2026, 5, 1)
    assert local_date("2026-05-01T03:00:00.000Z") == date(2026, 5, 1)  # meia-noite em Brasília
    assert local_date("2026-05-01T02:00:00Z") == date(2026, 4, 30)     # 23h do dia 30 em Brasília


def test_mapa_pluggy_so_tem_ids_de_8_digitos():
    bad = [k for k in PLUGGY_MAP if len(k) != 8]
    assert not bad
    assert PLUGGY_MAP["20030000"][0] == "saude.plano"  # plano de saúde → dedução no IR


def test_rendimento_fii_e_provento_nao_juros():
    assert keyword_category(_tx("t", "RENDIMENTO FII HGLG11", 12.3))[0] == "finrec.dividendos"
    assert keyword_category(_tx("t", "Rendimento da conta", 1.2))[0] == "finrec.juros"


def test_emissores_de_cartao_conectado():
    got = connected_card_issuers(["Nubank Ultravioleta", "Cartão Itaú Click", "Visa Internacional"])
    assert got == {"Nubank", "Itaú"}


def test_pagamento_ao_emissor_com_cartao_conectado_nao_vira_despesa():
    # Pix ao CNPJ do Nubank sem valor casado: com o cartão Nubank conectado é fatura (a conferir), não despesa
    pay = _tx("p1", "Pagamento de fatura Nu Pagamentos", -321.0, doc="18236120000158")
    dec, _ = card_payments([pay], [], {"cc1": "i1"}, set(), connected_issuers={"Nubank"})
    assert dec["p1"].event_type == "CARD_PAYMENT" and "card_payment_unmatched" in dec["p1"].review
    # sem o cartão daquele emissor, segue como cartão não conectado (despesa + revisão)
    dec, _ = card_payments([pay], [], {"cc1": "i1"}, set(), connected_issuers={"Itaú"})
    assert dec["p1"].event_type == "EXPENSE" and "card_not_connected" in dec["p1"].review


def test_orcamento_mae_e_filhas_nao_conta_em_dobro():
    from app.analytics.overview import rollup_budgets
    cats = {"moradia": SimpleNamespace(parent_id=None), "moradia.aluguel": SimpleNamespace(parent_id="moradia"),
            "moradia.energia": SimpleNamespace(parent_id="moradia"), "lazer": SimpleNamespace(parent_id=None),
            "lazer.viagens": SimpleNamespace(parent_id="lazer")}
    eff = rollup_budgets({"moradia": 3000.0, "moradia.aluguel": 2000.0, "lazer.viagens": 500.0}, cats)
    assert eff["moradia"] == 3000.0          # teto próprio da mãe vale (não 3000 + 2000)
    assert eff["moradia.aluguel"] == 2000.0
    assert eff["lazer"] == 500.0             # mãe sem orçamento próprio = soma das filhas
    assert "moradia.energia" not in eff


def test_parcela_com_centavos_diferentes_e_o_mesmo_plano(db_reset, monkeypatch):
    from app.accounting import balance
    from app.models import Account, FinancialEvent, Item, Transaction
    monkeypatch.setattr(balance, "today_brt", lambda: date(2026, 3, 10))
    s = db_reset()
    s.add(Item(id="i1"))
    s.flush()
    s.add(Account(id="cc1", item_id="i1", type="CREDIT"))
    # compra de 10x: 1ª parcela 33,37 e as demais 33,33 → chaves de parcelamento diferentes
    for n, (d, amt) in enumerate([(date(2026, 1, 5), -33.37), (date(2026, 2, 5), -33.33), (date(2026, 3, 5), -33.33)], 1):
        tid = f"t{n}"
        s.add(Transaction(id=tid, account_id="cc1", item_id="i1", date=d, amount=-amt, amount_brl=-amt, flow=amt,
                          installment_number=n, total_installments=10))
        s.add(FinancialEvent(source_id=tid, account_id="cc1", competence_date=d, amount=amt, event_type="EXPENSE",
                             category_id="compras.online", rule_source="manual", confidence=1.0,
                             installment_key=f"cc1|loja|10|{abs(amt)}"))
    s.flush()
    out = balance.future_installments(s)
    assert len(out["plans"]) == 1
    assert out["plans"][0]["remaining"] == 7          # 10 − 3, não 9 + 7
    assert round(out["total"], 2) == round(7 * 33.33, 2)


def test_dfc_ignora_pendente_duplicado_e_usa_data_de_caixa(db_reset):
    from app.accounting.statements import dfc
    from app.models import Account, FinancialEvent, Item
    s = db_reset()
    s.add(Item(id="i1"))
    s.flush()
    s.add(Account(id="b1", item_id="i1", type="BANK", balance=1000.0))
    common = dict(account_id="b1", rule_source="structural", confidence=1.0)
    s.add(FinancialEvent(source_id="posted", competence_date=date(2026, 2, 3), cash_date=date(2026, 2, 3),
                         amount=-100.0, event_type="EXPENSE", category_id="compras.online", **common))
    # gêmeo pendente do mesmo débito: fica fora do razão e do caixa
    s.add(FinancialEvent(source_id="pend", competence_date=date(2026, 2, 2), cash_date=date(2026, 2, 2),
                         amount=-100.0, event_type="IGNORE", category_id="pat.ignorar", rule_id="pending:superseded",
                         is_pending=True, **common))
    # competência ajustada para janeiro, mas o dinheiro saiu em fevereiro
    s.add(FinancialEvent(source_id="ajuste", competence_date=date(2026, 1, 31), cash_date=date(2026, 2, 10),
                         amount=-50.0, event_type="EXPENSE", category_id="compras.online", **common))
    s.flush()
    out = dfc(s, ["2026-01", "2026-02"])
    assert out["net_change"] == {"2026-01": 0.0, "2026-02": -150.0}


def test_pix_ao_banco_sem_evidencia_de_fatura_segue_categorizacao_normal():
    # seguro/consórcio/empréstimo pago ao CNPJ do banco: sem categoria nem descrição de fatura e sem valor casado
    seguro = _tx("s1", "Pix enviado Itau Seguros", -89.9, doc="60701190000104")
    dec, links = card_payments([seguro], [], {"cc1": "i1"}, set(), connected_issuers={"Itaú"})
    assert "s1" not in dec and not links
    # com valor casado com o crédito do cartão continua sendo fatura
    credit = _tx("c1", "Pagamento recebido", 89.9, acc="cc1", typ="CREDIT")
    dec, links = card_payments([seguro, credit], [], {"cc1": "i1"}, set())
    assert dec["s1"].event_type == "CARD_PAYMENT" and len(links) == 1


def test_entrada_a_classificar_nao_e_renda(db_reset):
    from app.accounting.statements import SPENDING_LINES, dre
    from app.analytics.overview import kpis_from_dre
    from app.categorization.chart import seed_chart
    from app.models import Account, FinancialEvent, Item
    s = db_reset()
    seed_chart(s)
    s.add(Item(id="i1"))
    s.flush()
    s.add(Account(id="b1", item_id="i1", type="BANK"))
    common = dict(account_id="b1", rule_source="default", confidence=0.5, event_type="INCOME")
    s.add(FinancialEvent(source_id="sal", competence_date=date(2026, 2, 5), amount=5000.0, category_id="rec.salario",
                         **common))
    s.add(FinancialEvent(source_id="pix", competence_date=date(2026, 2, 9), amount=300.0,
                         category_id="rec.pix_terceiros", **common))
    s.add(FinancialEvent(source_id="ir", competence_date=date(2026, 2, 20), amount=-400.0, category_id="impostos.ir",
                         account_id="b1", rule_source="default", confidence=0.8, event_type="TAX"))
    s.flush()
    d = dre(s, ["2026-02"], with_valuation=False)
    rows = {r["key"]: r["values"]["2026-02"] for r in d["rows"]}
    assert rows["receita_liquida"] == 4600.0          # 5000 − 400; o Pix sem decisão não é renda
    assert rows["entradas_a_classificar"] == 300.0
    assert rows["resultado_liquido"] == 4600.0
    assert rows["resultado_total"] == 4900.0
    k = kpis_from_dre(d)["2026-02"]
    assert k["a_classificar_entradas"] == 300.0
    assert k["despesas"] == -sum(rows[x] for x in SPENDING_LINES)   # impostos já saíram da receita


def test_regra_por_comerciante_sem_cnpj():
    from app.categorization.engine import compile_rules, match_rule
    from app.models import CategoryRule
    rule = CategoryRule(id=1, priority=10, field="merchant_id", operator="equals", pattern="42", active=True,
                        category_id="terceiros.pf", event_type="REFUND", direction=None, account_id=None,
                        amount_min=None, amount_max=None)
    tx = _tx("t", "Transferência recebida", 50.0)  # sem nome de contraparte nem documento
    rules = compile_rules([rule])
    assert match_rule(tx, rules, merchant_id=42) is rule
    assert match_rule(tx, rules, merchant_id=7) is None
    assert match_rule(tx, rules) is None
