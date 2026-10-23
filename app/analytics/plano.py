"""Planejamento: preferências do plano, 'quanto posso gastar este mês', política de investimentos (alocação-alvo
com bandas) e simulação de metas por Monte Carlo. Nada aqui recomenda produto: só mede contra regras do usuário."""
from __future__ import annotations

import calendar
import statistics
from datetime import date, timedelta

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounting.statements import dre, month_list
from app.alerts.reviews import ReviewCandidate, fmt_brl
from app.models import AllocationTarget, AppSetting, FinancialEvent, RecurringRule
from app.utils.time import month_add, month_bounds, month_key, today_brt

PLAN_DEFAULTS = {
    "meta_aporte_mensal": None,      # R$/mês que você quer investir; None = usa 20% da receita recorrente
    "reserva_meses_minima": 6,       # meses de custo essencial que devem estar em liquidez D0/D1
    "limite_fgc": 250000.0,
    "retorno_esperado_aa": None,     # None = usa o histórico ex-ante da carteira
    "aumento_para_aporte": None,     # fração de cada aumento de renda que vai para o aporte (None = desligado)
    "score_credito": None,           # informado pelo usuário (o Open Finance não traz); entra na saúde financeira
}
EXPENSE_LIKE = ("EXPENSE", "FINANCIAL_EXPENSE", "TAX", "REFUND")
ANNUAL_DAYS = 300  # recorrência com intervalo a partir disso é anual (provisionada mês a mês)
# degraus da reserva: o colchão pequeno é o que mais pesa no bem-estar (Vanguard, 2024); depois 3 meses e a meta
RESERVE_STEPS = [("Colchão inicial", 1.0), ("Três meses", 3.0)]
# banda de rebalanceamento "5/25": 5 p.p. ou 25% do alvo, o que for menor (classes pequenas não ficam sem controle)
BAND_ABS, BAND_REL = 0.05, 0.25


def get_setting(s: Session, key: str, defaults: dict | None = None) -> dict:
    row = s.get(AppSetting, key)
    return {**(defaults or {}), **((row.value or {}) if row else {})}


def put_setting(s: Session, key: str, value: dict) -> dict:
    row = s.get(AppSetting, key) or AppSetting(key=key, value={})
    merged = {**(row.value or {}), **value}
    row.value = merged
    s.add(row)
    s.flush()
    return merged


def plan(s: Session) -> dict:
    return get_setting(s, "plano", PLAN_DEFAULTS)


