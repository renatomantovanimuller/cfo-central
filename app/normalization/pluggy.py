"""Payload Pluggy → dicionários da camada 2. Tolerante a campos ausentes/nulos e a mudanças de formato."""
from __future__ import annotations

import re
from typing import Any

from app.utils.time import local_date, parse_dt


def num(v: Any) -> float | None:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def integer(v: Any) -> int | None:
    try:
        return None if v is None or v == "" else int(float(v))
    except (TypeError, ValueError):
        return None


def digits(s: str | None) -> str | None:
    d = re.sub(r"\D", "", s or "")
    return d or None


def g(d: Any, *path: str) -> Any:
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def institution(connector: dict) -> dict:
    return {
        "id": connector["id"], "name": connector.get("name") or str(connector["id"]),
        "type": connector.get("type"), "image_url": connector.get("imageUrl"),
        "primary_color": connector.get("primaryColor"),
        "is_open_finance": bool(connector.get("isOpenFinance")), "is_sandbox": bool(connector.get("isSandbox")),
    }


def item(p: dict) -> dict:
    return {
        "id": p["id"], "institution_id": g(p, "connector", "id"), "client_user_id": p.get("clientUserId"),
        "status": p.get("status"), "execution_status": p.get("executionStatus"),
        "status_detail": p.get("statusDetail"), "error": p.get("error"), "products": p.get("products"),
        "consent_expires_at": parse_dt(p.get("consentExpiresAt")),
        "next_auto_sync_at": parse_dt(p.get("nextAutoSyncAt")),
        "source_updated_at": parse_dt(p.get("lastUpdatedAt") or p.get("updatedAt")),
        "source_created_at": parse_dt(p.get("createdAt")),
    }


def account(p: dict) -> dict:
    cd = p.get("creditData") or {}
    return {
        "id": p["id"], "item_id": p.get("itemId"), "type": p.get("type"), "subtype": p.get("subtype"),
        "name": p.get("name"), "marketing_name": p.get("marketingName"), "number": p.get("number"),
        "owner": p.get("owner"), "tax_number": digits(p.get("taxNumber")), "currency": p.get("currencyCode"),
        "balance": num(p.get("balance")), "bank_data": p.get("bankData"), "credit_data": p.get("creditData"),
        "credit_limit": num(cd.get("creditLimit")), "available_credit": num(cd.get("availableCreditLimit")),
        "bill_close_date": local_date(cd.get("balanceCloseDate")), "bill_due_date": local_date(cd.get("balanceDueDate")),
        "minimum_payment": num(cd.get("minimumPayment")), "brand": cd.get("brand"),
        "source_updated_at": parse_dt(p.get("updatedAt")),
    }


def transaction(p: dict, account_id: str, item_id: str) -> dict:
    cc = p.get("creditCardMetadata") or {}
    pd = p.get("paymentData") or {}
    merchant = p.get("merchant") or {}
    payer, receiver = pd.get("payer") or {}, pd.get("receiver") or {}
    amount = num(p.get("amount")) or 0.0
    aic = num(p.get("amountInAccountCurrency"))
    amount_brl = abs(aic) * (1 if amount >= 0 else -1) if aic is not None else amount
    other = receiver if amount < 0 else payer
    return {
        "id": p["id"], "account_id": account_id, "item_id": item_id,
        "date": local_date(p.get("date")), "datetime_utc": parse_dt(p.get("date")),
        "description": p.get("description"), "description_raw": p.get("descriptionRaw"),
        "amount": amount, "amount_brl": amount_brl, "currency": p.get("currencyCode"),
        "type": p.get("type"), "status": p.get("status"), "operation_type": p.get("operationType"),
        "pluggy_category_id": p.get("categoryId"), "pluggy_category": p.get("category"),
        "merchant_name": merchant.get("name") or merchant.get("businessName"),
        "merchant_cnpj": digits(merchant.get("cnpj")), "merchant_cnae": merchant.get("cnae"),
        "merchant_category": merchant.get("category"),
        "mcc": integer(cc.get("payeeMCC")), "payment_method": pd.get("paymentMethod"),
        "payer_name": payer.get("name"), "payer_doc": digits(g(payer, "documentNumber", "value")),
        "receiver_name": receiver.get("name"), "receiver_doc": digits(g(receiver, "documentNumber", "value")),
        "counterparty_name": other.get("name"), "counterparty_doc": digits(g(other, "documentNumber", "value")),
        "installment_number": integer(cc.get("installmentNumber")),
        "total_installments": integer(cc.get("totalInstallments")),
        "installment_total_amount": num(cc.get("totalAmount")), "bill_id": cc.get("billId"),
        "purchase_date": local_date(cc.get("purchaseDate") or cc.get("transactionDateTime")),
        "provider_id": p.get("providerId"),
        "source_created_at": parse_dt(p.get("createdAt")), "source_updated_at": parse_dt(p.get("updatedAt")),
    }


