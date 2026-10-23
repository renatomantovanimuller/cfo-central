"""Metas e plano de aportes.

- Cada meta mede o próprio bolso (o dinheiro separado para ela). Metas antigas que mediam "investimentos" ou
  "patrimônio" continuam funcionando, mas são marcadas: contam o mesmo dinheiro que as outras.
- O aporte do mês é distribuído numa ordem única: reserva de emergência (degraus) → metas por prioridade e prazo
  (o aporte necessário de cada uma) → carteira (classes abaixo do alvo). Se a meta de aporte não cobre a soma
  dos necessários, as últimas metas da fila aparecem atrasadas, com quanto falta.
- Cada meta é simulada com o aporte que de fato recebe, não com o aporte inteiro.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.utils.time import month_add, month_bounds, month_key, today_brt

KINDS = {"prazo": "Prazo definido", "aposentadoria": "Aposentadoria / independência", "livre": "Acúmulo livre"}
SHORT_HORIZON_MONTHS = 24
RV_LIMIT_SHORT = 0.20
SAFE_WITHDRAWAL = 0.04  # premissa editável na tela; referência para a meta de independência financeira


def _months_left(target_date, today) -> int | None:
    if not target_date:
        return None
    return max(1, (target_date.year - today.year) * 12 + target_date.month - today.month)


def needed_monthly(current: float, target: float, months: int | None, return_aa: float) -> float | None:
    """Aporte mensal constante que leva `current` a `target` em `months` meses com o retorno esperado."""
    if not months:
        return None
    r = (1 + return_aa) ** (1 / 12) - 1
    gap = target - current * (1 + r) ** months
    if gap <= 0:
        return 0.0
    return gap * r / ((1 + r) ** months - 1) if r > 0 else gap / months


def goals_status(s: Session, pos: dict) -> list[dict]:
    from app.analytics.bolsos import RV_CLASSES, _allocations, sources
    from app.models import Bucket, FinancialGoal
    today = today_brt()
    buckets = {b.goal_id: b for b in s.scalars(select(Bucket).where(Bucket.goal_id.is_not(None)))}
    src = {(x["type"], x["id"]): x for x in sources(pos)}
    per_bucket, _ = _allocations(s, set(src))
    bv = {bid: sum(src[k]["value"] * pct for k, pct, _ in items) for bid, items in per_bucket.items()}
    out = []
    order = (FinancialGoal.priority, FinancialGoal.target_date, FinancialGoal.id)
    for g in s.scalars(select(FinancialGoal).order_by(*order)):
        b = buckets.get(g.id)
        legacy = g.basis != "bucket"
        if legacy:
            current = {"net_worth": pos["totals"]["net_worth"], "investments": pos["totals"]["investments"],
                       "asset_class": pos["investments_by_class"].get(g.asset_class or "", 0.0),
                       "manual": g.manual_current or 0.0}.get(g.basis, 0.0)
            rv_share = 0.0
        else:
            current = bv.get(b.id, 0.0) if b else 0.0
            items = per_bucket.get(b.id, []) if b else []
            rv = sum(src[k]["value"] * pct for k, pct, _ in items if src[k]["classe"] in RV_CLASSES)
            rv_share = rv / current if current > 0 else 0.0
        months = _months_left(g.target_date, today)
        avisos = []
        if legacy and g.basis in ("net_worth", "investments"):
            avisos.append("Mede o patrimônio inteiro: conta o mesmo dinheiro que as outras metas. Converta para bolso.")
        if months and months <= SHORT_HORIZON_MONTHS and rv_share > RV_LIMIT_SHORT:
            avisos.append(f"Prazo de {months} meses com {rv_share:.0%} em renda variável: uma queda perto da data "
                          "atrasa a meta. Para prazo curto, prefira pós-fixado/Tesouro Selic.")
        out.append({"id": g.id, "name": g.name, "kind": g.kind, "kind_label": KINDS.get(g.kind, g.kind),
                    "priority": g.priority, "target_amount": g.target_amount, "target_date": g.target_date,
                    "basis": g.basis, "asset_class": g.asset_class, "bucket_id": b.id if b else None,
                    "current": round(current, 2), "progress": current / g.target_amount if g.target_amount else None,
                    "months_left": months, "expected_return_aa": g.expected_return_aa,
                    "monthly_needed": needed_monthly(current, g.target_amount, months, g.expected_return_aa),
                    "rv_share": rv_share, "legacy": legacy, "avisos": avisos})
    return out


def contribution_plan(aporte: float, reserva: dict, goals: list[dict], classes: list[dict], total_inv: float) -> dict:
    """Distribui o aporte: reserva → metas (prioridade, prazo) → carteira. Devolve também o status de cada meta."""
    from app.analytics.plano import aporte_direcionado
    left = max(0.0, aporte or 0.0)
    destinos = []
    nxt = reserva.get("proximo_degrau")
    if left > 0 and nxt and nxt["falta"] > 0:
        share = 1.0 if nxt["meses"] <= 3 else 0.5
        v = min(left * share, nxt["falta"])
        destinos.append({"destino": "Reserva de emergência", "tipo": "reserva", "valor": round(v, 2),
                         "motivo": f"degrau \"{nxt['nome']}\""})
        left -= v
    metas = []
    for g in goals:
        need = g["monthly_needed"]
        if g["legacy"] or need is None:
            metas.append({**g, "aporte_alocado": None, "status": "sem prazo" if need is None else "medida antiga"})
            continue
        v = min(left, need)
        left -= v
        status = "concluída" if need == 0 else "no ritmo" if v >= need * 0.98 else "atrasada"
        metas.append({**g, "aporte_alocado": round(v, 2), "falta_aporte": round(max(0.0, need - v), 2),
                      "status": status})
        if v > 0:
            destinos.append({"destino": g["name"], "tipo": "meta", "goal_id": g["id"], "valor": round(v, 2),
                             "motivo": (f"aporte necessário até {g['target_date']:%m/%Y}" if g["target_date"]
                                        else "meta")})
    carteira = aporte_direcionado(classes, total_inv, left, {"proximo_degrau": None}) if left > 0.5 else []
    destinos += [{**c, "tipo": "carteira"} for c in carteira]
    if left > 0.5 and not carteira:
        destinos.append({"destino": "Carteira (livre)", "tipo": "carteira", "valor": round(left, 2),
                         "motivo": "defina a alocação-alvo para direcionar por classe"})
    soma_necessaria = sum(m["monthly_needed"] or 0 for m in metas if not m["legacy"])
    return {"aporte": round(aporte or 0.0, 2), "destinos": destinos, "metas": metas,
            "soma_necessaria_metas": round(soma_necessaria, 2),
            "falta_para_metas": round(sum(m.get("falta_aporte") or 0 for m in metas), 2)}


def contributions_history(s: Session, meta_aporte: float | None, months: int = 12) -> dict:
    """Aporte líquido realizado por mês (aplicações − resgates) contra a meta atual e a sequência de meses
    cumpridos."""
    from app.models import FinancialEvent
    today = today_brt()
    ml = [month_add(month_key(today), -k) for k in range(months - 1, -1, -1)]
    start = month_bounds(ml[0])[0]
    by_m: dict[str, float] = defaultdict(float)
    for d, amt in s.execute(select(FinancialEvent.competence_date, FinancialEvent.amount).where(
            FinancialEvent.is_removed.is_(False), FinancialEvent.competence_date >= start,
            FinancialEvent.event_type.in_(["INVESTMENT_CONTRIBUTION", "INVESTMENT_REDEMPTION"]))):
        by_m[month_key(d)] += -amt
    rows = [{"mes": m, "realizado": round(by_m.get(m, 0.0), 2), "meta": meta_aporte,
             "cumprido": (by_m.get(m, 0.0) >= meta_aporte * 0.98) if meta_aporte else None} for m in ml]
    streak = 0
    for r in reversed(rows[:-1]):  # meses fechados, do mais recente para trás
        if r["cumprido"]:
            streak += 1
        else:
            break
    return {"meses": rows, "sequencia": streak, "mes_atual": rows[-1],
            "nota": "Realizado = aplicações − resgates do mês. A meta é a atual do plano (o histórico de metas não é "
                    "guardado)."}
