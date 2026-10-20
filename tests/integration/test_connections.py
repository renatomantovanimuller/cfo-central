from sqlalchemy import select


def test_duplicate_bank_blocked_other_bank_allowed(synced):
    from app.api.routes_system import duplicate_of
    from app.models import Account

    s = synced["sf"]()
    existing = s.scalars(select(Account)).all()
    same = [{"type": a.type, "subtype": a.subtype, "number": a.number, "name": a.name} for a in existing]
    assert duplicate_of(s, "novo-item", same)  # o mesmo banco escolhido de novo no MeuPluggy
    other = [{"type": "BANK", "subtype": "CHECKING_ACCOUNT", "number": "0001/9999999-9", "name": "Banco Inter"}]
    assert duplicate_of(s, "novo-item", other) == []


def test_client_allows_multiple_meupluggy_items():
    from app.connectors.pluggy.client import PluggyClient

    sent = {}
    c = PluggyClient.__new__(PluggyClient)
    c.request = lambda method, path, json=None, **kw: sent.update(json) or {"accessToken": "t"}
    c.connect_token("user-1")
    assert "avoidDuplicates" not in sent["options"]
