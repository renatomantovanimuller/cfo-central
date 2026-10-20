from datetime import date

from collections import Counter

from app.accounting.ledger import _decide
from app.categorization.engine import TxView


def _tx(desc, flow=-120.0, pcat="04000000", mcc=None, typ="CREDIT", party=None):
    return TxView(id="t1", account_id="a1", item_id="i1", account_type=typ, date=date(2026, 1, 4), flow=flow,
                  description=desc, description_raw=None, pluggy_cat=pcat, merchant_name=party, merchant_cnpj=None,
                  mcc=mcc, payment_method="CREDIT_CARD", counterparty_name=party, counterparty_doc=None,
                  payer_doc=None, receiver_doc=None, status="POSTED", installment_number=None,
                  total_installments=None, removed=False)


class _Cat:
    def __init__(self, nature="despesa"):
        self.nature = nature


CATS = {k: _Cat() for k in ("terceiros.pf", "terceiros.pj", "compras.diversos", "transporte.estacionamento",
                            "transporte.combustivel", "alimentacao.restaurantes")}
PMAP = {"04000000": ("terceiros.pf", 0.6)}


def _run(tx):
    return _decide(tx, None, [], {}, None, PMAP, CATS, Counter())


def test_compra_no_cartao_com_categoria_transferencias_nao_vira_pix_pf():
    d = _run(_tx("Restaurante Sabor Ltda"))
    assert d.category_id == "alimentacao.restaurantes"
    d = _run(_tx("Loja Qualquer 123"))
    assert not d.category_id.startswith("terceiros")
    assert d.event_type == "EXPENSE" and d.category_id == "compras.diversos"


def test_compra_no_cartao_usa_mcc_quando_pluggy_diz_transferencias():
    d = _run(_tx("Estabelecimento X", mcc=5541))
    assert d.category_id == "transporte.combustivel"


def test_conta_corrente_continua_pix_pf():
    d = _run(_tx("Pix enviado Joao", typ="BANK"))
    assert d.category_id == "terceiros.pf"


def test_tag_de_pedagio_no_cartao_vai_para_pedagio():
    for desc in ("Sem Parar", "CONECTCAR", "Veloe Tag", "Move Mais", "TAG pedagio"):
        d = _run(_tx(desc))
        assert d.category_id == "transporte.estacionamento", desc
        assert d.event_type == "EXPENSE"
