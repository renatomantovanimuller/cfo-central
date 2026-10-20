"""Transações efetivas: pendente duplicado de efetivado e pendente velho não contam."""
from datetime import date
from types import SimpleNamespace

from app.accounting.effective import STALE, SUPERSEDED, ineffective_pending

HOJE = date(2026, 10, 16)


def tx(id, status, d, flow, desc="Pagamento recebido", account="cc1", account_type="CREDIT"):
    return SimpleNamespace(id=id, status=status, date=d, flow=flow, description=desc, account_id=account,
                           installment_number=None, total_installments=None, removed=False, account_type=account_type)


def test_par_pendente_e_efetivado_conta_uma_vez():
    txs = [tx("pos", "POSTED", date(2026, 10, 1), 750.0),
           tx("pen", "PENDING", date(2026, 10, 2), 750.0, desc="PAGAMENTO ON LINE")]
    assert ineffective_pending(txs, HOJE, 10) == {"pen": SUPERSEDED}


def test_pendente_velho_sem_efetivacao_nao_entra():
    txs = [tx("velho", "PENDING", date(2026, 9, 1), -86.0, desc="Farmacia", account_type="CREDIT"),
           tx("banco", "PENDING", date(2026, 10, 1), -20.0, desc="Pix", account="cc2", account_type="BANK")]
    assert ineffective_pending(txs, HOJE) == {"velho": STALE, "banco": STALE}


def test_pendente_de_cartao_ainda_nao_faturado_continua():
    txs = [tx("aberto", "PENDING", date(2026, 9, 23), -50.0, desc="Posto", account_type="CREDIT")]
    assert ineffective_pending(txs, HOJE) == {}


def test_pendente_recente_sem_par_continua():
    txs = [tx("novo", "PENDING", date(2026, 10, 12), -50.0, desc="Mercado"),
           tx("outro", "POSTED", date(2026, 10, 12), -51.0, desc="Mercado")]
    assert ineffective_pending(txs, HOJE, 10) == {}


def test_valor_ou_conta_diferente_nao_casa():
    txs = [tx("pos", "POSTED", date(2026, 10, 14), -30.0, desc="Padaria"),
           tx("pen", "PENDING", date(2026, 10, 14), -30.0, desc="Padaria", account="cc2")]
    assert ineffective_pending(txs, HOJE, 10) == {}
