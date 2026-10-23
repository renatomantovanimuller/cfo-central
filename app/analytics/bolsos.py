"""Bolsos: a finalidade de cada real do patrimônio (reserva de emergência, objetivos, aposentadoria) — e o que sobra,
"livre". Cada conta, investimento ou ativo manual pode ser dividido entre bolsos por fração; a soma das frações de
uma fonte nunca passa de 100%, então nenhum real é contado em dois objetivos (corrige metas que mediam "o
patrimônio inteiro" cada uma). Conta marcada com finalidade "Reserva" em Configurações vale como 100% no bolso da
reserva enquanto você não fizer uma divisão explícita.

Separar o dinheiro por objetivo, com rótulo visível, aumenta a poupança (Soman & Cheema); risco de um objetivo é
a chance de não atingi-lo (Das, Markowitz, Scheid & Statman).
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

RESERVE_NAME = "Reserva de emergência"
RV_CLASSES = {"Ações BR", "ETF Ações BR", "ETF Internacional", "FIIs", "Cripto"}
MARKED_TO_MARKET = {"Tesouro IPCA+", "Tesouro Prefixado"}


def sources(pos: dict) -> list[dict]:
    """Tudo o que pode ir para um bolso: contas (no patrimônio), investimentos e ativos manuais."""
    out = [{"type": "account", "id": c["account_id"], "label": c["name"], "institution": c.get("institution"),
            "value": c["balance"] or 0.0, "classe": "Caixa", "liquidez": "D0"} for c in pos.get("cash", [])]
    out += [{"type": "investment", "id": p["id"], "label": p["name"], "institution": p.get("institution"),
             "value": p["balance"] or 0.0, "classe": p.get("asset_class"), "liquidez": p.get("liquidity"),
             "vencimento": p.get("due_date")} for p in pos.get("positions", [])]
    out += [{"type": "manual", "id": str(m["id"]), "label": m["name"], "institution": None, "value": m["value"] or 0.0,
             "classe": m.get("class") or "Ativo manual", "liquidez": None} for m in pos.get("manual_assets", [])]
    return out


def ensure_reserve_bucket(s: Session):
    from app.models import Bucket
    b = s.scalar(select(Bucket).where(Bucket.kind == "reserva"))
    if b is None:
        b = Bucket(name=RESERVE_NAME, kind="reserva", sort=0)
        s.add(b)
        s.flush()
    return b


def _allocations(s: Session, src_keys: set) -> tuple[dict, dict]:
    """({bucket_id: [(chave, fração, origem)]}, {chave: fração total}) incluindo contas com finalidade Reserva."""
    from app.models import AccountSetting, Bucket, BucketAllocation
    per_bucket: dict[int, list] = defaultdict(list)
    used: dict[tuple, float] = defaultdict(float)
    for a in s.scalars(select(BucketAllocation)):
        k = (a.source_type, a.source_id)
        if k in src_keys and a.pct > 0:
            per_bucket[a.bucket_id].append((k, a.pct, "manual"))
            used[k] += a.pct
    reserve = s.scalar(select(Bucket).where(Bucket.kind == "reserva"))
    if reserve is not None:
        for st in s.scalars(select(AccountSetting).where(AccountSetting.purpose == "reserva")):
            k = ("account", st.account_id)
            if k in src_keys and used[k] == 0:  # finalidade da conta vale enquanto não houver divisão explícita
                per_bucket[reserve.id].append((k, 1.0, "finalidade"))
                used[k] = 1.0
    return per_bucket, used


def bucket_values(s: Session, pos: dict) -> dict:
    """{"by_bucket": {id: valor}, "reserve": valor|None (None = sem bolso de reserva com dinheiro)}."""
    from app.models import Bucket
    src = {(x["type"], x["id"]): x for x in sources(pos)}
    per_bucket, _ = _allocations(s, set(src))
    vals = {bid: sum(src[k]["value"] * pct for k, pct, _ in items) for bid, items in per_bucket.items()}
    reserve = s.scalar(select(Bucket).where(Bucket.kind == "reserva"))
    has_reserve = reserve is not None and bool(per_bucket.get(reserve.id))
    return {"by_bucket": vals, "reserve": vals.get(reserve.id, 0.0) if has_reserve else None}


def buckets_report(s: Session, pos: dict | None = None) -> dict:
    from app.accounting.balance import current_position
    from app.analytics.plano import plan, reserve_status
    from app.models import Bucket, FinancialGoal
    pos = pos or current_position(s)
    src_list = sources(pos)
    src = {(x["type"], x["id"]): x for x in src_list}
    per_bucket, used = _allocations(s, set(src))
    goals = {g.id: g for g in s.scalars(select(FinancialGoal))}
    res = reserve_status(s, pos, plan(s)["reserva_meses_minima"])
    out = []
    for b in s.scalars(select(Bucket).order_by(Bucket.sort, Bucket.id)):
        items = per_bucket.get(b.id, [])
        value = sum(src[k]["value"] * pct for k, pct, _ in items)
        g = goals.get(b.goal_id) if b.goal_id else None
        target = g.target_amount if g else (
            res["degraus"][-1]["valor"] if b.kind == "reserva" and res["degraus"] else None)
        rv = sum(src[k]["value"] * pct for k, pct, _ in items if src[k]["classe"] in RV_CLASSES)
        out.append({"id": b.id, "nome": b.name, "tipo": b.kind, "goal_id": b.goal_id, "valor": round(value, 2),
                    "alvo": round(target, 2) if target else None,
                    "progresso": (value / target) if target else None,
                    "fatia_renda_variavel": (rv / value) if value > 0 else 0.0,
                    "fontes": [{"type": k[0], "id": k[1], "label": src[k]["label"],
                                "institution": src[k]["institution"], "classe": src[k]["classe"],
                                "pct": round(pct, 4), "valor": round(src[k]["value"] * pct, 2), "origem": origem}
                               for k, pct, origem in items]})
    livre = sum(x["value"] * max(0.0, 1 - used.get((x["type"], x["id"]), 0.0)) for x in src_list)
    total = sum(x["value"] for x in src_list)
    fontes = [{**{k: v for k, v in x.items() if k != "vencimento"},
               "alocado": round(min(1.0, used.get((x["type"], x["id"]), 0.0)), 4)} for x in src_list]
    return {"bolsos": out, "livre": round(livre, 2), "total": round(total, 2), "fontes": fontes,
            "nota": "Cada fonte pode ser dividida entre bolsos (a soma não passa de 100%). O que não está em bolso "
                    "nenhum é livre. Conta com finalidade Reserva entra inteira na reserva até você dividir."}


def set_allocations(s: Session, bucket_id: int, items: list[dict]) -> None:
    """Substitui a divisão de um bolso. Recusa se alguma fonte passar de 100% somando os outros bolsos."""
    from app.models import BucketAllocation
    others: dict[tuple, float] = defaultdict(float)
    for a in s.scalars(select(BucketAllocation).where(BucketAllocation.bucket_id != bucket_id)):
        others[(a.source_type, a.source_id)] += a.pct
    for it in items:
        k = (it["source_type"], str(it["source_id"]))
        pct = float(it["pct"])
        if it["source_type"] not in ("account", "investment", "manual") or not 0 <= pct <= 1:
            raise ValueError(f"fonte ou fração inválida: {k}")
        if others[k] + pct > 1.0001:
            raise ValueError(f"{k[1]}: já há {others[k]:.0%} em outros bolsos; o máximo restante é {1 - others[k]:.0%}")
    for a in s.scalars(select(BucketAllocation).where(BucketAllocation.bucket_id == bucket_id)):
        s.delete(a)
    s.flush()
    for it in items:
        if float(it["pct"]) > 0:
            s.add(BucketAllocation(bucket_id=bucket_id, source_type=it["source_type"], source_id=str(it["source_id"]),
                                   pct=float(it["pct"])))
    s.flush()


def suggest_reserve(s: Session, pos: dict | None = None) -> dict:
    """Primeira divisão automática: contas com finalidade Reserva e aplicações de liquidez diária (sem marcação a
    mercado) entram no bolso da reserva até a meta do plano. Não mexe se a reserva já tiver divisão explícita."""
    from app.accounting.balance import current_position
    from app.analytics.plano import plan, reserve_status
    from app.models import AccountSetting, BucketAllocation
    pos = pos or current_position(s)
    b = ensure_reserve_bucket(s)
    if s.scalar(select(BucketAllocation).where(BucketAllocation.bucket_id == b.id).limit(1)):
        return {"criado": False, "motivo": "a reserva já tem divisão definida"}
    res = reserve_status(s, pos, plan(s)["reserva_meses_minima"])
    target = res["degraus"][-1]["valor"] if res["degraus"] else 0.0
    if target <= 0:
        return {"criado": False, "motivo": "sem custo essencial para calcular a meta da reserva"}
    reserve_accounts = {st.account_id
                        for st in s.scalars(select(AccountSetting).where(AccountSetting.purpose == "reserva"))}
    used: dict[tuple, float] = defaultdict(float)  # só divisões explícitas (a finalidade vira divisão aqui)
    for a in s.scalars(select(BucketAllocation)):
        used[(a.source_type, a.source_id)] += a.pct
    cands = [x for x in sources(pos) if x["type"] == "account" and x["id"] in reserve_accounts]
    # mesmo critério da reserva por liquidez: D0/D1 sem marcação a mercado, Tesouro Selic e RF com liquidez
    # diária comprovada (emissor/caixinha ou resgate parcial antes do vencimento)
    from app.models import InvestmentTransaction
    from app.portfolio.classification import has_daily_liquidity
    redeemed = set(s.scalars(select(InvestmentTransaction.investment_id).where(
        InvestmentTransaction.type == "SELL").distinct()))
    by_id = {p["id"]: p for p in pos.get("positions", [])}

    def daily(x: dict) -> bool:
        p = by_id.get(x["id"], {})
        if x["classe"] == "Tesouro Selic" or (x["liquidez"] in ("D0", "D1") and x["classe"] not in MARKED_TO_MARKET):
            return True
        return x["liquidez"] == "vencimento" and has_daily_liquidity({**p, "early_redemption": x["id"] in redeemed})
    cands += sorted([x for x in sources(pos) if x["type"] == "investment" and daily(x)], key=lambda x: -x["value"])
    left, items = target, []
    for x in cands:
        free = 1 - used.get((x["type"], x["id"]), 0.0)
        if left <= 0 or x["value"] <= 0 or free <= 0:
            continue
        pct = min(free, left / x["value"])
        items.append({"source_type": x["type"], "source_id": x["id"], "pct": round(pct, 4)})
        left -= x["value"] * pct
    if not items:
        return {"criado": False, "motivo": "nenhuma conta com finalidade Reserva nem aplicação de liquidez diária: "
                                           "escolha as fontes da reserva manualmente"}
    set_allocations(s, b.id, items)
    return {"criado": True, "fontes": len(items), "alvo": round(target, 2), "alocado": round(target - max(left, 0), 2)}
