def test_onboarding_flags_unclassified_income(synced):
    from app.api.routes_system import onboarding

    with synced["sf"]() as s:
        o = onboarding(db=s)
    assert o["pluggy_configured"] and o["items"] == 1 and o["events"] > 0
    # o salário do cliente falso chega como Pix de terceiro ainda "a classificar"
    assert o["income_unclassified"] > 0 and 0 < o["income_unclassified_share"] <= 1


def test_onboarding_empty_database(db_reset):
    from app.api.routes_system import onboarding

    with db_reset() as s:
        o = onboarding(db=s)
    assert o["items"] == 0 and o["events"] == 0 and o["income_unclassified_share"] == 0.0


def test_integrations_saved_in_app_override_env_and_can_be_cleared(db_reset):
    from app.config import integrations
    from app.config.settings import get_settings

    s = db_reset()
    try:
        _roundtrip(s, integrations, get_settings)
    finally:
        s.rollback()
        s.close()


def _roundtrip(s, integrations, get_settings):
    integrations.apply(s)
    env_id = get_settings().pluggy_client_id
    integrations.save(s, {"pluggy_client_id": "novo-id", "pluggy_client_secret": "novo-segredo", "smtp_user": "eu@gmail.com"})
    view = integrations.public_view(s)
    assert get_settings().pluggy_client_id == "novo-id" and view["pluggy"]["origin"] == "app"
    assert "novo-segredo" not in str(view)  # segredo nunca volta para a tela
    assert view["email"]["smtp_user"] == "eu@gmail.com" and not view["email"]["configured"]  # falta a senha

    integrations.save(s, {"pluggy_client_secret": None})  # segredo omitido fica como está
    assert get_settings().pluggy_client_secret == "novo-segredo"
    integrations.save(s, {"pluggy_client_id": "", "pluggy_client_secret": "", "smtp_user": ""})  # vazio volta ao .env
    assert get_settings().pluggy_client_id == env_id


def test_safe_to_spend_default_aporte_capped_by_surplus(synced):
    from app.analytics.plano import safe_to_spend

    with synced["sf"]() as s:
        sts = safe_to_spend(s)
    assert sts["meta_aporte_origem"] in ("padrao", "padrao_limitado")
    assert 0 <= sts["meta_aporte"] <= round(0.2 * sts["renda_prevista"], 2)
