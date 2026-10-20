from datetime import date

from app.categorization.engine import TxView
from app.reconciliation.matching import card_payments


def _tx(id, desc, flow, cat="05100000", cp=None, doc=None, acc="a1", typ="BANK"):
    return TxView(id=id, account_id=acc, item_id="i1", account_type=typ, date=date(2026, 1, 4), flow=flow,
                  description=desc, description_raw=None, pluggy_cat=cat, merchant_name=None, merchant_cnpj=None,
                  mcc=None, payment_method="PIX", counterparty_name=cp, counterparty_doc=doc, payer_doc=None,
                  receiver_doc=doc, status="POSTED", installment_number=None, total_installments=None, removed=False)


def test_pix_tuna_sem_fatura_casada_vira_despesa():
    tx = _tx("t1", "Pix enviado Tuna Pagamentos Ltda", -92.5, cp="TUNA PAGAMENTOS LTDA", doc="43098655000100")
    dec, links = card_payments([tx], [], {"cc1": "i1"}, set())
    assert dec["t1"].event_type == "EXPENSE"
    assert dec["t1"].category_id != "pat.fatura"
    assert dec["t1"].confidence < 0.5 and dec["t1"].review
    assert not links


def test_pagamento_real_de_fatura_continua_pagamento():
    pay = _tx("p1", "Pagamento de fatura", -500.0)
    credit = _tx("c1", "Pagamento recebido", 500.0, acc="cc1", typ="CREDIT")
    dec, links = card_payments([pay, credit], [], {"cc1": "i1"}, set())
    assert dec["p1"].event_type == "CARD_PAYMENT" and len(links) == 1


def test_gateway_com_credito_casado_e_pagamento():
    pay = _tx("p1", "Pix Tuna", -92.5, cp="Tuna")
    credit = _tx("c1", "Pagamento recebido", 92.5, acc="cc1", typ="CREDIT")
    dec, _ = card_payments([pay, credit], [], {"cc1": "i1"}, set())
    assert dec["p1"].event_type == "CARD_PAYMENT"
