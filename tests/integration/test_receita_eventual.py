"""Bônus/PLR fica fora da receita recorrente e da taxa de poupança, mas entra no resultado total."""
from datetime import date


def test_bonus_vai_para_receitas_eventuais(db_reset):
    from app.accounting.statements import dre
    from app.categorization.chart import seed_chart
    from app.models import Account, Category, FinancialEvent, Institution, Item
    with db_reset() as s:
        seed_chart(s)
        s.add(Institution(id=1, name="Banco"))
        s.flush()
        s.add(Item(id="it", institution_id=1))
        s.flush()
        s.add(Account(id="a", item_id="it", type="BANK", name="Conta"))
        s.flush()
        assert s.get(Category, "rec.bonus").dre_line == "receitas_eventuais"

        def ev(i, cat, v, et="INCOME"):
            return FinancialEvent(source_type="transaction", source_id=i, account_id="a", competence_date=date(2026, 7, 5),
                                  cash_date=date(2026, 7, 5), amount=v, event_type=et, category_id=cat, rule_source="manual",
                                  confidence=1.0, description=i)
        s.add_all([ev("sal", "rec.salario", 4000.0), ev("plr", "rec.bonus", 10000.0),
                   ev("gasto", "alimentacao.mercado", -1000.0, "EXPENSE")])
        s.flush()
        d = dre(s, ["2026-07"], with_valuation=False)
        r = {x["key"]: x["values"]["2026-07"] for x in d["rows"]}
        assert r["receita_liquida"] == 4000.0
        assert r["receitas_eventuais"] == 10000.0
        assert r["resultado_liquido"] == 3000.0 and r["resultado_total"] == 13000.0
        assert abs(d["savings_rate"]["2026-07"] - 0.75) < 1e-9


def test_upgrade_nao_mexe_em_linha_que_o_usuario_mudou(db_reset):
    from app.categorization.chart import seed_chart
    from app.models import Category
    with db_reset() as s:
        seed_chart(s)
        c = s.get(Category, "rec.freela")
        c.dre_line = "outras_receitas"
        s.flush()
        seed_chart(s)
        assert s.get(Category, "rec.freela").dre_line == "outras_receitas"
