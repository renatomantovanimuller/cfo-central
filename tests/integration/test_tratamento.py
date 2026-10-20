from datetime import timedelta

from sqlalchemy import select


def _rebuild():
    from app.services.pipeline import pipeline
    pipeline.rebuild_now("test")


def _event(s, tx_id):
    from app.models import FinancialEvent
    return s.scalar(select(FinancialEvent).where(FinancialEvent.source_id == tx_id))


def test_stale_pending_card_ignored_and_mcc_used(synced):
    from app.models import Account, Transaction
    from app.utils.time import today_brt
    sf = synced["sf"]
    with sf() as s:
        card = s.scalar(select(Account).where(Account.type == "CREDIT"))
        base = dict(account_id=card.id, item_id=card.item_id, currency="BRL", type="DEBIT")
        sign = card.card_sign or 1
        s.add(Transaction(id="t-stale", date=today_brt() - timedelta(days=70), amount=86.0 * -sign * -1 if sign < 0 else -86.0,
                          amount_brl=86.0 if sign < 0 else -86.0, flow=-86.0, status="PENDING", description="Loja X 3/3", **base))
        s.add(Transaction(id="t-barber", date=today_brt() - timedelta(days=3), amount=55.0 if sign < 0 else -55.0,
                          amount_brl=55.0 if sign < 0 else -55.0, flow=-55.0, status="POSTED", description="Zp*Liin Baber", mcc=7230,
                          pluggy_category_id="99999999", **base))
        s.commit()
    _rebuild()
    with sf() as s:
        st = _event(s, "t-stale")
        assert st.event_type == "IGNORE" and "pending_stale" in (st.review_reason or "")
        b = _event(s, "t-barber")
        assert b.category_id == "cuidados" and b.rule_id == "mcc:7230"


def test_income_merchant_outflow_not_negative_income(synced):
    from app.models import Account, FinancialEvent, Merchant, Transaction
    sf = synced["sf"]
    with sf() as s:
        inc = s.scalars(select(FinancialEvent).where(FinancialEvent.event_type == "INCOME",
                                                     FinancialEvent.merchant_id.is_not(None))).first()
        m = s.get(Merchant, inc.merchant_id)
        m.default_category_id, m.category_origin = "rec.salario", "user"
        src = s.get(Transaction, inc.source_id)
        s.add(Transaction(id="t-out-emp", account_id=src.account_id, item_id=src.item_id, date=src.date, amount=-60.0,
                          amount_brl=-60.0, flow=-60.0, status="POSTED", description="Transferência enviada|EMPRESA",
                          counterparty_name=src.counterparty_name, counterparty_doc=src.counterparty_doc,
                          receiver_doc=src.counterparty_doc, currency="BRL", type="DEBIT"))
        s.add(Transaction(id="t-devolvido", account_id=src.account_id, item_id=src.item_id, date=src.date, amount=44.5,
                          amount_brl=44.5, flow=44.5, status="POSTED", description="Pix enviado devolvido - Loja Y",
                          currency="BRL", type="CREDIT"))
        s.commit()
    _rebuild()
    with sf() as s:
        out = _event(s, "t-out-emp")
        assert out.event_type != "INCOME"
        assert _event(s, "t-devolvido").event_type == "REFUND"
