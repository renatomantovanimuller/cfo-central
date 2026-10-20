from datetime import date, timedelta

from sqlalchemy import select


def _rebuild():
    from app.services.pipeline import pipeline
    return pipeline.rebuild_now("test")


def _check(report, cid):
    return next(c for c in report["verificacoes"] if c["id"] == cid)


def test_health_runs_with_rebuild_and_flags_problems(synced):
    from app.health.checks import latest, run_checks
    from app.models import ReviewItem, SyncEvent, SyncRun, Transaction
    sf = synced["sf"]
    post = _rebuild()
    assert "saude" in post
    with sf() as s:
        rep = latest(s)
        assert rep and len(rep["verificacoes"]) >= 10
        assert _check(rep, "razao")["status"] == "ok"
        # lançamento sumiu do razão → falha; erro na última sincronização → falha
        tx = s.scalars(select(Transaction).where(Transaction.removed_at.is_(None))).first()
        run = s.scalars(select(SyncRun).where(SyncRun.kind == "pluggy").order_by(SyncRun.id.desc())).first()
        s.add(SyncEvent(run_id=run.id, level="error", step="transactions:Conta", message="operator does not exist"))
        s.add(Transaction(id="t-orfa", account_id=tx.account_id, item_id=tx.item_id, date=tx.date, amount=-10.0,
                          amount_brl=-10.0, flow=-10.0, status="POSTED", description="sem evento", currency="BRL"))
        s.commit()
        rep2 = run_checks(s)
        assert _check(rep2, "razao")["status"] == "falha"
        assert _check(rep2, "sync")["status"] == "falha"
        assert rep2["status"] == "falha"
    _rebuild()  # o razão volta a ficar completo; o erro de sync continua e vira revisão grave
    with sf() as s:
        rep3 = latest(s)
        assert _check(rep3, "razao")["status"] == "ok"
        rv = s.scalars(select(ReviewItem).where(ReviewItem.kind == "data_health", ReviewItem.status == "open")).all()
        assert any(r.entity_id == "sync" and r.severity == "high" for r in rv)


def test_bill_identity_check(synced):
    from app.health.checks import check_bills
    from app.models import Account, CreditCardBill, Transaction
    from app.utils.time import today_brt
    sf = synced["sf"]
    with sf() as s:
        item = s.scalar(select(Account.item_id))
        s.add(Account(id="card-x", item_id=item, type="CREDIT", name="Cartão X"))
        s.add(CreditCardBill(id="b1", account_id="card-x", due_date=date(2026, 8, 1), total_amount=500.0))
        s.add(CreditCardBill(id="b2", account_id="card-x", due_date=date(2026, 9, 1), total_amount=620.0))
        for i, v in enumerate((-500.0, 300.0, 320.0)):  # pagamento da anterior + compras
            s.add(Transaction(id=f"bx{i}", account_id="card-x", item_id=item, date=date(2026, 8, 5 + i), amount=v,
                              amount_brl=v, flow=-v, status="POSTED", description=f"c{i}", bill_id="b2"))
        s.flush()
        c = check_bills(s, today_brt())
        assert not [d for d in c.detalhes if d["cartao"] == "Cartão X"]
        s.get(CreditCardBill, "b2").total_amount = 670.0
        s.flush()
        c = check_bills(s, today_brt())
        bad = [d for d in c.detalhes if d["cartao"] == "Cartão X"]
        assert c.status == "falha" and bad[0]["diferenca"] == 50
        s.rollback()


def test_investment_episode_matching():
    from app.health.checks import _clusters
    d = date(2026, 7, 18)
    pts = [(d, "c_sell", 1337.55, ""), (d, "c_sell", 1063.78, ""), (d + timedelta(days=1), "b_in", 2380.0, ""),
           (d + timedelta(days=20), "c_buy", 500.0, ""), (d + timedelta(days=21), "b_out", 500.0, "")]
    cl = _clusters(pts)
    assert len(cl) == 2 and len(cl[0]) == 3