# ------------------------------------------------------------------ quanto posso gastar
def safe_to_spend(s: Session, today: date | None = None) -> dict:
    today = today or today_brt()
    month = month_key(today)
    a, b = month_bounds(month)
    hist = month_list(month_add(month, -1), 3)
    d = dre(s, hist + [month], with_valuation=False)
    rows = {r["key"]: r["values"] for r in d["rows"]}
    # bônus/PLR entra no resultado, mas não é renda de todo mês: fica fora da base de previsão
    bonus = {m: 0.0 for m in hist + [month]}
    for amt, dt in s.execute(select(FinancialEvent.amount, FinancialEvent.competence_date).where(
            FinancialEvent.is_removed.is_(False), FinancialEvent.category_id == "rec.bonus",
            FinancialEvent.competence_date.between(month_bounds(hist[0])[0], b))):
        key = month_key(dt)
        if key in bonus:
            bonus[key] += amt
    rec_hist = [rows["receita_liquida"][m] - bonus[m] for m in hist if rows["receita_liquida"][m] - bonus[m] > 0]
    renda_base = statistics.median(rec_hist) if rec_hist else 0.0
    recebido = rows["receita_liquida"][month] - bonus[month]
    renda = max(renda_base, recebido)
    p = plan(s)
    if p["meta_aporte_mensal"] is not None:
        aporte, origem = p["meta_aporte_mensal"], "plano"
    else:
        # sem meta definida: 20% da renda, mas nunca mais do que de fato sobrou nos meses anteriores
        # (sugerir aporte de 20% a quem fecha o mês no vermelho só empurra o "quanto posso gastar" para baixo de zero)
        sobra = [rows["resultado_liquido"][m] for m in hist]
        teto = max(0.0, statistics.median(sobra)) if sobra else 0.0
        aporte = round(min(0.2 * renda, teto), 2)
        origem = "padrao" if aporte >= round(0.2 * renda, 2) else "padrao_limitado"

    gasto = -(s.scalar(select(func.coalesce(func.sum(FinancialEvent.amount), 0.0)).where(
        FinancialEvent.is_removed.is_(False), FinancialEvent.competence_date.between(a, b),
        FinancialEvent.event_type.in_(EXPENSE_LIKE))) or 0.0)
    pendentes, provisoes = [], []
    for r in s.scalars(select(RecurringRule).where(RecurringRule.direction == "out", RecurringRule.status != "ignored")):
        paid_this_month = r.last_date is not None and r.last_date >= a
        if r.next_date and today <= r.next_date <= b and not paid_this_month:
            pendentes.append({"descricao": r.description, "valor": r.expected_amount, "data": r.next_date})
        elif (r.frequency_days or 30) >= ANNUAL_DAYS and r.next_date and r.next_date > b and not paid_this_month:
            # custo verdadeiro: a despesa anual de daqui a meses já consome 1/12 da renda deste mês
            provisoes.append({"descricao": r.description, "valor": round(r.expected_amount / 12, 2),
                              "anual": r.expected_amount, "data": r.next_date})
    comprometido = sum(x["valor"] for x in pendentes)
    provisao = sum(x["valor"] for x in provisoes)
    disponivel = renda - aporte - gasto - comprometido - provisao
    dias_rest = (b - today).days + 1
    dias_mes = calendar.monthrange(today.year, today.month)[1]
    ritmo = gasto / today.day * dias_mes if today.day else gasto
    return {
        "mes": month, "renda_prevista": round(renda, 2), "renda_recebida": round(recebido, 2),
        "meta_aporte": round(aporte, 2), "meta_aporte_origem": origem, "gasto_ate_hoje": round(gasto, 2),
        "recorrencias_pendentes": pendentes, "comprometido": round(comprometido, 2),
        "provisoes_anuais": sorted(provisoes, key=lambda x: x["data"]), "provisao": round(provisao, 2),
        "disponivel": round(disponivel, 2), "por_dia": round(disponivel / dias_rest, 2) if dias_rest > 0 else None,
        "dias_restantes": dias_rest, "projecao_gasto_mes": round(ritmo + comprometido, 2),
        "premissas": [
            "Renda prevista = maior entre a mediana da receita recorrente dos 3 meses anteriores e o já recebido no mês (sem bônus/PLR).",
            "Meta de aporte = configurada no plano; sem meta, 20% da renda prevista limitado à sobra mediana dos 3 meses anteriores.",
            "Gasto até hoje = despesas do mês por competência (cartão na data da compra), já descontados reembolsos.",
            "Recorrências pendentes = gastos recorrentes detectados com próxima data ainda neste mês.",
            "Provisão anual = 1/12 das despesas anuais previstas (IPVA, IPTU, seguro, anuidade…) que vencem nos "
            "próximos meses; no mês do vencimento entra o valor cheio como recorrência pendente.",
            "Extraordinários (herança, doações) e entradas ainda a classificar (Pix de terceiros) "
            "não entram na renda.",
        ],
    }


# ------------------------------------------------------------------ poupar mais amanhã (aumentos de renda)
RAISE_MIN_PCT, RAISE_MIN_BRL = 0.05, 100.0


