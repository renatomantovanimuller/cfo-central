"""Índice de saúde financeira (0–100), calculado dos dados.

Inspirado no FinHealth Score (Financial Health Network): 4 pilares e 8 indicadores — Gastar (gasto × renda,
contas em dia), Poupar (reserva líquida, poupança de longo prazo), Dever (dívida administrável, score de
crédito) e Planejar e proteger (seguros, planejamento). O original é um questionário; aqui cada indicador vem do
razão, da carteira e do plano. Indicador sem dado fica fora da média (e aparece como "sem dado"), nunca vira zero.

Faixas como no FinHealth: 80+ saudável, 40–79 equilibrando, abaixo de 40 vulnerável.
"""
from __future__ import annotations

import statistics
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.reviews import fmt_brl
from app.utils.time import month_add, month_bounds, month_key, today_brt

PILLARS = [("gastar", "Gastar"), ("poupar", "Poupar"), ("dever", "Dever"), ("planejar", "Planejar e proteger")]
HIST_KEY = "saude_financeira_hist"


def _interp(x: float, points: list[tuple[float, float]]) -> float:
    """Nota por interpolação linear entre pontos (x, nota), com saturação nas pontas."""
    pts = sorted(points)
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def tier(score: float | None) -> str | None:
    if score is None:
        return None
    return "saudavel" if score >= 80 else "equilibrando" if score >= 40 else "vulneravel"


def _ind(key, pillar, name, score, value, why, tip) -> dict:
    return {"chave": key, "pilar": pillar, "nome": name, "nota": None if score is None else round(score),
            "valor": value, "explicacao": why, "como_melhorar": tip}


