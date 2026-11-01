"""Pagamento de fatura entregue em dobro pela fonte: a cópia só sai quando a conta da fatura prova o erro."""
from datetime import date


def _setup(s, twin_bill: str | None = "b3"):
    from app.models import Account, CreditCardBill, Institution, Item, Transaction
    s.add(Institution(id=1, name="Banco"))
    s.flush()
    s.add(Item(id="it", institution_id=1))
    s.flush()
    s.add(Account(id="card", item_id="it", type="CREDIT", name="Cartão"))
    s.flush()
    s.add_all([CreditCardBill(id="b1", account_id="card", due_date=date(2026, 7, 31), total_amount=500.0),
               CreditCardBill(id="b2", account_id="card", due_date=date(2026, 8, 31), total_amount=800.0),
               CreditCardBill(id="b3", account_id="card", due_date=date(2026, 9, 30), total_amount=300.0)])

    def tx(i, d, desc, v, bill):
        return Transaction(id=i, account_id="card", item_id="it", date=d, description=desc, amount=v, amount_brl=v,
                           flow=-v, status="POSTED", bill_id=bill)
    s.add_all([
        tx("c1", date(2026, 8, 10), "Mercado", 800.0, "b2"),
        tx("p1", date(2026, 8, 31), "Pagamento recebido", -500.0, "b2"),   # paga a b1: está certo na b2
        tx("c2", date(2026, 9, 10), "Farmácia", 300.0, "b3"),
        tx("p2", date(2026, 9, 1), "Pagamento recebido", -800.0, "b3"),    # paga a b2
        tx("p2x", date(2026, 9, 1), "pagamento on line", -800.0, "b2"),    # mesma operação de novo, na b2
    ])
    if twin_bill is None:
        s.get(Transaction, "p2x").bill_id = None
    s.flush()
    # b2: 500 + (800 − 500) = 800 ✓ sem a cópia; com a cópia, 0 ✗
    s.get(Transaction, "p1").amount_brl = -500.0


def test_copia_que_quebra_a_fatura_e_descartada(db_reset):
    from app.accounting.bills import reconcile_bills
    from app.accounting.effective import DUP_PAYMENT, duplicate_card_payments, excluded_pending_ids
    with db_reset() as s:
        _setup(s)
        dup = duplicate_card_payments(s)
        assert dup == {"p2x": DUP_PAYMENT}
        assert "p2x" in excluded_pending_ids(s)
        bills = {b["id"]: b for b in reconcile_bills(s)["card"]}
        assert bills["b2"]["situacao"] == "ok" and bills["b3"]["situacao"] == "ok"
        assert len(bills["b2"]["duplicados_descartados"]) == 1


def test_sem_prova_pela_fatura_nada_e_descartado(db_reset):
    from app.accounting.effective import duplicate_card_payments
    from app.models import Transaction
    with db_reset() as s:
        _setup(s)
        # a b2 passa a fechar mesmo com os dois pagamentos: não há como provar que um deles é cópia
        s.get(Transaction, "c1").amount_brl = 1600.0
        s.flush()
        assert duplicate_card_payments(s) == {}


def test_pagamentos_iguais_em_dias_distantes_ficam(db_reset):
    from app.accounting.effective import duplicate_card_payments
    from app.models import Transaction
    with db_reset() as s:
        _setup(s)
        s.get(Transaction, "p2x").date = date(2026, 8, 20)
        s.flush()
        assert duplicate_card_payments(s) == {}