def salary_raise(s: Session, today: date | None = None) -> dict | None:
    """Aumento de renda recorrente: os 2 últimos meses fechados de salário acima do patamar anterior (mediana dos
    4 meses antes deles, ou o nível do último aumento já aplicado). Exigir 2 meses evita 13º, férias e bônus."""
    today = today or today_brt()
    months = month_list(month_add(month_key(today), -1), 6)
    start = month_bounds(months[0])[0]
    totals = {m: 0.0 for m in months}
    for amt, dt in s.execute(select(FinancialEvent.amount, FinancialEvent.competence_date).where(
            FinancialEvent.is_removed.is_(False), FinancialEvent.category_id == "rec.salario",
            FinancialEvent.event_type == "INCOME", FinancialEvent.competence_date >= start,
            FinancialEvent.competence_date <= month_bounds(months[-1])[1])):
        totals[month_key(dt)] += amt
    vals = [totals[m] for m in months]
    before = [v for v in vals[:-2] if v > 0]
    if len(before) < 4 or min(vals[-2:]) <= 0:
        return None
    applied = get_setting(s, "aumentos", {"aplicados": []})["aplicados"]
    ref = max(statistics.median(before), max((a["depois"] for a in applied), default=0.0))
    recent = min(vals[-2:])
    if recent < ref * (1 + RAISE_MIN_PCT) or recent - ref < RAISE_MIN_BRL:
        return None
    return {"mes": months[-2], "antes": round(ref, 2), "depois": round(recent, 2), "aumento": round(recent - ref, 2)}


def salary_raises(s: Session) -> dict:
    return {"fracao": plan(s)["aumento_para_aporte"], "detectado": salary_raise(s),
            "aplicados": get_setting(s, "aumentos", {"aplicados": []})["aplicados"][-12:]}


def salary_raise_reviews(s: Session) -> list[ReviewCandidate]:
    """Com a regra ligada, sobe a meta de aporte uma vez por aumento (pré-compromisso: a decisão foi tomada antes
    do dinheiro chegar). Desligada, pergunta na Revisão."""
    r = salary_raise(s)
    if r is None:
        return []
    p = plan(s)
    frac = p["aumento_para_aporte"]
    if frac is None:
        return [ReviewCandidate(
            f"raise:{round(r['depois'], -2):.0f}", "salary_raise", "warn", "plan", "aporte",
            f"Sua renda recorrente subiu {fmt_brl(r['aumento'])}/mês "
            f"(de {fmt_brl(r['antes'])} para {fmt_brl(r['depois'])})",
            "Quer que parte de cada aumento vá automaticamente para o aporte? Defina a fração em Planejamento → "
            "Plano. Decidir antes de se acostumar com o dinheiro novo é o que mais faz a poupança crescer.",
            {"amount": r["aumento"]})]
    extra = round(frac * r["aumento"], 2) if p["meta_aporte_mensal"] is not None else 0.0
    if extra:
        put_setting(s, "plano", {"meta_aporte_mensal": round(p["meta_aporte_mensal"] + extra, 2)})
    hist = get_setting(s, "aumentos", {"aplicados": []})["aplicados"]
    put_setting(s, "aumentos", {"aplicados": [*hist, {**r, "acrescimo_aporte": extra,
                                                       "aplicado_em": today_brt().isoformat()}]})
    detail = (f"Meta de aporte subiu {fmt_brl(extra)} ({frac:.0%} do aumento), como você definiu no plano."
              if extra else "Sua meta de aporte é a automática (20% da renda), que já acompanha o aumento.")
    return [ReviewCandidate(f"raise_applied:{r['mes']}", "salary_raise_applied", "info", "plan", "aporte",
                            f"Aumento de {fmt_brl(r['aumento'])}/mês detectado", detail, {"amount": r["aumento"]})]


