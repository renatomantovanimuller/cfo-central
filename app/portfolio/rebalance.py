"""Rebalanceamento: onde aplicar o próximo aporte para aproximar a carteira da alocação-alvo, sem vender, e qual
seria o rebalanceamento completo (com vendas e IR estimado). Só mede contra os alvos definidos por você; não
recomenda produto — sugere reforçar a posição que você já tem em cada classe."""
from __future__ import annotations

import math
from collections import defaultdict

from sqlalchemy.orm import Session

from app.utils.time import today_brt

EQUITY_RATE = {"ETF Ações BR": 0.15, "ETF Internacional": 0.15, "Ações BR": 0.15, "FIIs": 0.20, "Cripto": 0.15}
RV_CLASSES = set(EQUITY_RATE)


def _regressive(days: int) -> float:
    return 0.225 if days <= 180 else 0.20 if days <= 360 else 0.175 if days <= 720 else 0.15


def _sell_tax(p: dict, amount: float, lots: dict) -> tuple[float | None, str]:
    """IR estimado ao vender `amount` (valor de mercado) da posição p."""
    bal = p["balance"] or 0.0
    if bal <= 0 or amount <= 0:
        return 0.0, ""
    share = min(1.0, amount / bal)
    cls = p["asset_class"]
    if cls in RV_CLASSES:
        lot = lots.get((p.get("code") or "").upper())
        if not lot or not lot.get("custo_completo") or not lot.get("custo_conhecido"):
            return None, "custo desconhecido"
        gain = (lot["quantidade"] * (lot["preco_atual"] or 0) - lot["custo_conhecido"]) * share
        note = "Ações BR: isento se as vendas do mês somarem até R$ 20 mil" if cls == "Ações BR" else ""
        return max(0.0, gain) * EQUITY_RATE[cls], note
    if cls == "ETF Renda Fixa":
        return None, "IR retido na fonte pelo administrador (regra própria de ETF de renda fixa)"
    cost = p.get("cost")
    if not cost:
        return None, "custo desconhecido"
    gross = p.get("gross") or bal
    start = p.get("purchase_date")
    days = (today_brt() - start).days if start else 721
    return max(0.0, gross - cost) * share * _regressive(days), f"alíquota regressiva {_regressive(days):.1%}"


