"""Visão consolidada do patrimônio: cada conta, investimento, cartão, empréstimo e item manual numa lista única com
instituição, classe, faixa de liquidez, bolsos e conferência do saldo. A tela agrupa por qualquer dimensão
(instituição, classe, liquidez, bolso) sem que o total mude, e abre até a posição.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.reviews import fmt_brl
from app.utils.time import today_brt

LIQ_ORDER = ["Em 1 dia", "Até 30 dias", "Até 30 dias, com oscilação", "No vencimento", "Longo prazo", "Ilíquido",
             "Dívida"]
MARKED_TO_MARKET = {"Tesouro IPCA+", "Tesouro Prefixado"}
PROJ_MAX_RETURN = 0.12  # teto do retorno nominal da projeção quando o plano não tem premissa


def liquidity_band(item: dict, daily_ids: set) -> str:
    """Faixa de liquidez legível a partir do prazo de resgate e da marcação a mercado."""
    if item["tipo"] == "conta" or item["id"] in daily_ids:
        return "Em 1 dia"
    cls, liq = item.get("classe"), item.get("liquidez")
    if cls in ("Previdência", "COE"):
        return "Longo prazo"
    if cls in MARKED_TO_MARKET:
        return "Até 30 dias, com oscilação"
    if liq in ("D0", "D1") or cls == "Tesouro Selic":
        return "Em 1 dia"
    if liq and liq.startswith("D"):
        return "Até 30 dias, com oscilação" if cls in ("Ações BR", "ETF Ações BR", "ETF Internacional", "FIIs",
                                                       "Cripto", "ETF Renda Fixa") else "Até 30 dias"
    if liq == "vencimento":
        return "No vencimento"
    return "Ilíquido"


def _balance_checks(s: Session) -> dict[str, dict]:
    """Conferência por conta a partir da última verificação de Saúde dos dados: saldo reconstruído pelos
    lançamentos nunca negativo e variação entre sincronizações fechando com os lançamentos."""
    from app.health.checks import _acc_names, latest
    rep = latest(s) or {}
    chk = next((c for c in rep.get("verificacoes") or [] if c.get("id") == "saldo_conta"), None)
    if not chk:
        return {}
    by_name: dict[str, dict] = {}
    for d in chk.get("detalhes") or []:
        st = by_name.setdefault(d.get("conta"), {"status": "ok", "nota": "saldo confere com os lançamentos"})
        if d.get("problema"):
            st.update(status="atencao", nota=d["problema"])
        elif d.get("menor_saldo_reconstruido") is not None and \
                d["menor_saldo_reconstruido"] < -(d.get("limite_cheque_especial") or 0) - 1:
            st.update(status="falha", nota="reconstruído pelos lançamentos, o saldo fica negativo: falta entrada")
    names = _acc_names(s)
    return {aid: by_name[n] for aid, n in names.items() if n in by_name}


def consolidated(s: Session) -> dict:
    from app.accounting.balance import current_position
    from app.accounting.institutions import institution_labels
    from app.analytics.bolsos import _allocations, sources
    from app.models import Bucket, InvestmentTransaction, Loan
    from app.portfolio.classification import has_daily_liquidity
    pos = current_position(s)
    labels = institution_labels(s)
    src = sources(pos)
    per_bucket, _ = _allocations(s, {(x["type"], x["id"]) for x in src})
    bucket_names = {b.id: b.name for b in s.scalars(select(Bucket))}
    shares: dict[tuple, list] = defaultdict(list)
    for bid, items in per_bucket.items():
        for k, pct, _ in items:
            shares[k].append((bucket_names.get(bid, "?"), pct))
    redeemed = set(s.scalars(select(InvestmentTransaction.investment_id).where(InvestmentTransaction.type == "SELL")))
    daily = {p["id"] for p in pos["positions"] if p.get("liquidity") == "vencimento"
             and has_daily_liquidity({**p, "early_redemption": p["id"] in redeemed})}
    checks = _balance_checks(s)
    kind = {"account": "conta", "investment": "investimento", "manual": "bem manual"}
    items = []
    for x in src:
        it = {"tipo": kind[x["type"]], "id": x["id"], "nome": x["label"],
              "instituicao": x["institution"] or ("Bens e dívidas manuais" if x["type"] == "manual" else "—"),
              "classe": x["classe"], "liquidez": x["liquidez"], "valor": round(x["value"], 2),
              "vencimento": x.get("vencimento")}
        it["faixa"] = "Ilíquido" if x["type"] == "manual" else liquidity_band(it, daily)
        sh = shares.get((x["type"], x["id"]), [])
        free = max(0.0, 1 - sum(p for _, p in sh))
        it["bolsos"] = [{"nome": n, "valor": round(x["value"] * p, 2)} for n, p in sh] + \
            ([{"nome": "Livre", "valor": round(x["value"] * free, 2)}] if free > 1e-6 else [])
        if x["type"] == "account":
            it["conferencia"] = checks.get(x["id"])
        items.append(it)
    # mesma regra do Balanço: com o limite usado de todos os cartões, dívida = limite usado; senão fatura atual +
    # parcelas futuras estimadas (linha à parte)
    all_used = bool(pos["cards"]) and all(c["used_total"] is not None for c in pos["cards"])
    for c in pos["cards"]:
        debt = (c["used_total"] if all_used else c["current"]) or 0.0
        items.append({"tipo": "cartão", "id": c["account_id"], "nome": c["name"],
                      "instituicao": c["institution"] or "—",
                      "classe": "Cartão de crédito", "faixa": "Dívida", "valor": -round(debt, 2),
                      "detalhe": f"fatura atual {fmt_brl(c['current'])}",
                      "bolsos": [{"nome": "Dívidas", "valor": -round(debt, 2)}]})
    loan_inst = {l.id: labels.get(l.item_id) for l in s.scalars(select(Loan))}
    for ln in pos["loans"]:
        items.append({"tipo": "empréstimo", "id": ln["id"], "nome": ln["name"],
                      "instituicao": loan_inst.get(ln["id"]) or "—",
                      "classe": "Empréstimo", "faixa": "Dívida", "valor": -round(ln["outstanding"], 2),
                      "bolsos": [{"nome": "Dívidas", "valor": -round(ln["outstanding"], 2)}]})
    for m in pos["manual_liabilities"]:
        items.append({"tipo": "dívida manual", "id": str(m["id"]), "nome": m["name"],
                      "instituicao": "Bens e dívidas manuais", "classe": m.get("class") or "Dívida manual",
                      "faixa": "Dívida", "valor": -round(m["value"], 2),
                      "bolsos": [{"nome": "Dívidas", "valor": -round(m["value"], 2)}]})
    if (pos["totals"].get("in_transit") or 0) > 0:
        items.append({"tipo": "em trânsito", "id": "transito", "nome": "Valores em trânsito", "instituicao": "—",
                      "classe": "Em trânsito", "faixa": "No vencimento", "valor": round(pos["totals"]["in_transit"], 2),
                      "bolsos": [{"nome": "Livre", "valor": round(pos["totals"]["in_transit"], 2)}]})
    if pos["cards"] and not all_used and pos["totals"]["card_future"]:
        items.append({"tipo": "cartão", "id": "parcelas", "nome": "Parcelas futuras (estimadas)", "instituicao": "—",
                      "classe": "Cartão de crédito", "faixa": "Dívida",
                      "valor": -round(pos["totals"]["card_future"], 2),
                      "bolsos": [{"nome": "Dívidas", "valor": -round(pos["totals"]["card_future"], 2)}]})
    total = round(sum(i["valor"] for i in items), 2)
    return {"itens": items, "total": total, "patrimonio_liquido": round(pos["totals"]["net_worth"], 2),
            "disponivel_1_dia": round(pos["totals"]["liquid_net_worth"], 2), "faixas": LIQ_ORDER,
            "agrupamentos": [["instituicao", "Instituição"], ["classe", "Classe"], ["faixa", "Liquidez"],
                             ["bolso", "Bolso"], ["tipo", "Tipo"]],
            "nota": "Cada item aparece uma vez; o total é o patrimônio líquido. Por bolso, um item dividido aparece "
                    "em cada bolso com a sua parte."}


# ------------------------------------------------------------------ ponte do patrimônio
def bridge(s: Session, months: int = 12) -> dict:
    """De onde veio a variação do patrimônio em cada mês: poupança (resultado recorrente) + extraordinários e
    entradas a classificar + valorização dos investimentos + variação dos itens manuais; o que sobra é "não
    explicado" (conta não conectada, lançamento faltando, diferença de critério entre competência e saldo)."""
    from app.accounting.balance import history
    from app.accounting.manual import manual_net_at
    from app.accounting.statements import dre, portfolio_valuation
    from app.utils.time import month_bounds, month_key
    hist = history(s, months)
    if len(hist) < 2:
        return {"meses": [], "nota": "Precisa de pelo menos dois meses de histórico."}
    ml = [h["date"][:7] for h in hist[1:]]
    d = dre(s, ml, with_valuation=False)
    rows = {r["key"]: r["values"] for r in d["rows"]}
    val = portfolio_valuation(s, ml)
    out = []
    for prev, cur in zip(hist, hist[1:]):
        m = cur["date"][:7]
        a, b = month_bounds(m)
        poup = rows["resultado_liquido"].get(m, 0.0)
        extra = rows["extraordinarios"].get(m, 0.0) + rows["entradas_a_classificar"].get(m, 0.0)
        v = val["values"].get(m)
        manual = manual_net_at(s, min(b, date.fromisoformat(cur["date"]))) - manual_net_at(s, a - timedelta(days=1))
        delta = cur["net_worth"] - prev["net_worth"]
        known = poup + extra + (v or 0.0) + manual
        out.append({"mes": m, "inicio": round(prev["net_worth"], 2), "fim": round(cur["net_worth"], 2),
                    "poupanca": round(poup, 2), "extraordinarios": round(extra, 2),
                    "valorizacao": None if v is None else round(v, 2), "manuais": round(manual, 2),
                    "nao_explicado": round(delta - known, 2),
                    "estimado": bool(cur.get("inferred") or prev.get("inferred") or val["inferred"].get(m)),
                    "parcial": m == month_key(today_brt())})
    return {"meses": out,
            "nota": "Variação do patrimônio = poupança do mês (resultado recorrente) + extraordinários e entradas a "
                    "classificar + valorização dos investimentos + variação dos itens manuais + não explicado. "
                    "\"Não explicado\" alto aponta conta não conectada ou lançamento faltando."}