# ------------------------------------------------------------------ política de investimentos
def reserve_status(s: Session, pos: dict, minimo_meses: float) -> dict:
    """Reserva de emergência em degraus (colchão inicial → 3 meses → meta do plano), em meses de custo essencial.
    Custo essencial = média dos meses fechados com dado (meses anteriores ao histórico não entram como zero)."""
    from app.accounting.management import reserva_liquida
    hist = month_list(month_add(month_key(today_brt()), -1), 6)
    d = dre(s, hist, with_valuation=False)
    ess = [-v for v in next(r for r in d["rows"] if r["key"] == "essenciais")["values"].values() if v]
    ess_med = statistics.mean(ess) if ess else 0.0
    from app.analytics.bolsos import bucket_values
    in_bucket = bucket_values(s, pos)["reserve"]  # bolso da reserva, quando você separou o dinheiro
    liquido = in_bucket if in_bucket is not None else reserva_liquida(s, pos)
    meses = liquido / ess_med if ess_med > 0 else None
    steps = [x for x in RESERVE_STEPS if x[1] < minimo_meses] + [("Meta do plano", float(minimo_meses))]
    degraus = [{"nome": nome, "meses": m, "valor": round(m * ess_med, 2), "atingido": liquido >= m * ess_med,
                "falta": round(max(0.0, m * ess_med - liquido), 2)} for nome, m in steps]
    atual = next((g for g in degraus if not g["atingido"]), None)
    return {"liquido_d0_d1": round(liquido, 2), "custo_essencial_mensal": round(ess_med, 2), "meses": meses,
            "minimo_meses": minimo_meses, "ok": meses is None or meses >= minimo_meses, "degraus": degraus,
            "proximo_degrau": atual, "abaixo_do_colchao": bool(ess_med > 0 and degraus and not degraus[0]["atingido"]),
            "fonte": "bolso" if in_bucket is not None else "liquidez"}


def aporte_direcionado(classes: list[dict], total: float, aporte: float, reserva: dict) -> list[dict]:
    """Para onde vai o aporte do mês, sem vender nada (rebalancear pelo fluxo evita IR e custos):
    1º a reserva (todo o aporte até 3 meses de essenciais, metade dele daí até a meta do plano); depois cobre o que falta às classes abaixo do alvo, considerando o
    total depois do aporte; sobra vai na proporção dos alvos. Só classes, nunca produtos."""
    out: list[dict] = []
    left = max(0.0, aporte)
    nxt = reserva.get("proximo_degrau")
    if left > 0 and nxt and nxt["falta"] > 0:
        # até 3 meses a reserva leva tudo (é onde está o ganho de segurança); dali até a meta, metade do aporte
        share = 1.0 if nxt["meses"] <= 3 else 0.5
        v = min(left * share, nxt["falta"])
        out.append({"destino": "Reserva de emergência (liquidez diária)", "valor": round(v, 2),
                    "motivo": f"completar o degrau \"{nxt['nome']}\" "
                              f"({nxt['meses']:g} {'mês' if nxt['meses'] == 1 else 'meses'} de essenciais)"})
        left -= v
    alvos = [c for c in classes if c["alvo"]]
    if left <= 0.005 or not alvos:
        return out
    final_total = total + left
    gaps = {c["classe"]: max(0.0, c["alvo"] * final_total - c["valor"]) for c in alvos}
    gap_sum = sum(gaps.values())
    if gap_sum >= left:
        alloc = {k: left * g / gap_sum for k, g in gaps.items()}
    else:
        tgt_sum = sum(c["alvo"] for c in alvos)
        alloc = {c["classe"]: gaps[c["classe"]] + (left - gap_sum) * c["alvo"] / tgt_sum for c in alvos}
    for c in sorted(alvos, key=lambda c: -alloc[c["classe"]]):
        v = alloc[c["classe"]]
        if v >= 1:
            out.append({"destino": c["classe"], "valor": round(v, 2),
                        "motivo": "abaixo do alvo" if gaps[c["classe"]] > 0 else "manter a proporção dos alvos"})
    return out


REGRESSIVE = [(180, 0.225), (360, 0.20), (720, 0.175)]  # IR de renda fixa por prazo; acima de 720 dias, 15%
TAX_FREE_SUBTYPES = {"LCI", "LCA", "CRI", "CRA", "DEBENTURE_INCENTIVADA", "POUPANCA"}