def test_irpf_report_sections(synced):
    from app.models import Account, Transaction
    from app.tax.irpf import _compensate, irpf_report, irpf_xlsx
    from app.utils.time import today_brt
    sf = synced["sf"]
    ano = today_brt().year
    with sf() as s:
        bank = s.scalar(select(Account).where(Account.type == "BANK"))
        base = dict(account_id=bank.id, item_id=bank.item_id, currency="BRL", status="POSTED")
        d = date(ano, 2, 10)
        s.add(Transaction(id="t-psi1", date=d, amount=-300.0, amount_brl=-300.0, flow=-300.0, type="DEBIT",
                          description="Transferência enviada|Clinica Teste", counterparty_name="Clinica Teste",
                          counterparty_doc="12345678901", **base))
        s.add(Transaction(id="t-psi2", date=d + timedelta(days=30), amount=-300.0, amount_brl=-300.0, flow=-300.0,
                          type="DEBIT", description="Transferência enviada|Clinica Teste",
                          counterparty_name="Clinica Teste", counterparty_doc="12345678901", **base))
        s.add(Transaction(id="t-her", date=d, amount=5000.0, amount_brl=5000.0, flow=5000.0, type="CREDIT",
                          description="Transferência recebida|Espolio", counterparty_name="Espolio", **base))
        s.commit()
    from app.models import EventOverride
    with sf() as s:
        s.add(EventOverride(source_id="t-psi1", category_id="saude.consultas"))
        s.add(EventOverride(source_id="t-psi2", category_id="saude.consultas"))
        s.add(EventOverride(source_id="t-her", category_id="rec.heranca"))
        s.commit()
    _rebuild()
    with sf() as s:
        r = irpf_report(s, ano)
        assert r["ano_base"] == ano and r["bens_e_direitos"]
        assert any(b["grupo"] == "06" for b in r["bens_e_direitos"])
        psi = next(p for p in r["pagamentos"] if p["prestador"] == "Clinica Teste")
        assert psi["pago"] == 600 and psi["cpf_cnpj"] == "123.456.789-01"
        her = next(i for i in r["isentos"] if i["codigo"] == "14")
        assert her["valor"] == 5000
        assert any("CPF do doador" in p for p in r["pendencias"])
        assert len(r["renda_variavel"]["meses"]) == 12
        assert irpf_xlsx(s, ano)[:2] == b"PK"
    assert _compensate(100.0, 30.0) == (70.0, 0.0)
    assert _compensate(-50.0, 30.0) == (0.0, 80.0)
    assert _compensate(20.0, 30.0) == (0.0, 10.0)


def test_classifier_learns_and_respects_guards():
    from app.categorization.chart import seed_chart
    from app.categorization.engine import Decision, TxView
    from app.categorization.model import apply_model
    from app.database.migrate import migrate
    from app.database.session import session_factory
    from app.models import Category
    migrate()
    sf = session_factory()

    def tx(i, desc, flow, merchant=None, doc=None, pcat="99999999"):
        return TxView(id=f"m{i}", account_id="a", item_id="i", account_type="CREDIT" if flow < 0 else "BANK",
                      date=date(2026, 5, 1) + timedelta(days=i % 90), flow=flow, description=desc, description_raw=None,
                      pluggy_cat=pcat, merchant_name=merchant, merchant_cnpj=None, mcc=None, payment_method=None,
                      counterparty_name=None, counterparty_doc=doc, payer_doc=None, receiver_doc=None, status="POSTED",
                      installment_number=None, total_installments=None, removed=False)

    decided = {}
    i = 0
    for desc, cat in (("PADARIA PAO DOURADO", "alimentacao.padaria"), ("POSTO SHELL AVENIDA", "transporte.combustivel"),
                      ("DROGARIA SAO PAULO", "saude.farmacia"), ("CINEMARK SHOPPING", "lazer.eventos")):
        for k in range(25):
            t = tx(i, f"{desc} {k}", -20.0 - k)
            decided[t.id] = (t, Decision(cat, None, "heuristic", f"keyword:{cat}", 0.9), None, None)
            i += 1
    # candidatos fracos: categoria genérica da Pluggy
    weak = tx(900, "PADARIA PAO DOURADO FILIAL", -18.0)
    decided[weak.id] = (weak, Decision("compras.diversos", None, "pluggy_map", "pluggy:x", 0.5), None, None)
    manual = tx(901, "PADARIA PAO DOURADO", -15.0)
    decided[manual.id] = (manual, Decision("lazer.outros", None, "manual", "override:1", 1.0), None, None)
    person = tx(902, "Transferência enviada|Fulano", -50.0, doc="12345678901")
    decided[person.id] = (person, Decision("terceiros.pf", None, "pluggy_map", "pluggy:y", 0.5), None, None)
    with sf() as s:
        seed_chart(s)
        cats = {c.id: c for c in s.scalars(select(Category))}
        info = apply_model(s, decided, cats)
        s.commit()
    assert info["habilitado"], info
    assert decided["m900"][1].category_id == "alimentacao.padaria" and decided["m900"][1].rule_source == "modelo"
    assert "padaria" in decided["m900"][1].rule_id
    assert decided["m901"][1].rule_source == "manual"  # ajuste manual intocado
    assert decided["m902"][1].category_id == "terceiros.pf"  # Pix para pessoa: decisão do usuário


def test_incremental_sync_has_no_step_errors(synced):
    """Regressão: a releitura incremental comparava DATE com texto (passava no SQLite, quebrava no Postgres)."""
    from app.ingestion.pluggy_sync import sync_item
    from tests.fixtures.fake_pluggy import ITEM_ID
    res = sync_item(synced["sf"], synced["client"], ITEM_ID, full=False, trigger="test")
    assert res["status"] == "ok", res.get("warnings")