def bill(p: dict, account_id: str) -> dict:
    return {
        "id": p["id"], "account_id": account_id, "due_date": local_date(p.get("dueDate")),
        "close_date": local_date(p.get("billClosingDate")), "total_amount": num(p.get("totalAmount")),
        "minimum_payment": num(p.get("minimumPaymentAmount")), "currency": p.get("totalAmountCurrencyCode"),
        "finance_charges": p.get("financeCharges") or [], "payments": p.get("payments") or [],
        "source_updated_at": parse_dt(p.get("updatedAt")),
    }


def investment(p: dict) -> dict:
    return {
        "id": p["id"], "item_id": p.get("itemId"), "name": p.get("name"), "number": p.get("number"),
        "code": p.get("code"), "isin": p.get("isin"), "type": p.get("type"), "subtype": p.get("subtype"),
        "status": p.get("status"), "currency": p.get("currencyCode"),
        "balance": num(p.get("balance")), "amount": num(p.get("amount")),
        "amount_original": num(p.get("amountOriginal")), "amount_profit": num(p.get("amountProfit")),
        "amount_withdrawal": num(p.get("amountWithdrawal")), "taxes": num(p.get("taxes")),
        "taxes2": num(p.get("taxes2")), "quantity": num(p.get("quantity")), "value": num(p.get("value")),
        "rate": num(p.get("rate")), "rate_type": p.get("rateType"),
        "fixed_annual_rate": num(p.get("fixedAnnualRate")), "annual_rate": num(p.get("annualRate")),
        "last_month_rate": num(p.get("lastMonthRate")), "last_12m_rate": num(p.get("lastTwelveMonthsRate")),
        "issuer": p.get("issuer"), "issuer_cnpj": digits(p.get("issuerCNPJ")),
        "due_date": local_date(p.get("dueDate")), "issue_date": local_date(p.get("issueDate")),
        "purchase_date": local_date(p.get("purchaseDate")), "reference_date": local_date(p.get("date")),
        "source_updated_at": parse_dt(p.get("updatedAt")),
    }


def investment_transaction(p: dict, investment_id: str) -> dict:
    return {
        "id": p["id"], "investment_id": investment_id, "type": p.get("type"),
        "movement_type": p.get("movementType"), "quantity": num(p.get("quantity")), "value": num(p.get("value")),
        "amount": num(p.get("amount")), "net_amount": num(p.get("netAmount")), "expenses": p.get("expenses"),
        "date": local_date(p.get("date")), "trade_date": local_date(p.get("tradeDate")),
        "description": p.get("description"), "brokerage_number": p.get("brokerageNumber"),
        "source_updated_at": parse_dt(p.get("updatedAt")),
    }


def loan(p: dict) -> dict:
    outstanding = p.get("contractOutstandingBalance")
    if outstanding is None:
        outstanding = p.get("totalRemainingAmount")
    return {
        "id": p["id"], "item_id": p.get("itemId"), "contract_number": p.get("contractNumber"),
        "product_name": p.get("productName"), "type": p.get("type"),
        "contract_amount": num(p.get("contractAmount")), "outstanding": num(outstanding),
        "next_installment_amount": num(p.get("nextInstallmentAmount")),
        "contract_date": local_date(p.get("contractDate")), "due_date": local_date(p.get("dueDate")),
        "cet": num(p.get("CET")), "interest_rates": p.get("interestRates"), "installments": p.get("installments"),
        "source_updated_at": parse_dt(p.get("updatedAt")),
    }
