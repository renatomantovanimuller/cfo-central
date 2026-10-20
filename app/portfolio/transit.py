"""Saída de investimento sem contrapartida: "Valores em trânsito" e resolução persistente pelo usuário.

Quando o saldo de um investimento cai (> 2% e > R$ 50) entre dois snapshots, ou zera/entra em resgate total, procura-se
a contrapartida: venda em `investment_transactions` ou crédito compatível (±2%) em conta conectada, em ±5 dias úteis
(aproximados por ±7 dias corridos). Sem contrapartida, o valor que faltou continua no patrimônio como ativo em trânsito
até a contrapartida aparecer ou o usuário decidir. A decisão fica em `app_settings` (chave `transit_resolutions`).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.reviews import ReviewCandidate, fmt_brl
from app.models import (Account, AppSetting, FinancialEvent, Investment, InvestmentBalance,
                        InvestmentTransaction)
from app.utils.time import today_brt

DROP_PCT = 0.02
DROP_MIN_BRL = 50.0
MATCH_TOLERANCE = 0.02
WINDOW_DAYS = 7  # ≈ 5 dias úteis
SETTING_KEY = "transit_resolutions"
# créditos aceitos como contrapartida: resgates/rendimentos/transferências próprias; INCOME/REFUND só na mesma instituição
CREDIT_TYPES = ("INVESTMENT_REDEMPTION", "INVESTMENT_INCOME", "INTERNAL_TRANSFER", "EXTERNAL_OWN_TRANSFER",
                "INCOME", "REFUND")
TRANSFER_TYPES = ("INTERNAL_TRANSFER", "EXTERNAL_OWN_TRANSFER")
# renda variável/fundos: a saída é queda de quantidade (oscilação de preço não é saída)
QUANTITY_TYPES = ("EQUITY", "ETF", "MUTUAL_FUND", "FUND", "REAL_ESTATE_FUND", "FII")

# resolução → (rótulo, tratamento)
RESOLUTIONS = {
    "not_connected_account": ("Resgatado para conta não conectada", "perimeter_exit"),
    "custody_transferred": ("Transferido de custódia (continua como ativo)", "kept"),
    "provider_error": ("Erro do provedor — manter posição", "kept"),
    "loss": ("Perda / baixa", "writeoff"),
}
KEPT_LABELS = {"pending": "Valores em trânsito", "custody_transferred": "Custódia transferida",
               "provider_error": "Mantido (erro do provedor)"}


def exit_key(investment_id: str, d: date) -> str:
    return f"{investment_id}|{d.isoformat()}"


def load_resolutions(s: Session) -> dict:
    row = s.get(AppSetting, SETTING_KEY)
    return dict(row.value or {}) if row else {}


def set_resolution(s: Session, key: str, resolution: str, by: str = "user") -> None:
    if resolution not in RESOLUTIONS:
        raise ValueError(f"resolução desconhecida: {resolution}")
    cur = load_resolutions(s)
    cur[key] = {"resolution": resolution, "by": by}
    row = s.get(AppSetting, SETTING_KEY)
    if row is None:
        s.add(AppSetting(key=SETTING_KEY, value=cur))
    else:
        row.value = cur
    s.flush()


def _drop_amount(inv: Investment | None, prev, cur) -> float:
    """Valor da saída entre dois snapshots. Renda variável: Δquantidade × preço anterior; demais: Δsaldo."""
    pb, cb = prev.balance or 0.0, cur.balance or 0.0
    if inv is not None and (inv.type or "").upper() in QUANTITY_TYPES and prev.quantity and cur.quantity is not None:
        dq = prev.quantity - cur.quantity
        if dq <= 1e-9:
            return 0.0
        price = prev.value or (pb / prev.quantity)
        return dq * price
    return pb - cb


def _candidate_drops(s: Session) -> list[dict]:
    invs = {i.id: i for i in s.scalars(select(Investment))}
    by_inv: dict[str, list] = {}
    for b in s.scalars(select(InvestmentBalance).order_by(InvestmentBalance.investment_id, InvestmentBalance.date)):
        by_inv.setdefault(b.investment_id, []).append(b)
    out: list[dict] = []
    for inv_id, rows in by_inv.items():
        inv = invs.get(inv_id)
        rows = list(rows)
        if inv is not None and inv.removed_at is not None and (rows[-1].balance or 0.0) > 0 \
                and rows[-1].date <= inv.removed_at.date():
            # sumiu do payload da instituição sem snapshot zerado: equivale a queda para 0
            rows.append(SimpleNamespace(date=inv.removed_at.date(), balance=0.0, quantity=0.0, value=None))
        for i in range(1, len(rows)):
            prev, cur = rows[i - 1], rows[i]
            pb = prev.balance or 0.0
            drop = _drop_amount(inv, prev, cur)
            if drop <= max(DROP_MIN_BRL, DROP_PCT * pb):
                continue
            if any((r.balance or 0.0) >= (cur.balance or 0.0) + 0.9 * drop for r in rows[i + 1:]):
                continue  # saldo voltou: oscilação do provedor
            out.append({"investment_id": inv_id, "item_id": inv.item_id if inv else None, "date": cur.date,
                        "prev_date": prev.date, "amount": drop, "name": (inv.name if inv else None) or inv_id})
    return out


def _within(v: float, target: float) -> bool:
    return abs(v - target) <= target * MATCH_TOLERANCE


def detect_exits(s: Session) -> list[dict]:
    """Saídas sem contrapartida. Cada item: investment_id, name, date, amount, state, resolution, key.

    As quedas do mesmo item (instituição) na mesma data são somadas e comparadas com a soma líquida dos créditos
    (resgates − aportes) das contas da instituição na janela; cada crédito/venda é consumido uma única vez.
    A busca de contrapartida vai até hoje (crédito tardio fecha a saída; evita dupla contagem).
    """
    resolutions = load_resolutions(s)
    drops = _candidate_drops(s)
    if not drops:
        return []
    acc_item = {a.id: a.item_id for a in s.scalars(select(Account))}
    events = [e for e in s.scalars(select(FinancialEvent).where(
        FinancialEvent.is_removed.is_(False),
        FinancialEvent.event_type.in_(CREDIT_TYPES + ("INVESTMENT_CONTRIBUTION",))))]
    sells = [t for t in s.scalars(select(InvestmentTransaction)) if (t.type or "").upper() == "SELL"]
    today = today_brt()
    used_ev: set[int] = set()
    used_sell: set[str] = set()

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for d in drops:
        groups[(d["item_id"], d["date"])].append(d)
    out: list[dict] = []
    for (item_id, dt), grp in sorted(groups.items(), key=lambda kv: kv[0][1]):
        total = sum(g["amount"] for g in grp)
        lo = min(g["prev_date"] for g in grp) - timedelta(days=WINDOW_DAYS)
        hi = max(dt + timedelta(days=WINDOW_DAYS), today)
        ids = {g["investment_id"] for g in grp}
        # (i) vendas registradas dos investimentos da queda
        cand_s = [t for t in sells if t.id not in used_sell and t.investment_id in ids
                  and (t.date or t.trade_date) and lo <= (t.date or t.trade_date) <= hi]
        sell_sum = sum(abs(t.amount if t.amount is not None else (t.net_amount or 0.0)) for t in cand_s)
        if cand_s and _within(sell_sum, total):
            used_sell |= {t.id for t in cand_s}
            continue
        # (ii) soma líquida dos créditos da mesma instituição
        same = [e for e in events if e.id not in used_ev and lo <= e.competence_date <= hi
                and acc_item.get(e.account_id) == item_id]
        credits = [e for e in same if e.event_type in CREDIT_TYPES and e.amount > 0]
        contribs = [e for e in same if e.event_type == "INVESTMENT_CONTRIBUTION" and e.amount < 0]
        net = sum(e.amount for e in credits) - sum(-e.amount for e in contribs)
        if credits and _within(net, total):
            used_ev |= {e.id for e in credits + contribs}
            continue
        # (iii) transferência própria para conta de outra instituição (crédito único)
        other = next((e for e in events if e.id not in used_ev and e.event_type in TRANSFER_TYPES and e.amount > 0
                      and lo <= e.competence_date <= hi and _within(e.amount, total)), None)
        if other is not None:
            used_ev.add(other.id)
            continue
        for g in grp:
            key = exit_key(g["investment_id"], dt)
            res = (resolutions.get(key) or {}).get("resolution")
            out.append({"key": key, "investment_id": g["investment_id"], "name": g["name"], "date": dt,
                        "amount": round(g["amount"], 2), "state": res or "pending", "resolution": res})
    return out


def transit_summary(exits: list[dict]) -> dict:
    """Totais por tratamento: entram no PL (pending/custody/provider_error) ou saem como movimento explícito."""
    kept, lines = 0.0, []
    perimeter = writeoff = 0.0
    for e in exits:
        treat = "kept" if e["state"] == "pending" else RESOLUTIONS[e["state"]][1]
        if treat == "kept":
            kept += e["amount"]
            lines.append({**e, "label": KEPT_LABELS[e["state"]]})
        elif treat == "perimeter_exit":
            perimeter += e["amount"]
        else:
            writeoff += e["amount"]
    return {"in_transit": round(kept, 2), "lines": lines, "perimeter_exits": round(perimeter, 2),
            "writeoffs": round(writeoff, 2)}


def exit_reviews(s: Session) -> list[ReviewCandidate]:
    out = []
    for e in detect_exits(s):
        if e["state"] != "pending":
            continue
        out.append(ReviewCandidate(
            f"exit:{e['key']}", "exit_no_counterpart", "high", "investment", e["investment_id"],
            f"Saída de {fmt_brl(e['amount'])} de {e['name']} sem contrapartida",
            f"O saldo caiu em {e['date']:%d/%m/%Y} sem venda registrada nem crédito compatível em conta conectada "
            f"(±2%, ±5 dias úteis). O valor está mantido no patrimônio como \"Valores em trânsito\" até aparecer a "
            f"contrapartida ou você decidir.",
            {"amount": e["amount"], "date": e["date"].isoformat(), "key": e["key"],
             "options": [{"id": k, "label": v[0]} for k, v in RESOLUTIONS.items()]}))
    return out
