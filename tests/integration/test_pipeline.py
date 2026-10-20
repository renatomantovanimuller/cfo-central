from sqlalchemy import func, select

from app.accounting.statements import dre, dfc, month_list
from app.ingestion.pluggy_sync import sync_item
from app.models import (CardPaymentLink, CategoryRule, FinancialEvent, RawPayload, ReviewItem, Transaction)
from app.services.pipeline import pipeline
from tests.fixtures.fake_pluggy import ITEM_ID


def count(s, model):
    return s.scalar(select(func.count()).select_from(model))


def test_sync_is_idempotent(synced):
    sf, client = synced["sf"], synced["client"]
    with sf() as s:
        n_tx, n_raw = count(s, Transaction), count(s, RawPayload)
    sync_item(sf, client, ITEM_ID, full=True, trigger="test")
    with sf() as s:
        assert count(s, Transaction) == n_tx
        assert count(s, RawPayload) == n_raw  # mesmo hash → só last_seen_at muda


def test_pending_becomes_posted_soft_delete(synced):
    sf, client = synced["sf"], synced["client"]
    client.pending_variant = True
    sync_item(sf, client, ITEM_ID, full=True, trigger="test")
    pipeline.post_process("test")
    with sf() as s:
        old = s.get(Transaction, client._pending_id)
        assert old is not None and old.removed_at is not None  # nunca apagado
        ev = s.scalar(select(FinancialEvent).where(FinancialEvent.source_id == client._pending_id))
        assert ev.is_removed
        assert s.get(Transaction, "posted-" + client._pending_id[:8]) is not None


def test_card_payments_not_double_counted(synced):
    with synced["sf"]() as s:
        pays = s.scalars(select(FinancialEvent).where(FinancialEvent.description == "Pagamento de fatura")).all()
        assert pays and all(e.event_type == "CARD_PAYMENT" for e in pays)
        assert count(s, CardPaymentLink) == len(pays)
        side = s.scalars(select(FinancialEvent).where(FinancialEvent.description == "Pagamento recebido")).all()
        assert all(e.event_type == "CARD_PAYMENT" and e.amount > 0 for e in side)


def test_structural_classification(synced):
    with synced["sf"]() as s:
        def ev(desc):
            return s.scalars(select(FinancialEvent).where(FinancialEvent.description.like(f"{desc}%"))).all()
        assert all(e.event_type == "INVESTMENT_CONTRIBUTION" for e in ev("Aplicação RDB"))
        assert all(e.event_type == "INVESTMENT_REDEMPTION" for e in ev("Resgate RDB"))
        assert all(e.event_type == "EXTERNAL_OWN_TRANSFER" for e in ev("Transferência Recebida|FULANO"))
        assert all(e.event_type == "REFUND" and e.category_id == "transporte.apps" for e in ev("Estorno de Uber"))
        assert all(e.category_id == "assinaturas.software" for e in ev("Anthropic"))
        assert all(e.category_id == "moradia.aluguel" for e in ev("Pagamento efetuado|IMOBILIARIA"))
        uber = ev("Uber *Trip")
        assert uber and all(e.event_type == "EXPENSE" and e.amount < 0 for e in uber)


def test_salary_review_then_rule(synced):
    sf = synced["sf"]
    with sf() as s:
        kinds = {r.kind for r in s.scalars(select(ReviewItem).where(ReviewItem.status == "open"))}
        assert "pix_in_unknown" in kinds or "recurring_income" in kinds
        s.add(CategoryRule(field="cnpj", operator="equals", pattern="12345678000190", category_id="rec.salario",
                           origin="user"))
        s.commit()
    pipeline.post_process("test")
    with sf() as s:
        sal = s.scalars(select(FinancialEvent).where(FinancialEvent.description.like("%ACME%"))).all()
        assert sal and all(e.category_id == "rec.salario" and e.rule_source == "rule" for e in sal)
        open_fp = {r.fingerprint for r in s.scalars(select(ReviewItem).where(ReviewItem.status == "open"))}
        assert not any("pix_in_unknown" in fp and str(sal[0].merchant_id) in fp for fp in open_fp)


def test_dre_and_dfc_consistency(synced):
    with synced["sf"]() as s:
        months = month_list(n=6)
        d = dre(s, months, with_valuation=False)
        rows = {r["key"]: r for r in d["rows"]}
        m = months[-2]
        # resultado = soma das linhas
        parts = ["receita_operacional", "outras_receitas", "impostos_renda", "essenciais", "estilo_vida", "terceiros",
                 "nao_classificado", "receitas_financeiras", "despesas_financeiras"]
        assert abs(rows["resultado_liquido"]["values"][m] - sum(rows[p]["values"][m] for p in parts)) < 0.01
        # cartão entra por competência na DRE e só a fatura entra no caixa (DFC)
        f = dfc(s, months)
        faturas = next(l for sec in f["sections"] for l in sec["lines"] if l["key"] == "faturas")
        assert faturas["values"][m] < 0
        assert abs(f["closing_cash"][m] - f["opening_cash"][m] - f["net_change"][m]) < 0.01


def test_manual_override_wins_and_is_audited(synced):
    sf = synced["sf"]
    with sf() as s:
        e = s.scalars(select(FinancialEvent).where(FinancialEvent.description == "Netflix.com")).first()
        sid = e.source_id
        from app.models import EventOverride
        s.add(EventOverride(source_id=sid, category_id="lazer.outros"))
        s.commit()
    pipeline.post_process("user")
    with sf() as s:
        e = s.scalar(select(FinancialEvent).where(FinancialEvent.source_id == sid))
        assert e.category_id == "lazer.outros" and e.rule_source == "manual" and not e.is_inferred
        from app.models import LedgerAudit
        assert s.scalar(select(func.count()).select_from(LedgerAudit).where(LedgerAudit.source_id == sid)) >= 1
