"""Reconciliação estrutural: pagamentos de fatura, transferências próprias e fluxos de investimento.

Cada função recebe a lista completa de transações (TxView) e devolve decisões estruturais por tx_id,
mais os vínculos encontrados (para auditoria e para as telas).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.categorization.engine import Decision, TxView
from app.categorization.text import norm

FATURA_RE = re.compile(r"pag(to|amento)?\.? ?(de )?fatura|pagamento (de )?cartao|pgto\.? cartao|pag fat\b|fatura (do )?cartao")
# raiz do CNPJ de emissores de cartão: Pix/boleto pago ao próprio banco (sem ser para você) é fatura
CARD_ISSUER_ROOTS = {
    "00416968": "Inter", "18236120": "Nubank", "60701190": "Itaú", "60746948": "Bradesco",
    "90400888": "Santander", "00000000": "Banco do Brasil", "00360305": "Caixa", "31872495": "C6 Bank",
    "30306294": "BTG Pactual", "59285411": "Banco Pan",
}
# como o emissor aparece no nome/apelido do cartão conectado (para saber se o cartão daquele emissor está aqui)
CARD_ISSUER_HINTS = {
    "Inter": r"\binter\b", "Nubank": r"\bnu ?bank\b|\bnu pagamentos\b|\bultravioleta\b", "Itaú": r"\bitau",
    "Bradesco": r"\bbradesco", "Santander": r"\bsantander", "Banco do Brasil": r"\bbanco do brasil\b|\bourocard\b",
    "Caixa": r"\bcaixa\b", "C6 Bank": r"\bc6\b", "BTG Pactual": r"\bbtg\b", "Banco Pan": r"\bpan\b|\bbanco pan\b",
}
CARD_IN_RE = re.compile(r"pagamento (recebido|efetuado|obrigado)|pagto recebido|pagamento de fatura|pagamento fatura"
                        r"|pagamento on ?line|pag(to|amento) (por )?debito automatico")
# gateways de pagamento: Pix para eles nunca e fatura de cartao sem evidencia real (credito/fatura casados)
GATEWAY_RE = re.compile(r"\b(tuna|pagseguro|pagbank|mercado ?pago|stone|cielo|getnet|adyen|ebanx|picpay|asaas|iugu"
                        r"|pagar ?me|zoop|juno)\b")
INVEST_OUT_RE = re.compile(r"aplicacao|\baplic\b|guardad[oa]|caixinha|compra de (cdb|lci|lca|titulo|tesouro|acoes|fii|etf|renda (variavel|fixa))|investimento realizado")
INVEST_IN_RE = re.compile(r"resgate|resgatad|valor recebido de investimentos|vencimento de (cdb|lci|lca|titulo)|venda de (acoes|fii|etf|renda (variavel|fixa))")
# Tesouro Direto debitado na conta (ex.: Inter "Debito Online Td - Prot.123456789 Selic 2031")
TESOURO_OUT_RE = re.compile(r"debito online td\b|\btd\b.{0,40}\b(selic|ipca|prefixado|renda\+|educa\+) ?20\d\d|compra (de )?tesouro")
TESOURO_IN_RE = re.compile(r"credito online td\b|resgate td\b|venda td\b|vencimento td\b|\btd\b.{0,40}\b(selic|ipca|prefixado) ?20\d\d")
INVEST_HINT_RE = re.compile(r"\b(rdb|cdb|lci|lca|cri|cra|tesouro|caixinha|fundo|investimento|poupanca|renda variavel|renda fixa|acoes|fii|etf)")


@dataclass
class TransferLink:
    out_tx: str
    in_tx: str
    amount: float
    days: int
    method: str
    confidence: float


@dataclass
class CardLink:
    payment_tx: str
    card_account_id: str
    card_tx: str | None
    bill_id: str | None
    method: str
    diff: float
    confidence: float


def _days(a: date, b: date) -> int:
    return abs((a - b).days)


def _close(a: float, b: float, rel: float, absolute: float) -> bool:
    return abs(abs(a) - abs(b)) <= max(absolute, rel * abs(b))


# ------------------------------------------------------------------ investimentos
def investment_flows(txs: list[TxView]) -> dict[str, Decision]:
    out: dict[str, Decision] = {}
    for t in txs:
        if t.removed or t.account_type != "BANK":
            continue
        cat = t.pluggy_cat or ""
        text = t.text
        by_cat = cat.startswith("03") and cat != "03060000"
        by_text = ((INVEST_IN_RE.search(text) if t.flow > 0 else INVEST_OUT_RE.search(text)) and (
            INVEST_HINT_RE.search(text) or "investimentos" in text)) or (
            TESOURO_IN_RE.search(text) if t.flow > 0 else TESOURO_OUT_RE.search(text))
        if not (by_cat or by_text):
            continue
        out[t.id] = Decision(
            category_id="pat.aporte" if t.flow < 0 else "pat.resgate",
            event_type="INVESTMENT_CONTRIBUTION" if t.flow < 0 else "INVESTMENT_REDEMPTION",
            rule_source="structural", rule_id="invest:category" if by_cat else "invest:description",
            confidence=0.92 if by_cat else 0.85)
    return out


# ------------------------------------------------------------------ cartão
def connected_card_issuers(card_texts: list[str]) -> set[str]:
    """Emissores (rótulos de CARD_ISSUER_ROOTS) com cartão conectado, a partir de nome/apelido/instituição."""
    out = set()
    for text in card_texts:
        t = norm(text)
        out |= {label for label, rx in CARD_ISSUER_HINTS.items() if re.search(rx, t)}
    return out


def card_payments(txs: list[TxView], bills: list[dict], card_accounts: dict[str, str],
                  skip: set[str], connected_issuers: set[str] | None = None
                  ) -> tuple[dict[str, Decision], list[CardLink]]:
    """card_accounts: {account_id: item_id} dos cartões conectados. bills: dicts com id, account_id, due_date,
    total_amount. connected_issuers: emissores com cartão conectado (pagamento ao CNPJ deles sem casamento não é
    cartão externo)."""
    connected_issuers = connected_issuers or set()
    decisions: dict[str, Decision] = {}
    links: list[CardLink] = []
    def issuer(t: TxView) -> str | None:
        doc = t.receiver_doc or t.counterparty_doc or ""
        return CARD_ISSUER_ROOTS.get(doc[:8]) if len(doc) == 14 else None

    def is_gateway(t: TxView) -> bool:
        return bool(GATEWAY_RE.search(norm(f"{t.counterparty_name or ''} {t.text}"))) and not issuer(t) \
            and not FATURA_RE.search(t.text)

    payments = sorted([t for t in txs if not t.removed and t.id not in skip and t.account_type == "BANK"
                       and t.flow < 0 and (t.pluggy_cat == "05100000" or FATURA_RE.search(t.text) or issuer(t))],
                      key=lambda t: t.date)
    credits = [t for t in txs if not t.removed and t.account_type == "CREDIT" and t.flow > 0
               and (t.pluggy_cat == "05100000" or CARD_IN_RE.search(t.text))]
    used_credits: set[str] = set()
    used_bills: set[str] = set()

    for p in payments:
        best = None
        for c in credits:
            if c.id in used_credits or not _close(p.flow, c.flow, 0.01, 1.0):
                continue
            d = _days(p.date, c.date)
            if d <= 7 and (best is None or d < best[0]):
                best = (d, c)
        if best:
            c = best[1]
            used_credits.add(c.id)
            links.append(CardLink(p.id, c.account_id, c.id, None, "card_credit", abs(abs(p.flow) - c.flow), 0.95))
            decisions[p.id] = Decision("pat.fatura", "CARD_PAYMENT", "structural", "card:credit_match", 0.95)
            continue
        bill = None
        for b in bills:
            if b["id"] in used_bills or b["due_date"] is None or b["total_amount"] is None:
                continue
            if _close(p.flow, b["total_amount"], 0.02, 1.0) and _days(p.date, b["due_date"]) <= 10:
                bill = b
                break
        if bill:
            used_bills.add(bill["id"])
            links.append(CardLink(p.id, bill["account_id"], None, bill["id"], "bill_amount",
                                  abs(abs(p.flow) - bill["total_amount"]), 0.9))
            decisions[p.id] = Decision("pat.fatura", "CARD_PAYMENT", "structural", "card:bill_match", 0.9)
        elif not (p.pluggy_cat == "05100000" or FATURA_RE.search(p.text)):
            # só o CNPJ do banco, sem categoria/descrição de fatura nem valor casado: pode ser seguro, consórcio,
            # parcela de empréstimo do mesmo banco… fica com a categorização normal (comerciante, Pluggy, revisão)
            continue
        elif is_gateway(p):
            # sem fatura/credito casado, Pix a gateway e despesa provisoria para revisao
            decisions[p.id] = Decision("servicos.outros", "EXPENSE", "structural", "card:gateway_not_invoice", 0.35,
                                       review=["payment_gateway"])
        elif card_accounts and (not issuer(p) or issuer(p) in connected_issuers):
            # o cartão do emissor está conectado: as compras já estão lá; tratar como despesa contaria em dobro
            decisions[p.id] = Decision("pat.fatura", "CARD_PAYMENT", "structural", "card:unmatched", 0.7,
                                       review=["card_payment_unmatched"])
        else:
            # sem cartão conectado (ou pago ao emissor de um cartão que não está aqui): a fatura é a única
            # evidência das compras, então entra como despesa até o cartão ser conectado
            decisions[p.id] = Decision("terceiros.cartao_externo", "EXPENSE", "structural",
                                       f"card:not_connected:{issuer(p) or '-'}", 0.6,
                                       review=["card_not_connected"])

    for c in credits:
        decisions[c.id] = Decision("pat.fatura", "CARD_PAYMENT", "structural",
                                   "card:credit_side" if c.id in used_credits else "card:credit_side_unmatched",
                                   0.92 if c.id in used_credits else 0.8)
    return decisions, links


# ------------------------------------------------------------------ transferências próprias
def _own_name_match(text: str, own_names: list[list[str]]) -> bool:
    for tokens in own_names:
        if len(tokens) >= 2 and tokens[0] in text and tokens[-1] in text:
            return True
    return False


def is_own(t: TxView, own_docs: set[str], own_names: list[list[str]]) -> bool:
    if (t.pluggy_cat or "").startswith("04"):
        return True
    if own_docs:
        if t.payer_doc in own_docs and t.receiver_doc in own_docs:
            return True
        if t.counterparty_doc and t.counterparty_doc in own_docs:
            return True
    target = norm(f"{t.counterparty_name or ''} {t.description or ''}")
    return _own_name_match(target, own_names) and (t.payment_method in ("PIX", "TED", "DOC", None)
                                                   or (t.pluggy_cat or "").startswith("05"))


def transfers(txs: list[TxView], own_docs: set[str], own_names: list[list[str]], skip: set[str]
              ) -> tuple[dict[str, Decision], list[TransferLink]]:
    decisions: dict[str, Decision] = {}
    links: list[TransferLink] = []
    pool = [t for t in txs if not t.removed and t.id not in skip and t.account_type == "BANK"
            and ((t.pluggy_cat or "").startswith(("04", "05")) or is_own(t, own_docs, own_names))]
    own = {t.id for t in pool if is_own(t, own_docs, own_names)}
    outs = sorted([t for t in pool if t.flow < 0], key=lambda t: t.date)
    ins = [t for t in pool if t.flow > 0]
    used: set[str] = set()
    for o in outs:
        best = None
        for i in ins:
            if i.id in used or i.account_id == o.account_id or abs(abs(o.flow) - i.flow) > 0.01:
                continue
            if not (o.id in own or i.id in own):
                continue
            d = _days(o.date, i.date)
            if d <= 3 and (best is None or d < best[0]):
                best = (d, i)
        if best:
            i = best[1]
            used.update({o.id, i.id})
            links.append(TransferLink(o.id, i.id, abs(o.flow), best[0], "amount_date_own", 0.95))
            for tid in (o.id, i.id):
                decisions[tid] = Decision("pat.transferencia", "INTERNAL_TRANSFER", "structural",
                                          "transfer:paired", 0.95)
    for t in pool:
        if t.id in own and t.id not in used:
            decisions[t.id] = Decision("pat.conta_externa", "EXTERNAL_OWN_TRANSFER", "structural",
                                       "transfer:own_unpaired", 0.85)
    return decisions, links


def installment_key(t: TxView) -> str | None:
    if t.account_type != "CREDIT" or not t.total_installments or t.total_installments <= 1:
        return None
    from app.categorization.text import merchant_alias
    return f"{t.account_id[:8]}|{merchant_alias(t.description)}|{t.total_installments}|{abs(round(t.flow, 2))}"
