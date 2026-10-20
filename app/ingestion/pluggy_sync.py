"""Sincronização de um item Pluggy: bruto → camada 2 → snapshots. Cada etapa é isolada (falha parcial não perde o resto)."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Callable

from sqlalchemy import select, update

from app.config.settings import get_settings
from app.connectors.pluggy.client import PluggyClient, PluggyError
from app.ingestion.store import RunLogger, store_raw_many, upsert_rows
from app.models import (Account, AccountBalance, CreditCardBill, IdentityRecord, Institution, Investment,
                        InvestmentBalance, InvestmentTransaction, Item, Loan, PluggyCategory, Transaction)
from app.normalization import pluggy as N
from app.utils.time import today_brt, utcnow

log = logging.getLogger(__name__)
CARD_PAYMENT_HINTS = ("pagamento recebido", "pagamento efetuado", "pagto recebido", "pagamento obrigado")


def sync_categories(sf, client: PluggyClient) -> int:
    cats = client.categories()
    with sf() as s:
        upsert_rows(s, PluggyCategory, [{"id": c["id"], "description": c.get("description"),
                                         "description_pt": c.get("descriptionTranslated") or c.get("description"),
                                         "parent_id": c.get("parentId")} for c in cats])
        s.commit()
    return len(cats)


def sync_item(sf, client: PluggyClient, item_id: str, *, full: bool = False, trigger: str = "manual",
              progress: Callable[[str], None] = lambda _m: None) -> dict[str, Any]:
    settings = get_settings()
    rl = RunLogger(sf, "pluggy", trigger, item_id)
    stats: dict[str, Any] = {"accounts": 0, "transactions": 0, "tx_new": 0, "tx_removed": 0, "bills": 0,
                             "investments": 0, "investment_tx": 0, "loans": 0}

    def step(name: str, fn: Callable[[], None], critical: bool = False) -> bool:
        progress(name)
        try:
            fn()
            return True
        except Exception as exc:  # noqa: BLE001 — registrar e seguir
            level = "error"
            if isinstance(exc, PluggyError) and exc.status in (400, 403, 404):
                level = "warn"  # produto indisponível para este conector
            rl.log(level, name, str(exc))
            log.warning("sync %s/%s: %s", item_id, name, exc)
            if critical:
                raise
            return False

    # 1. item + instituição
    item_payload: dict = {}

    def do_item() -> None:
        nonlocal item_payload
        item_payload = client.item(item_id)
        with sf() as s:
            raw = store_raw_many(s, "item", [(item_id, item_payload)], item_id, rl.run_id)
            conn = item_payload.get("connector") or {}
            if conn.get("id") is not None:
                upsert_rows(s, Institution, [N.institution(conn)])
            upsert_rows(s, Item, [N.item(item_payload)], raw)
            s.commit()
        if item_payload.get("status") in ("LOGIN_ERROR", "OUTDATED", "WAITING_USER_INPUT"):
            rl.log("warn", "item", f"status {item_payload.get('status')} — talvez precise reconectar")

    try:
        step("item", do_item, critical=True)
    except Exception as exc:  # noqa: BLE001
        _finish_item(sf, item_id, "error")
        rl.finish(stats, error=str(exc))
        return {**stats, "status": "error", "error": str(exc), "run_id": rl.run_id}

    # 2. contas + snapshot de saldo
    accounts: list[dict] = []

    def do_accounts() -> None:
        payloads = client.accounts(item_id)
        with sf() as s:
            raw = store_raw_many(s, "account", [(p["id"], p) for p in payloads], item_id, rl.run_id)
            rows = [N.account(p) for p in payloads]
            upsert_rows(s, Account, rows, raw)
            today = today_brt()
            for r in rows:
                _upsert_snapshot(s, AccountBalance, {"account_id": r["id"], "date": today},
                                 {"balance": r["balance"], "credit_limit": r["credit_limit"],
                                  "available_credit": r["available_credit"], "collected_at": utcnow()})
            s.commit()
        accounts.extend(rows)
        stats["accounts"] = len(rows)

    step("accounts", do_accounts)

    # 3. transações por conta (janela incremental ou completa), faturas
    for acc in accounts:
        step(f"transactions:{acc['name']}", lambda acc=acc: _sync_transactions(sf, client, acc, item_id, full,
                                                                              settings.tx_window_days, rl, stats))
        if acc["type"] == "CREDIT":
            def do_bills(acc=acc) -> None:
                payloads = client.bills(acc["id"])
                with sf() as s:
                    raw = store_raw_many(s, "bill", [(p["id"], p) for p in payloads], item_id, rl.run_id)
                    upsert_rows(s, CreditCardBill, [N.bill(p, acc["id"]) for p in payloads], raw)
                    s.commit()
                stats["bills"] += len(payloads)
            step(f"bills:{acc['name']}", do_bills)

    # 4. investimentos + snapshot + movimentações
    def do_investments() -> None:
        payloads = client.investments(item_id)
        today = today_brt()
        with sf() as s:
            raw = store_raw_many(s, "investment", [(p["id"], p) for p in payloads], item_id, rl.run_id)
            rows = [N.investment(p) for p in payloads]
            upsert_rows(s, Investment, rows, raw)
            seen = {r["id"] for r in rows}
            if seen:
                s.execute(update(Investment).where(Investment.item_id == item_id, Investment.id.not_in(seen),
                                                   Investment.removed_at.is_(None)).values(removed_at=utcnow()))
            for r in rows:
                _upsert_snapshot(s, InvestmentBalance, {"investment_id": r["id"], "date": today},
                                 {"balance": r["balance"], "amount": r["amount"], "quantity": r["quantity"],
                                  "value": r["value"], "collected_at": utcnow()})
            s.commit()
        stats["investments"] = len(payloads)
        for p in payloads:
            def do_inv_tx(p=p) -> None:
                txs = client.investment_transactions(p["id"])
                with sf() as s:
                    raw = store_raw_many(s, "investment_transaction", [(t["id"], t) for t in txs], item_id, rl.run_id)
                    upsert_rows(s, InvestmentTransaction, [N.investment_transaction(t, p["id"]) for t in txs], raw)
                    s.commit()
                stats["investment_tx"] += len(txs)
            step(f"investment_tx:{p.get('code') or p['id'][:8]}", do_inv_tx)

    step("investments", do_investments)

    # 5. empréstimos
    def do_loans() -> None:
        payloads = client.loans(item_id)
        with sf() as s:
            raw = store_raw_many(s, "loan", [(p["id"], p) for p in payloads], item_id, rl.run_id)
            upsert_rows(s, Loan, [N.loan(p) for p in payloads], raw)
            s.commit()
        stats["loans"] = len(payloads)

    step("loans", do_loans)

    # 6. identidade (CPF/nome do titular → detecção de transferências próprias)
    def do_identity() -> None:
        p = client.identity(item_id)
        with sf() as s:
            raw = store_raw_many(s, "identity", [(p.get("id") or item_id, p)], item_id, rl.run_id)
            rec = s.get(IdentityRecord, item_id) or IdentityRecord(item_id=item_id)
            rec.full_name = p.get("fullName")
            rec.tax_number = N.digits(p.get("taxNumber") or p.get("document"))
            rec.raw_payload_id = next(iter(raw.values()), None)
            rec.updated_at = utcnow()
            s.add(rec)
            s.commit()

    step("identity", do_identity)

    status = "partial" if rl.errors else "ok"
    _finish_item(sf, item_id, status)
    rl.finish(stats)
    return {**stats, "status": status, "run_id": rl.run_id, "warnings": rl.warnings}


def _sync_transactions(sf, client: PluggyClient, acc: dict, item_id: str, full: bool, window_days: int,
                       rl: RunLogger, stats: dict) -> None:
    with sf() as s:
        last = s.scalar(select(Account.last_tx_sync_at).where(Account.id == acc["id"]))
    since = None if (full or not last) else today_brt() - timedelta(days=window_days)
    date_from = since.isoformat() if since else None
    payloads = list(client.transactions(acc["id"], date_from=date_from))
    with sf() as s:
        raw = store_raw_many(s, "transaction", [(p["id"], p) for p in payloads], item_id, rl.run_id)
        rows = [N.transaction(p, acc["id"], item_id) for p in payloads]
        rows = [r for r in rows if r["date"] is not None]
        ins, _ = upsert_rows(s, Transaction, rows, raw)
        stats["transactions"] += len(rows)
        stats["tx_new"] += ins
        # sumiu da fonte dentro da janela lida → soft delete (pendente que virou definitiva, estorno etc.)
        fetched = {r["id"] for r in rows}
        q = select(Transaction).where(Transaction.account_id == acc["id"], Transaction.removed_at.is_(None))
        if since:  # objeto date: no Postgres, comparar DATE com texto falha (no SQLite passava)
            q = q.where(Transaction.date > since)
        removed = 0
        if fetched:
            for tx in s.scalars(q):
                if tx.id not in fetched:
                    tx.removed_at = utcnow()
                    removed += 1
        stats["tx_removed"] += removed
        # convenção de sinal do cartão: compras são maioria
        sign = 1
        if acc["type"] == "CREDIT":
            pos = neg = 0
            for amount, cat, desc in s.execute(select(Transaction.amount, Transaction.pluggy_category_id,
                                                      Transaction.description)
                                               .where(Transaction.account_id == acc["id"],
                                                      Transaction.removed_at.is_(None))):
                if cat == "05100000" or any(h in (desc or "").lower() for h in CARD_PAYMENT_HINTS):
                    continue
                pos += amount > 0
                neg += amount < 0
            sign = -1 if pos > neg else 1
        s.execute(update(Account).where(Account.id == acc["id"]).values(card_sign=sign, last_tx_sync_at=utcnow()))
        s.execute(update(Transaction).where(Transaction.account_id == acc["id"])
                  .values(flow=Transaction.amount_brl * sign))
        s.commit()
    if removed:
        rl.log("info", "transactions", f"{removed} transações marcadas como removidas em {acc['name']}")


def _upsert_snapshot(s, model, keys: dict, values: dict) -> None:
    obj = s.scalars(select(model).filter_by(**keys)).first()
    if obj is None:
        s.add(model(**keys, **values))
    else:
        for k, v in values.items():
            setattr(obj, k, v)


def _finish_item(sf, item_id: str, status: str) -> None:
    with sf() as s:
        it = s.get(Item, item_id)
        if it:
            it.last_synced_at, it.last_sync_status = utcnow(), status
            s.commit()
