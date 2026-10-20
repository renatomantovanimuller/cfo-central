"""Cliente Pluggy falso com ~13 meses de dados realistas no formato da API (para testes e demo).

Convenções reproduzidas da fonte real (MeuPluggy/Nubank): compras no cartão com amount positivo,
transferências genéricas em 05000000, Pix com paymentData (CPF/CNPJ), faturas mensais.
"""
from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta, timezone

OWNER_CPF = "123.456.789-09"
OWNER = "FULANO DE TAL SILVA"
ITEM_ID = "00000000-0000-4000-8000-00000000demo"
BANK_ID = "acc-bank-0001"
CARD_ID = "acc-card-0001"


def _iso(d: date, hour: int = 15) -> str:
    return datetime(d.year, d.month, d.day, hour, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _uid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128)))


class FakePluggyClient:
    def __init__(self, today: date | None = None, months: int = 13, seed: int = 7):
        self.today = today or date.today()
        self.rng = random.Random(seed)
        self.months = months
        self._bank, self._card, self._bills = [], [], []
        self.pending_variant = False  # simula pendente → efetivada com novo id
        self._build()

    # ------------------------------------------------------------------ geração
    def _tx(self, acc: str, d: date, desc: str, amount: float, cat: tuple[str, str] | None = None,
            ptype: str | None = None, payer=None, receiver=None, merchant=None, cc=None, status="POSTED",
            tid: str | None = None) -> dict:
        pd = None
        if ptype:
            pd = {"paymentMethod": ptype, "payer": payer or {}, "receiver": receiver or {}, "reason": None,
                  "receiverReferenceId": None, "authenticationCode": None, "referenceNumber": None,
                  "boletoMetadata": None}
        return {"id": tid or _uid(self.rng), "description": desc, "descriptionRaw": None, "currencyCode": "BRL",
                "amount": round(amount, 2), "amountInAccountCurrency": None, "date": _iso(d),
                "category": cat[1] if cat else None, "categoryId": cat[0] if cat else None, "balance": None,
                "accountId": acc, "providerCode": None, "status": status, "paymentData": pd,
                "type": "CREDIT" if (amount > 0) != (acc == CARD_ID) else "DEBIT",
                "operationType": None, "creditCardMetadata": cc, "merchant": merchant,
                "createdAt": _iso(d), "updatedAt": _iso(d)}

    def _party(self, name: str, doc: str, kind: str = "CPF") -> dict:
        return {"name": name, "documentNumber": {"type": kind, "value": doc}, "accountNumber": None,
                "branchNumber": None, "routingNumber": None, "routingNumberISPB": None}

    def _build(self) -> None:
        r = self.rng
        me = self._party(OWNER, OWNER_CPF)
        start = date(self.today.year, self.today.month, 1)
        for k in range(self.months - 1, -1, -1):
            y, m = start.year, start.month - k
            while m <= 0:
                y, m = y - 1, m + 12
            first = date(y, m, 1)

            def day(n: int) -> date | None:
                try:
                    d = first.replace(day=n)
                except ValueError:
                    d = first.replace(day=28)
                return d if d <= self.today else None

            # salário (PJ, categoria genérica de transferência — como no Nubank)
            if (d := day(5)):
                self._bank.append(self._tx(BANK_ID, d, "Transferência Recebida|ACME CONSULTORIA LTDA",
                                           round(3200 + r.uniform(-150, 300), 2), ("05000000", "Transfers"), "PIX",
                                           payer=self._party("ACME CONSULTORIA LTDA", "12.345.678/0001-90", "CNPJ"),
                                           receiver=me))
            if (d := day(10)):
                self._bank.append(self._tx(BANK_ID, d, "Pagamento efetuado|IMOBILIARIA CENTRO LOCACOES", -1500,
                                           ("05000000", "Transfers"), "OTHER"))
            if (d := day(12)):
                self._bank.append(self._tx(BANK_ID, d, "Pagamento de boleto|ENERGIA EXEMPLO", -round(r.uniform(140, 230), 2),
                                           ("17020002", "Electricity"), "BOLETO",
                                           merchant={"cnpj": "22222222000191", "cnae": "3514000",
                                                     "category": "Electricity", "businessName": "COMPANHIA PAULISTA DE FORCA E LUZ"}))
            if (d := day(6)):
                self._bank.append(self._tx(BANK_ID, d, "Aplicação RDB", -800, ("03000000", "Investments"), "OTHER"))
            if k % 4 == 1 and (d := day(20)):
                self._bank.append(self._tx(BANK_ID, d, "Resgate RDB", 1200, ("03000000", "Investments"), "OTHER"))
            if k % 3 == 0 and (d := day(15)):
                self._bank.append(self._tx(BANK_ID, d, "Transferência enviada pelo Pix|JOAO AMIGO", -round(r.uniform(60, 250), 2),
                                           ("05000000", "Transfers"), "PIX", payer=me,
                                           receiver=self._party("JOAO AMIGO", "987.654.321-00")))
            if k % 2 == 0 and (d := day(18)):
                self._bank.append(self._tx(BANK_ID, d, "Transferência Recebida|MARIA COLEGA", round(r.uniform(30, 90), 2),
                                           ("05000000", "Transfers"), "PIX", payer=self._party("MARIA COLEGA", "111.222.333-44"),
                                           receiver=me))
            if k % 5 == 2 and (d := day(22)):
                self._bank.append(self._tx(BANK_ID, d, f"Transferência Recebida|{OWNER}", 2000.0,
                                           ("04000000", "Same person transfer"), "PIX", payer=me, receiver=me))
            if (d := day(28)):
                self._bank.append(self._tx(BANK_ID, d, "IOF", -round(r.uniform(0.5, 3), 2), ("15030000", "Tax on financial operations")))

            # cartão: compras (amount positivo = compra)
            card_total = 0.0

            def buy(n: int, desc: str, amt: float, cat: tuple[str, str], cnpj: str | None = None, cc=None):
                nonlocal card_total
                d = day(n)
                if not d:
                    return
                merchant = {"cnpj": cnpj, "cnae": None, "category": cat[1], "businessName": desc.upper()} if cnpj else None
                self._card.append(self._tx(CARD_ID, d, desc, amt, cat, merchant=merchant, cc=cc))
                card_total += amt

            for n in (2, 9, 16, 23):
                buy(n, "Supermercado Exemplo", round(r.uniform(80, 260), 2), ("10000000", "Groceries"), "11111111000191")
            for n in range(1, 29, 3):
                buy(n, "Uber *Trip", round(r.uniform(9, 35), 2), ("19010000", "Taxi and ride-hailing"))
            for n in (4, 13, 21, 26):
                buy(n, "Ifd*Restaurante Sabor", round(r.uniform(35, 80), 2), ("11020000", "Food delivery"))
            for n in (7, 19):
                buy(n, "Bar e Petiscaria Central", round(r.uniform(40, 160), 2), ("11010000", "Eating out"))
            buy(3, "Netflix.com", 55.90, ("09020000", "Video streaming"))
            buy(3, "Spotify", 21.90, ("09030000", "Music streaming"))
            buy(8, "Smart Fit", 129.90, ("07030001", "Gyms and fitness centers"))
            buy(14, "Anthropic Claude Subscription", 110.0, ("08020000", "Electronics"))
            if k % 2 == 0:
                buy(17, "Raia Drogasil", round(r.uniform(25, 120), 2), ("18020000", "Pharmacy"), "61585865000151")
            if k == 1:
                buy(11, "Estorno de Uber - NuPay", -18.5, ("05000000", "Transfers"))
                card_total -= 0  # estorno já entra pelo sinal
            # compra parcelada 10x iniciada 5 meses atrás
            if 0 <= 5 - k < 10:
                n_inst = 5 - k + 1
                buy(11, "Loja Eletro Notebook", 450.0, ("08020000", "Electronics"),
                    cc={"installmentNumber": n_inst, "totalInstallments": 10, "totalAmount": 4500.0,
                        "purchaseDate": None, "billId": None})

            # fatura: paga no dia 1 do mês seguinte a partir do conta corrente
            due = first.replace(day=28) + timedelta(days=4)
            due = due.replace(day=1)
            if due <= self.today:
                total = round(card_total, 2)
                bill_id = _uid(r)
                self._bills.append({"id": bill_id, "dueDate": _iso(due), "billClosingDate": _iso(due - timedelta(days=7)),
                                    "totalAmount": total, "totalAmountCurrencyCode": "BRL", "minimumPaymentAmount": None,
                                    "allowsInstallments": None, "financeCharges": [], "payments": []})
                self._bank.append(self._tx(BANK_ID, due, "Pagamento de fatura", -total, ("05100000", "Credit card payment"), "OTHER"))
                self._card.append(self._tx(CARD_ID, due, "Pagamento recebido", -total, ("05100000", "Credit card payment")))

        # um lançamento pendente recente
        self._pending_id = _uid(r)
        self._card.append(self._tx(CARD_ID, self.today, "Padaria Pao Quente", 23.4, ("11000000", "Food and drinks"),
                                   status="PENDING", tid=self._pending_id))

    # ------------------------------------------------------------------ API compatível
    def item(self, item_id: str) -> dict:
        return {"id": item_id, "status": "UPDATED", "executionStatus": "SUCCESS",
                "connector": {"id": 200, "name": "MeuPluggy", "imageUrl": None, "primaryColor": "7d47ff",
                              "type": "PERSONAL_BANK", "isOpenFinance": False, "isSandbox": False},
                "createdAt": "2025-01-01T00:00:00Z", "updatedAt": _iso(self.today), "lastUpdatedAt": _iso(self.today),
                "consentExpiresAt": _iso(self.today + timedelta(days=300)),
                "nextAutoSyncAt": _iso(self.today + timedelta(days=1)), "products": ["ACCOUNTS", "TRANSACTIONS"],
                "clientUserId": "demo", "statusDetail": None, "error": None}

    def accounts(self, item_id: str) -> list[dict]:
        bank_bal = 4200.0 + sum(t["amount"] for t in self._bank[-6:]) * 0
        return [
            {"id": BANK_ID, "itemId": item_id, "type": "BANK", "subtype": "CHECKING_ACCOUNT", "name": "Conta Corrente",
             "marketingName": "Conta", "number": "0001/123456-7", "owner": OWNER, "taxNumber": OWNER_CPF,
             "balance": round(bank_bal, 2), "currencyCode": "BRL", "bankData": {"closingBalance": bank_bal},
             "creditData": None, "updatedAt": _iso(self.today)},
            {"id": CARD_ID, "itemId": item_id, "type": "CREDIT", "subtype": "CREDIT_CARD", "name": "Cartão Roxinho",
             "marketingName": None, "number": "1234", "owner": OWNER, "taxNumber": OWNER_CPF, "balance": 1450.32,
             "currencyCode": "BRL", "bankData": None,
             "creditData": {"creditLimit": 9000.0, "availableCreditLimit": 5049.68,
                            "balanceCloseDate": _iso(self.today + timedelta(days=10)),
                            "balanceDueDate": _iso(self.today + timedelta(days=17)), "minimumPayment": 210.0,
                            "brand": "MASTERCARD"}, "updatedAt": _iso(self.today)},
        ]

    def transactions(self, account_id: str, date_from: str | None = None):
        txs = self._bank if account_id == BANK_ID else self._card
        if self.pending_variant:
            txs = [t for t in txs if t["id"] != self._pending_id]
            posted = self._tx(CARD_ID, self.today, "Padaria Pao Quente", 23.4, ("11000000", "Food and drinks"),
                              tid="posted-" + self._pending_id[:8]) if account_id == CARD_ID else None
            if posted:
                txs = txs + [posted]
        for t in txs:
            if date_from and t["date"][:10] < date_from:
                continue
            yield t

    def bills(self, account_id: str) -> list[dict]:
        return list(self._bills) if account_id == CARD_ID else []

    def investments(self, item_id: str) -> list[dict]:
        base = {"itemId": item_id, "currencyCode": "BRL", "status": "ACTIVE", "taxes": None, "taxes2": None,
                "metadata": None, "owner": OWNER, "updatedAt": _iso(self.today)}
        return [
            {**base, "id": "inv-cdb-1", "name": "CDB Banco Digital 120% CDI", "code": None, "isin": None,
             "type": "FIXED_INCOME", "subtype": "CDB", "balance": 18450.0, "amount": 18900.0, "amountOriginal": 16000.0,
             "amountProfit": None, "quantity": 160000, "value": 0.118, "rate": 120.0, "rateType": "CDI",
             "issuer": "BANCO DIGITAL S.A.", "issuerCNPJ": "18.236.120/0001-58", "dueDate": "2028-05-02T00:00:00Z",
             "purchaseDate": _iso(self.today - timedelta(days=500)), "date": _iso(self.today)},
            {**base, "id": "inv-tesouro-1", "name": "Tesouro IPCA+ 2035", "code": "BRSTNCNTB4U6", "isin": "BRSTNCNTB4U6",
             "type": "FIXED_INCOME", "subtype": "TREASURY", "balance": 9800.0, "amount": 9950.0, "amountOriginal": 9000.0,
             "amountProfit": None, "quantity": 3.1, "value": 3209.0, "rate": 100.0, "rateType": "IPCA",
             "fixedAnnualRate": 6.4, "issuer": None, "dueDate": "2035-05-15T00:00:00Z",
             "purchaseDate": _iso(self.today - timedelta(days=420)), "date": _iso(self.today)},
            {**base, "id": "inv-bova", "name": "ISHARES BOVA", "code": "BOVA11", "isin": "BRBOVACTF003", "type": "ETF",
             "subtype": "ETF", "balance": 12800.0, "amount": 12800.0, "amountOriginal": None, "quantity": 92,
             "value": 139.13, "issuer": None, "dueDate": None, "date": _iso(self.today)},
            {**base, "id": "inv-ivvb", "name": "ISHARES S&P 500", "code": "IVVB11", "isin": "BRIVVBCTF001", "type": "ETF",
             "subtype": "ETF", "balance": 15400.0, "amount": 15400.0, "amountOriginal": None, "quantity": 36,
             "value": 427.7, "issuer": None, "dueDate": None, "date": _iso(self.today)},
            {**base, "id": "inv-hglg", "name": "CSHG LOGISTICA FII", "code": "HGLG11", "isin": None, "type": "EQUITY",
             "subtype": "REAL_ESTATE_FUND", "balance": 6400.0, "amount": 6400.0, "amountOriginal": 6100.0,
             "quantity": 40, "value": 160.0, "issuer": None, "dueDate": None, "date": _iso(self.today)},
        ]

    def investment_transactions(self, investment_id: str) -> list[dict]:
        if investment_id != "inv-cdb-1":
            return []
        return [{"id": f"itx-{i}", "type": "BUY", "movementType": "CREDIT", "quantity": 8000, "value": 0.1,
                 "amount": 800.0, "netAmount": None, "date": _iso(self.today - timedelta(days=30 * i)),
                 "tradeDate": None, "description": "Aplicação", "brokerageNumber": None} for i in range(1, 6)]

    def loans(self, item_id: str) -> list[dict]:
        return []

    def identity(self, item_id: str) -> dict:
        return {"id": "ident-1", "fullName": OWNER, "taxNumber": OWNER_CPF}

    def categories(self) -> list[dict]:
        from app.categorization.chart import PLUGGY_MAP
        return [{"id": k, "description": k, "descriptionTranslated": k, "parentId": None} for k in PLUGGY_MAP]

    def connect_token(self, *a, **k) -> str:
        return "fake-token"
