from types import SimpleNamespace

from app.accounting.balance import card_usage


def _acc(limit, available, lines=None):
    return SimpleNamespace(credit_limit=limit, available_credit=available,
                           credit_data={"disaggregatedCreditLimits": lines} if lines is not None else None)


def test_limite_reduzido_no_app_nao_vira_divida():
    # contratado 6.000, limite ajustado pelo cliente 2.500, disponível 1.300, usado 1.200
    line = {"creditLineLimitType": "LIMITE_CREDITO_TOTAL", "usedAmount": 1200.0, "limitAmount": 6000,
            "availableAmount": 1300.0, "customizedLimitAmount": 2500}
    assert card_usage(_acc(6000, 1300.0, [line, dict(line, creditLineLimitType="LIMITE_CREDITO_MODALIDADE_OPERACAO")])) \
        == (2500, 1200.0)


def test_sem_linhas_desagregadas_usa_limite_menos_disponivel():
    assert card_usage(_acc(3000, 1000)) == (3000, 2000)


def test_personalizado_sem_used_amount():
    line = {"creditLineLimitType": "LIMITE_CREDITO_TOTAL", "customizedLimitAmount": 2000}
    assert card_usage(_acc(5000, 500, [line])) == (2000, 1500)


def test_sem_dados():
    assert card_usage(_acc(None, None)) == (None, None)