def calendario_fiscal(positions: list[dict], today=None, window: int = 30) -> dict:
    """Títulos de renda fixa a até `window` dias de cair de faixa do IR regressivo (resgatar antes custa mais)
    e o próximo come-cotas (último dia útil de maio e de novembro) quando há fundos."""
    today = today or today_brt()
    faixas = []
    for p in positions:
        if (p.get("type") or "").upper() != "FIXED_INCOME" or (p.get("subtype") or "").upper() in TAX_FREE_SUBTYPES:
            continue
        start = p.get("purchase_date")
        if not start:
            continue
        held = (today - start).days
        for limit, rate in REGRESSIVE:
            if held <= limit:
                days_left = limit - held + 1
                nxt = next((r for lim, r in REGRESSIVE if lim > limit), 0.15)
                if days_left <= window:
                    faixas.append({"titulo": p["name"], "instituicao": p.get("institution"), "saldo": p["balance"],
                                   "dias": days_left, "data": today + timedelta(days=days_left),
                                   "de": rate, "para": nxt})
                break
    come_cotas = None
    if any((p.get("type") or "").upper() == "MUTUAL_FUND" for p in positions):
        for y, m in ((today.year, 5), (today.year, 11), (today.year + 1, 5)):
            d = _last_business_day(y, m)
            if d >= today:
                come_cotas = d
                break
    return {"faixas": sorted(faixas, key=lambda x: x["dias"]), "come_cotas": come_cotas}


def _last_business_day(y: int, m: int):
    d = month_bounds(f"{y:04d}-{m:02d}")[1]
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def policy_report(s: Session, aporte: float | None = None) -> dict:
    from app.accounting.balance import current_position
    from app.portfolio.service import allocation, fgc_exposure

    p = plan(s)
    pos = current_position(s)
    positions = pos.get("positions", [])
    alloc = allocation(positions) if positions else {"total": 0, "by_class": []}
    current = {x["label"]: x["pct"] for x in alloc["by_class"]}
    targets = {t.asset_class: t for t in s.scalars(select(AllocationTarget))}
    total = alloc["total"] or 0.0
    linhas = []
    for cls in sorted(set(current) | set(targets)):
        t = targets.get(cls)
        cur = current.get(cls, 0.0)
        tgt = t.target_pct if t else None
        band = min(BAND_ABS, BAND_REL * tgt) if tgt is not None else None
        lo = (t.min_pct if t and t.min_pct is not None else (max(0.0, tgt - band) if tgt is not None else None))
        hi = (t.max_pct if t and t.max_pct is not None else (tgt + band if tgt is not None else None))
        status = "sem alvo" if tgt is None else ("abaixo" if cur < lo - 1e-9 else "acima" if cur > hi + 1e-9 else "ok")
        linhas.append({"classe": cls, "atual": cur, "valor": round(cur * total, 2), "alvo": tgt, "min": lo, "max": hi,
                       "status": status,
                       "ajuste_para_alvo": round((tgt - cur) * total, 2) if tgt is not None else None})
    soma_alvos = sum(t.target_pct for t in targets.values())

    reserva = reserve_status(s, pos, p["reserva_meses_minima"])
    fgc = fgc_exposure(positions) if positions else []
    acima_fgc = [f for f in fgc if f["value"] > p["limite_fgc"]]
    aporte = p["meta_aporte_mensal"] if aporte is None else aporte
    return {
        "classes": linhas, "soma_alvos": soma_alvos, "alvos_definidos": bool(targets),
        "reserva": reserva,
        "aporte": {"valor": aporte, "destinos": aporte_direcionado(linhas, total, aporte, reserva) if aporte else []},
        "calendario_fiscal": calendario_fiscal(positions),
        "fgc": {"limite": p["limite_fgc"], "acima_do_limite": acima_fgc},
        "nota": "Alvos e limites são definidos por você; o app só mede o desvio. Banda padrão: 5 p.p. ou 25% do "
                "alvo, o que for menor (regra 5/25).",
    }


def set_targets(s: Session, targets: list[dict]) -> None:
    keep = set()
    for t in targets:
        cls = t["asset_class"]
        keep.add(cls)
        row = s.scalar(select(AllocationTarget).where(AllocationTarget.asset_class == cls)) or AllocationTarget(asset_class=cls)
        row.target_pct = float(t["target_pct"])
        row.min_pct = t.get("min_pct")
        row.max_pct = t.get("max_pct")
        s.add(row)
    for row in s.scalars(select(AllocationTarget)):
        if row.asset_class not in keep:
            s.delete(row)
    s.flush()