# ------------------------------------------------------------------ evolução por classe e instituição
def evolution(s: Session, months: int = 12) -> dict:
    """Investimentos no fim de cada mês por classe e por instituição, a partir das fotos diárias de cada
    investimento (só existem desde que o app começou a sincronizar: meses anteriores ficam vazios, não inventados)."""
    from app.accounting.institutions import institution_labels
    from app.models import Asset, Investment, InvestmentBalance
    from app.utils.time import month_add, month_bounds, month_key
    today = today_brt()
    ml = [month_add(month_key(today), -k) for k in range(months - 1, -1, -1)]
    invs = {i.id: i for i in s.scalars(select(Investment))}
    assets = {a.id: a for a in s.scalars(select(Asset))}
    labels = institution_labels(s)
    snaps: dict[str, list] = defaultdict(list)
    for b in s.scalars(select(InvestmentBalance).order_by(InvestmentBalance.date)):
        snaps[b.investment_id].append((b.date, b.balance or 0.0))
    by_class: dict[str, list] = defaultdict(lambda: [None] * len(ml))
    by_inst: dict[str, list] = defaultdict(lambda: [None] * len(ml))
    covered = [False] * len(ml)
    for i, m in enumerate(ml):
        end = min(month_bounds(m)[1], today)
        for inv_id, pts in snaps.items():
            last = next((v for d, v in reversed(pts) if d <= end and (end - d).days <= 10), None)
            if last is None:
                continue
            covered[i] = True
            inv = invs.get(inv_id)
            a = assets.get(inv.asset_id) if inv else None
            cls = a.asset_class if a else "Outros"
            inst = labels.get(inv.item_id, "—") if inv else "—"
            by_class[cls][i] = (by_class[cls][i] or 0.0) + last
            by_inst[inst][i] = (by_inst[inst][i] or 0.0) + last
    for series in (by_class, by_inst):
        for k, vals in series.items():
            series[k] = [None if not covered[i] else round(v or 0.0, 2) for i, v in enumerate(vals)]
    return {"meses": ml, "por_classe": dict(by_class), "por_instituicao": dict(by_inst),
            "meses_com_dado": sum(covered),
            "nota": "Fim de cada mês, pelas fotos diárias dos investimentos. Meses antes da primeira sincronização "
                    "ficam vazios."}