def financial_health(s: Session) -> dict:
    from app.accounting.balance import current_position
    from app.accounting.statements import dre, month_list
    from app.analytics.overview import kpis_from_dre
    from app.analytics.plano import plan, reserve_status
    from app.models import AllocationTarget, Budget, FinancialEvent, FinancialGoal, Loan

    today = today_brt()
    months = month_list(month_add(month_key(today), -1), 6)  # 6 meses fechados
    k = kpis_from_dre(dre(s, months, with_valuation=False))
    active = [m for m in months if k[m]["receita_liquida"] or k[m]["despesas"]]
    p = plan(s)
    pos = current_position(s)
    inds: list[dict] = []

    # --- Gastar 1: gasto relativo à renda
    rec = sum(k[m]["receita_liquida"] for m in active)
    desp = sum(k[m]["despesas"] for m in active)
    if active and rec > 0:
        ratio = desp / rec
        inds.append(_ind("gasto_renda", "gastar", "Gasto menor que a renda",
                         _interp(ratio, [(0.8, 100), (0.95, 70), (1.0, 50), (1.1, 0)]),
                         f"{ratio:.0%} da renda gasta ({len(active)} meses)",
                         "Despesas ÷ receita líquida dos meses fechados. Até 80% é folga; "
                         "acima de 100% consome patrimônio.",
                         "Veja no Resultado gerencial as categorias acima da média e defina orçamentos nelas."))
    else:
        inds.append(_ind("gasto_renda", "gastar", "Gasto menor que a renda", None, "sem dado",
                         "Precisa de pelo menos um mês fechado com receita.", "Sincronize e classifique a renda."))

    # --- Gastar 2: contas em dia (proxy: juros, multas, rotativo, cheque especial)
    start = month_bounds(months[0])[0]
    late = s.execute(select(FinancialEvent.competence_date, func.sum(FinancialEvent.amount))
                     .where(FinancialEvent.is_removed.is_(False), FinancialEvent.competence_date >= start,
                            FinancialEvent.competence_date <= month_bounds(months[-1])[1],
                            FinancialEvent.category_id.in_(["findesp.juros", "findesp.multas"]))
                     .group_by(FinancialEvent.competence_date)).all()
    late_months = {month_key(d) for d, v in late if (v or 0) < -5}
    n = len(late_months)
    if not active:
        inds.append(_ind("contas_em_dia", "gastar", "Contas em dia", None, "sem dado",
                         "Precisa de pelo menos um mês fechado com movimento.", "Sincronize suas contas."))
    else:
        inds.append(_ind("contas_em_dia", "gastar", "Contas em dia", _interp(n, [(0, 100), (1, 70), (2, 40), (3, 10)]),
                         "nenhum mês com juros ou multa" if n == 0 else f"{n} de {len(active)} meses com juros/multa",
                         "Juros, multas, rotativo do cartão e cheque especial indicam conta paga atrasada ou parcial.",
                         "Pague a fatura cheia e use débito automático (ou Pix Automático) nas contas fixas."))

    # --- Poupar 1: reserva líquida em meses de essenciais
    res = reserve_status(s, pos, p["reserva_meses_minima"])
    if res["meses"] is not None:
        inds.append(_ind("reserva", "poupar", "Reserva de emergência",
                         _interp(res["meses"], [(0, 0), (1, 40), (3, 75), (6, 100)]),
                         f"{res['meses']:.1f} meses de custo essencial".replace(".", ","),
                         "Caixa e aplicações de liquidez diária sem marcação a mercado ÷ custo essencial mensal. "
                         "O primeiro mês de reserva é o que mais reduz estresse financeiro.",
                         f"Próximo degrau: {res['proximo_degrau']['nome']} "
                         f"(faltam {fmt_brl(res['proximo_degrau']['falta'])})." if res["proximo_degrau"]
                         else "Reserva completa: direcione o aporte à carteira."))
    else:
        inds.append(_ind("reserva", "poupar", "Reserva de emergência", None, "sem dado",
                         "Precisa do custo essencial de pelo menos um mês.", "Classifique moradia, mercado e contas."))

    # --- Poupar 2: poupança de longo prazo (taxa de poupança recorrente)
    rates = [k[m]["taxa_poupanca"] for m in active if k[m]["taxa_poupanca"] is not None]
    if rates:
        sr = statistics.median(rates)
        inds.append(_ind("poupanca", "poupar", "Poupança de longo prazo",
                         _interp(sr, [(0, 0), (0.05, 40), (0.10, 65), (0.20, 90), (0.30, 100)]),
                         f"taxa de poupança mediana {sr:.0%}",
                         "Quanto sobra da receita líquida todo mês (resultado recorrente, sem extraordinários).",
                         "Ative no Plano a regra que destina parte de cada aumento ao aporte."))
    else:
        inds.append(_ind("poupanca", "poupar", "Poupança de longo prazo", None, "sem dado",
                         "Precisa de receita classificada em pelo menos um mês fechado.",
                         "Confirme na Revisão quais entradas são salário."))

    # --- Dever 1: dívida administrável (parcelas do próximo mês ÷ renda mensal)
    renda = rec / len(active) if active and rec > 0 else None
    inst_next = pos["installments"]["by_month"][0]["amount"] if pos["installments"]["by_month"] else 0.0
    loans_next = sum(x or 0 for x in s.scalars(select(Loan.next_installment_amount).where(Loan.removed_at.is_(None))))
    if renda:
        dr = (inst_next + loans_next) / renda
        inds.append(_ind("divida", "dever", "Dívida administrável",
                         _interp(dr, [(0.10, 100), (0.20, 75), (0.35, 40), (0.5, 0)]),
                         f"{dr:.0%} da renda em parcelas no próximo mês",
                         "Parcelas do cartão e de empréstimos ÷ renda mensal. Acima de 30% aperta qualquer "
                         "imprevisto.",
                         "Evite novos parcelamentos até baixar; compare o CET dos empréstimos e considere a "
                         "portabilidade."))
    else:
        inds.append(_ind("divida", "dever", "Dívida administrável", None, "sem dado",
                         "Precisa da renda mensal (receita classificada).",
                         "Confirme na Revisão quais entradas são salário."))

    # --- Dever 2: score de crédito (fora do Open Finance; informado no plano)
    score = p.get("score_credito")
    inds.append(_ind("score_credito", "dever", "Score de crédito",
                     _interp(float(score), [(300, 10), (500, 50), (700, 90), (850, 100)]) if score else None,
                     f"{score:.0f} pontos" if score else "sem dado",
                     "Informado por você (Serasa, Boa Vista ou Registrato): o Open Finance não traz o score.",
                     "Informe o score em Planejamento → Plano para completar o pilar."))

    # --- Planejar e proteger 1: seguros (plano de saúde e outros seguros pagos no último ano)
    year_ago = today - timedelta(days=365)
    paid = set(s.scalars(select(FinancialEvent.category_id).where(
        FinancialEvent.is_removed.is_(False), FinancialEvent.competence_date >= year_ago, FinancialEvent.amount < 0,
        FinancialEvent.category_id.in_(["saude.plano", "servicos.seguros"])).distinct()))  # IPVA não é seguro
    prot = (60 if "saude.plano" in paid else 0) + (40 if "servicos.seguros" in paid else 0)
    names = {"saude.plano": "plano de saúde", "servicos.seguros": "seguros"}
    inds.append(_ind("protecao", "planejar", "Proteção (saúde e seguros)", prot,
                     ", ".join(sorted(names[c] for c in paid)) or "nenhum seguro identificado",
                     "Plano de saúde e seguros pagos nos últimos 12 meses (pelo extrato; cobertura paga pela "
                     "empresa não aparece).",
                     "Se tem dependentes ou bens relevantes, avalie seguro de vida e residencial."))

    # --- Planejar e proteger 2: planejamento (o que já está definido)
    checks = {"meta de aporte": p.get("meta_aporte_mensal") is not None,
              "alocação-alvo": bool(s.scalar(select(func.count()).select_from(AllocationTarget))),
              "metas": bool(s.scalar(select(func.count()).select_from(FinancialGoal))),
              "orçamentos": bool(s.scalar(select(func.count()).select_from(Budget)))}
    done = [k_ for k_, v in checks.items() if v]
    inds.append(_ind("planejamento", "planejar", "Planejamento", 25 * len(done),
                     f"{len(done)} de 4 definidos" + (f" ({', '.join(done)})" if done else ""),
                     "Meta de aporte, alocação-alvo, metas e orçamentos: quem decide antes gasta menos por impulso.",
                     ("Falta: " + ", ".join(k_ for k_, v in checks.items() if not v)) if len(done) < 4
                     else "Tudo definido."))

    scored = [i for i in inds if i["nota"] is not None]
    pillars = []
    for key, label in PILLARS:
        vals = [i["nota"] for i in scored if i["pilar"] == key]
        pillars.append({"chave": key, "nome": label, "nota": round(statistics.mean(vals)) if vals else None})
    total = round(statistics.mean(i["nota"] for i in scored)) if scored else None
    hist = _history(s)
    return {"nota": total, "faixa": tier(total), "pilares": pillars, "indicadores": inds,
            "medidos": len(scored), "de": len(inds), "historico": hist,
            "nota_metodo": "Média dos indicadores com dado (0–100). Inspirado no FinHealth Score; faixas: 80+ "
                           "saudável, 40–79 equilibrando, abaixo de 40 vulnerável."}


def _history(s: Session) -> list[dict]:
    from app.analytics.plano import get_setting
    h = get_setting(s, HIST_KEY, {})
    return [{"mes": m, "nota": v} for m, v in sorted(h.items()) if not m.startswith("_")][-12:]


def snapshot_health(s: Session) -> int | None:
    """Grava a nota do mês corrente (a cada reconstrução) para a tendência."""
    from app.analytics.plano import put_setting
    rep = financial_health(s)
    if rep["nota"] is not None:
        put_setting(s, HIST_KEY, {month_key(today_brt()): rep["nota"]})
    return rep["nota"]