def policy_reviews(s: Session) -> list[ReviewCandidate]:
    out: list[ReviewCandidate] = []
    try:
        rep = policy_report(s)
    except Exception:  # noqa: BLE001 - sem dados de mercado/posições
        return out
    for c in rep["classes"]:
        if c["status"] in ("abaixo", "acima"):
            out.append(ReviewCandidate(
                f"policy:{c['classe']}:{c['status']}", "policy_drift", "warn", "asset_class", c["classe"],
                f"{c['classe']} {c['status']} da banda: {c['atual']:.1%} (alvo {c['alvo']:.0%})",
                f"Para voltar ao alvo: {fmt_brl(c['ajuste_para_alvo'])}. Banda {c['min']:.0%}–{c['max']:.0%}."))
    r = rep["reserva"]
    if not r["ok"] and r["proximo_degrau"]:
        g = r["proximo_degrau"]
        out.append(ReviewCandidate(
            "policy:reserva", "policy_reserve", "warn", "plan", "reserva",
            f"Reserva de emergência: faltam {fmt_brl(g['falta'])} para o degrau \"{g['nome']}\" "
            f"({r['meses']:.1f} de {r['minimo_meses']:g} meses)".replace(".", ","),
            f"Liquidez imediata {fmt_brl(r['liquido_d0_d1'])} para custo essencial de "
            f"{fmt_brl(r['custo_essencial_mensal'])}/mês. O aporte do mês vai primeiro para a reserva."))
    return out  # excesso de FGC já é sinalizado por portfolio_reviews


# ------------------------------------------------------------------ Monte Carlo de metas
def monte_carlo(current: float, target: float, months: int, monthly: float, mu_aa: float, sigma_aa: float,
                n: int = 4000, seed: int = 7) -> dict:
    """Retornos mensais log-normais (média e vol anuais), aporte no fim de cada mês."""
    months = max(1, int(months))
    rng = np.random.default_rng(seed)
    mu_m = np.log1p(mu_aa) / 12
    sig_m = sigma_aa / np.sqrt(12)
    r = np.exp(rng.normal(mu_m - sig_m ** 2 / 2, sig_m, size=(n, months))) - 1
    v = np.empty((n, months))
    cur = np.full(n, float(current))
    for t in range(months):
        cur = cur * (1 + r[:, t]) + monthly
        v[:, t] = cur
    final = v[:, -1]
    pct = np.percentile(v, [10, 50, 90], axis=0)
    step = max(1, months // 60)
    return {
        "probabilidade": float((final >= target).mean()),
        "final_p10": float(np.percentile(final, 10)), "final_p50": float(np.percentile(final, 50)),
        "final_p90": float(np.percentile(final, 90)),
        "trajetoria": [{"mes": t + 1, "p10": float(pct[0, t]), "p50": float(pct[1, t]), "p90": float(pct[2, t])}
                       for t in range(0, months, step)] + ([] if (months - 1) % step == 0 else
                       [{"mes": months, "p10": float(pct[0, -1]), "p50": float(pct[1, -1]), "p90": float(pct[2, -1])}]),
        "premissas": {"retorno_aa": mu_aa, "vol_aa": sigma_aa, "aporte_mensal": monthly, "simulacoes": n},
    }


def portfolio_mu_sigma(s: Session, fallback_mu: float) -> tuple[float, float, str]:
    from app.portfolio.service import risk_report
    try:
        rr = risk_report(s, 2)
        st = rr.get("stats") or {}
        if rr.get("available") and st.get("vol_ann"):
            mu = plan(s)["retorno_esperado_aa"]
            return (float(mu) if mu is not None else min(max(float(st.get("return_ann") or fallback_mu), 0.0), 0.25),
                    float(st["vol_ann"]), "carteira atual (2 anos, ex-ante)")
    except Exception:  # noqa: BLE001
        pass
    return fallback_mu, 0.08, "premissa padrão (vol 8% a.a.)"
