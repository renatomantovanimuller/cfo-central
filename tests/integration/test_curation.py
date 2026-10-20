from sqlalchemy import select


def test_curation_is_idempotent_and_reports_bad_input(synced):
    from app.models import AccountSetting, CategoryRule, EventOverride, Merchant, Transaction
    from app.services.curation import apply_curation

    sf = synced["sf"]
    with sf() as s:
        tx = s.scalars(select(Transaction)).first()
        data = {
            "accounts": [{"match": {"type": "BANK"}, "nickname": "Conta principal"}],
            "merchants": [{"doc": "11.222.333/0001-81", "name": "Loja X", "category": "compras.diversos"}],
            "rules": [{"name": "r1", "pattern": "padaria", "category": "alimentacao.restaurantes"},
                      {"name": "ruim", "pattern": "x", "category": "nao.existe"}],
            "overrides": [{"tx_id": tx.id, "category": "rec.bonus"}, {"tx_id": "nao-existe", "category": "rec.bonus"}],
        }
        r1 = apply_curation(s, data)
        r2 = apply_curation(s, data)
        s.commit()
        assert r1["skipped"] and len(r2["skipped"]) == len(r1["skipped"])
        assert s.scalar(select(Merchant).where(Merchant.cnpj == "11222333000181")).default_category_id == "compras.diversos"
        assert len(s.scalars(select(CategoryRule).where(CategoryRule.name == "r1")).all()) == 1
        assert len(s.scalars(select(EventOverride).where(EventOverride.source_id == tx.id)).all()) == 1
        assert any(x.nickname == "Conta principal" for x in s.scalars(select(AccountSetting)))