# ------------------------------------------------------------------ projeção
def projection(s: Session, years: int = 10, alvo: float | None = None, inflacao: float = 0.04) -> dict:
    """Patrimônio financeiro (caixa + investimentos) projetado com o aporte do plano e o risco/retorno da carteira
    atual: faixas p10–p90 de 4.000 cenários, em valores nominais e em reais de hoje (inflação editável)."""
    from app.accounting.balance import current_position
    from app.analytics.plano import monte_carlo, plan, portfolio_mu_sigma, safe_to_spend
    pos = current_position(s)
    t = pos["totals"]
    start = (t["cash"] or 0.0) + (t["investments"] or 0.0) + (t.get("in_transit") or 0.0)
    p = plan(s)
    aporte = p["meta_aporte_mensal"] if p["meta_aporte_mensal"] is not None else safe_to_spend(s)["meta_aporte"]
    mu, sigma, fonte = portfolio_mu_sigma(s, 0.10)
    if p.get("retorno_esperado_aa") is None and mu > PROJ_MAX_RETURN:
        # o ex-ante de 2 anos da carteira atual é otimista para 10 anos: sem premissa no plano, limita
        mu, fonte = PROJ_MAX_RETURN, f"{fonte}; limitado a {PROJ_MAX_RETURN:.0%} a.a. (defina a premissa no plano)"
    months = years * 12
    mc = monte_carlo(start, alvo or 0.0, months, aporte or 0.0, mu, sigma)
    real = lambda v, mes: v / (1 + inflacao) ** (mes / 12)  # noqa: E731
    traj = [{**x, "p10_real": real(x["p10"], x["mes"]), "p50_real": real(x["p50"], x["mes"]),
             "p90_real": real(x["p90"], x["mes"])} for x in mc["trajetoria"]]
    marcos = []
    for y in (1, 5, 10):
        if y <= years:
            pt = min(traj, key=lambda x: abs(x["mes"] - y * 12))
            marcos.append({"anos": y, "p10": pt["p10"], "p50": pt["p50"], "p90": pt["p90"], "p50_real": pt["p50_real"]})
    quando = None
    if alvo:
        hit = next((x for x in traj if x["p50"] >= alvo), None)
        quando = hit["mes"] if hit else None
    return {"inicio": round(start, 2), "aporte_mensal": aporte, "retorno_aa": mu, "vol_aa": sigma, "fonte_risco": fonte,
            "inflacao": inflacao, "trajetoria": traj, "marcos": marcos, "alvo": alvo, "meses_ate_alvo_p50": quando,
            "probabilidade_alvo": mc["probabilidade"] if alvo else None,
            "nota": "Projeção, não promessa: retornos sorteados com o risco da carteira atual; aporte do plano "
                    "todo mês."}
