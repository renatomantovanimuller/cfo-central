from datetime import date, timedelta

from sqlalchemy import select


def _month_with_income(sf):
    from app.models import FinancialEvent
    with sf() as s:
        e = s.scalars(select(FinancialEvent).where(FinancialEvent.event_type == "INCOME")
                      .order_by(FinancialEvent.amount.desc())).first()
        return e.source_id, e.competence_date.strftime("%Y-%m"), e.amount


def test_extraordinary_income_kept_out_of_recurring_result(synced):
    from app.accounting.management import dre_gerencial
    from app.accounting.statements import dre
    from app.api.routes_ledger import EventPatch, _apply_override
    from app.services.pipeline import pipeline
    sf = synced["sf"]
    sid, month, amount = _month_with_income(sf)
    # na massa fictícia o salário chega como Pix sem decisão (fora do recorrente): classifica como o usuário faria
    with sf() as s:
        _apply_override(s, sid, EventPatch(category_id="rec.salario", learn=False))
        s.commit()
    pipeline.rebuild_now("test")
    with sf() as s:
        before = {r["key"]: r["values"][month] for r in dre(s, [month], False)["rows"]}
        _apply_override(s, sid, EventPatch(category_id="rec.heranca"))
        s.commit()
    pipeline.rebuild_now("test")
    with sf() as s:
        after = {r["key"]: r["values"][month] for r in dre(s, [month], False)["rows"]}
        g = dre_gerencial(s, month)
    assert round(after["extraordinarios"], 2) == round(amount, 2)
    assert round(after["resultado_liquido"], 2) == round(before["resultado_liquido"] - amount, 2)
    assert round(after["resultado_total"], 2) == round(before["resultado_liquido"], 2)  # total não muda
    keys = {r["key"] for r in g["rows"]}
    assert {"resultado_liquido", "extraordinarios", "resultado_total"} <= keys
    assert {"media6", "delta", "orcamento", "ytd", "av"} <= set(g["rows"][0])
    assert "meses_de_reserva" in g["indicadores"]


def test_safe_to_spend_and_policy(synced):
    from app.analytics.plano import policy_report, policy_reviews, put_setting, safe_to_spend, set_targets
    sf = synced["sf"]
    with sf() as s:
        put_setting(s, "plano", {"meta_aporte_mensal": 1000.0})
        sts = safe_to_spend(s)
        assert sts["meta_aporte"] == 1000.0
        assert round(sts["disponivel"], 2) == round(sts["renda_prevista"] - 1000 - sts["gasto_ate_hoje"] - sts["comprometido"], 2)
        rep = policy_report(s)
        classes = [c["classe"] for c in rep["classes"]]
        assert classes and all(c["status"] == "sem alvo" for c in rep["classes"])
        set_targets(s, [{"asset_class": classes[0], "target_pct": 0.01}])  # força desvio
        s.commit()
        rep = policy_report(s)
        assert any(c["status"] == "acima" for c in rep["classes"])
        assert any(r.kind == "policy_drift" for r in policy_reviews(s))


def test_monte_carlo_monotonic_in_contribution():
    from app.analytics.plano import monte_carlo
    lo = monte_carlo(10_000, 100_000, 60, 500, 0.10, 0.10)
    hi = monte_carlo(10_000, 100_000, 60, 1500, 0.10, 0.10)
    assert 0 <= lo["probabilidade"] < hi["probabilidade"] <= 1
    assert lo["final_p10"] < lo["final_p50"] < lo["final_p90"]
    assert hi["trajetoria"][-1]["mes"] == 60


def test_fixed_income_and_equity_lots(synced):
    from app.models import FinancialEvent, Investment, InvestmentBalance
    from app.portfolio.realized import equity_lots, fixed_income_titles
    sf = synced["sf"]
    with sf() as s:
        fi = fixed_income_titles(s)
        assert fi["titulos"] and {"aplicado", "resultado", "pct_cdi", "historico_completo"} <= set(fi["titulos"][0])
        inv = s.get(Investment, "inv-bova")
        d0 = date.today() - timedelta(days=10)
        s.add(InvestmentBalance(investment_id=inv.id, date=d0 - timedelta(days=1), quantity=80, value=135.0, balance=10800))
        s.add(InvestmentBalance(investment_id=inv.id, date=d0, quantity=92, value=139.13, balance=12800))
        # débito bancário correspondente à compra de 12 cotas (valor exato vem do banco)
        acc = s.scalars(select(FinancialEvent.account_id)).first()
        s.add(FinancialEvent(source_type="test", source_id="buy-bova", split_seq=0, account_id=acc, item_id="x",
                             competence_date=d0, cash_date=d0, amount=-1650.0, event_type="INVESTMENT_CONTRIBUTION",
                             category_id="pat.aporte", description="Compra de renda variável", is_removed=False,
                             confidence=0.9, rule_source="structural", is_inferred=True, needs_review=False, is_pending=False))
        s.commit()
        rv = {a["ativo"]: a for a in equity_lots(s)["ativos"]}
    bova = rv["BOVA11"]
    assert bova["quantidade_com_custo"] == 12 and bova["custo_conhecido"] == 1650.0
    assert bova["quantidade_sem_custo"] == 80 and not bova["custo_completo"]
    assert bova["lotes"][-1]["origem"] == "banco"


def test_email_digest_sends_once(synced, monkeypatch):
    from app.alerts import notify
    from app.config.settings import get_settings
    st = get_settings()
    monkeypatch.setattr(st, "smtp_user", "eu@example.com")
    monkeypatch.setattr(st, "smtp_password", "x")
    sent = []
    monkeypatch.setattr(notify, "_send", lambda subj, body: sent.append(subj))
    sf = synced["sf"]
    with sf() as s:
        r1 = notify.daily_digest(s)
        s.commit()
        r2 = notify.daily_digest(s)
        s.commit()
        mc = notify.monthly_close(s)
        s.commit()
        mc2 = notify.monthly_close(s)
    assert r1["sent"] and not r2["sent"] and len([x for x in sent if "alerta" in x]) == 1
    assert mc["sent"] and not mc2["sent"]