def suggest(s: Session, aporte: float | None = None) -> dict:
    from app.analytics.plano import plan, policy_report, safe_to_spend
    from app.portfolio.service import positions
    pol = policy_report(s)
    targets = {c["classe"]: c["alvo"] for c in pol["classes"] if c["alvo"] is not None and c["alvo"] > 0}
    if not targets:
        return {"available": False, "reason": "Defina a alocação-alvo por classe em Planejamento para ver as sugestões."}
    pos = positions(s)
    if aporte is None:
        p = plan(s)
        if p.get("meta_aporte_mensal") is not None:
            aporte, origem = float(p["meta_aporte_mensal"]), "meta de aporte do plano"
        else:
            try:
                aporte, origem = float(safe_to_spend(s)["meta_aporte"]), "meta de aporte calculada no planejamento"
            except Exception:  # noqa: BLE001
                aporte, origem = 0.0, "sem meta definida"
    else:
        origem = "informado"
    aporte = max(0.0, float(aporte or 0.0))

    by_class: dict[str, float] = defaultdict(float)
    best: dict[str, dict] = {}
    for p in pos:
        by_class[p["asset_class"]] += p["balance"]
        if p["asset_class"] not in best or p["balance"] > best[p["asset_class"]]["balance"]:
            best[p["asset_class"]] = p
    # reserva de emergência vem antes: completa em liquidez diária (classe RF Pós)
    r = pol["reserva"]
    reserva_falta = 0.0
    if not r.get("ok") and r.get("meses") is not None:
        reserva_falta = max(0.0, r["minimo_meses"] * r["custo_essencial_mensal"] - r["liquido_d0_d1"])
    para_reserva = min(aporte, reserva_falta)
    livre = aporte - para_reserva

    tsum = sum(targets.values())
    tw = {c: t / tsum for c, t in targets.items()}  # alvos normalizados entre as classes com alvo
    cur = {c: by_class.get(c, 0.0) for c in tw}
    if para_reserva:
        cur["RF Pós"] = cur.get("RF Pós", 0.0) + para_reserva
        tw.setdefault("RF Pós", 0.0)
    base = sum(cur.values())
    total_after = base + livre
    deficit = {c: max(0.0, tw.get(c, 0.0) * total_after - cur[c]) for c in cur}
    dsum = sum(deficit.values())
    if livre <= 0:
        alloc = {c: 0.0 for c in cur}
    elif dsum >= livre:
        alloc = {c: livre * deficit[c] / dsum for c in cur}
    else:
        alloc = {c: deficit[c] + (livre - dsum) * tw.get(c, 0.0) for c in cur}

    lots = {}
    try:
        from app.portfolio.realized import equity_lots
        lots = {(a["ativo"] or "").upper(): a for a in equity_lots(s)["ativos"]}
    except Exception:  # noqa: BLE001
        pass

    rows = []
    for c in sorted(cur, key=lambda x: -(alloc.get(x, 0.0))):
        after = cur[c] + alloc[c]
        bp = best.get(c)
        row = {"classe": c, "atual": round(by_class.get(c, 0.0), 2), "peso_atual": by_class.get(c, 0.0) / base if base else 0.0,
               "alvo": tw.get(c), "aplicar": round(alloc[c] + (para_reserva if c == "RF Pós" else 0.0), 2),
               "peso_depois": after / total_after if total_after else 0.0,
               "desvio_depois_pp": ((after / total_after) - tw.get(c, 0.0)) * 100 if total_after else None,
               "sugestao": None}
        amount = row["aplicar"]
        if amount >= 1 and bp:
            name = bp.get("code") or bp.get("name")
            price = bp.get("unit_price")
            if c in RV_CLASSES or c == "ETF Renda Fixa":
                cotas = math.floor(amount / price) if price else None
                row["sugestao"] = {"ativo": name, "cotas": cotas, "preco": price,
                                   "texto": f"{cotas} cotas de {name}" if cotas else f"reforçar {name}"}
            else:
                row["sugestao"] = {"ativo": name, "texto": f"reforçar {name}" + (" (liquidez diária)" if bp.get("liquidity") == "D0" else "")}
        elif amount >= 1:
            row["sugestao"] = {"ativo": None, "texto": "classe sem posição hoje: escolha o produto"}
        rows.append(row)

    # rebalanceamento completo (com vendas) para o mesmo total
    full = []
    tax_total, tax_unknown = 0.0, []
    for c in cur:
        delta = tw.get(c, 0.0) * total_after - cur[c]
        item = {"classe": c, "operacao": "comprar" if delta > 0 else "vender" if delta < 0 else "manter",
                "valor": round(abs(delta), 2), "ir_estimado": 0.0, "observacao": ""}
        if delta < -1:
            remaining = -delta
            members = sorted([p for p in pos if p["asset_class"] == c], key=lambda p: -p["balance"])
            ir, notes = 0.0, set()
            for p in members:
                take = min(remaining, p["balance"])
                t, note = _sell_tax(p, take, lots)
                if t is None:
                    tax_unknown.append(p.get("code") or p.get("name"))
                    notes.add(note)
                else:
                    ir += t
                    if note:
                        notes.add(note)
                remaining -= take
                if remaining <= 0.01:
                    break
            item["ir_estimado"] = round(ir, 2)
            item["observacao"] = "; ".join(sorted(n for n in notes if n))
            tax_total += ir
        full.append(item)
    untargeted = sorted(set(by_class) - set(tw))
    return {
        "available": True, "aporte": round(aporte, 2), "origem_aporte": origem,
        "reserva": {"falta": round(reserva_falta, 2), "aplicar": round(para_reserva, 2),
                    "meses": r.get("meses"), "minimo_meses": r.get("minimo_meses")},
        "aporte_sem_venda": rows,
        "rebalanceamento_completo": {"operacoes": sorted(full, key=lambda x: (x["operacao"] != "vender", -x["valor"])),
                                     "ir_estimado": round(tax_total, 2), "ir_nao_estimado": sorted(set(tax_unknown))},
        "classes_sem_alvo": [{"classe": c, "valor": round(by_class[c], 2)} for c in untargeted],
        "soma_alvos": tsum,
        "nota": "Aporte sem venda: o dinheiro vai para as classes mais abaixo do alvo (proporcional ao que falta); "
                "se sobrar, segue os pesos-alvo. A reserva de emergência é completada antes. Rebalanceamento completo "
                "leva tudo ao alvo, com IR estimado sobre as vendas (renda fixa pela tabela regressiva; renda "
                "variável só com custo conhecido). Classes sem alvo ficam de fora do cálculo.",
    }
