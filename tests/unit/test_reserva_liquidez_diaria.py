from app.portfolio.classification import classify, has_daily_liquidity


def _cdb(**kw):
    base = {"type": "FIXED_INCOME", "subtype": "CDB", "rate_type": "CDI", "issuer": "Banco X", "name": "CDB X"}
    return {**base, **kw}


def test_cdb_nu_financeira_tem_liquidez_diaria():
    assert classify(_cdb(issuer="Nu Financeira S.A."))["liquidity"] == "D0"


def test_rdb_tem_liquidez_diaria():
    assert classify(_cdb(subtype="RDB"))["liquidity"] == "D0"


def test_caixinha_tem_liquidez_diaria():
    assert classify(_cdb(name="Caixinha Viagem"))["liquidity"] == "D0"


def test_historico_de_resgate_parcial_marca_liquidez_diaria():
    assert classify(_cdb(early_redemption=True))["liquidity"] == "D0"


def test_cdb_comum_continua_no_vencimento():
    assert classify(_cdb())["liquidity"] == "vencimento"
    assert not has_daily_liquidity(_cdb())


def test_tesouro_selic_e_d1():
    out = classify({"type": "FIXED_INCOME", "subtype": "TREASURY", "rate_type": "SELIC"})
    assert out["liquidity"] == "D1" and out["asset_class"] == "Tesouro Selic"
