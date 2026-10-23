"""Tela "Hoje": o que saber e o que fazer ao começar o dia, como o inventário e as missões de um jogo.

- Missões do dia (com XP): decisões pendentes, lançamentos novos para conferir, o resumo de ontem, e missões de
  fundo quando fazem sentido (sincronizar, montar a reserva, separar bolsos, atualizar itens manuais, aporte do mês).
- Inventário: patrimônio, disponível hoje, reserva em degraus, bolsos, saúde financeira e aporte do mês.
- Novidades desde a última vez que você concluiu o dia, como foi ontem e os próximos 7 dias.
- "Concluir o dia" soma o XP das missões cumpridas e mantém a sequência de dias. Conquistas acendem com marcos reais.

O estado da rotina (visitas, XP, missões vistas) fica em app_settings["rotina"].
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.reviews import fmt_brl
from app.utils.time import month_bounds, month_key, today_brt, utcnow

KEY = "rotina"
XP_PER_LEVEL = 100
EXPENSE_LIKE = ("EXPENSE", "FINANCIAL_EXPENSE", "TAX", "REFUND")


def _state(s: Session) -> dict:
    from app.analytics.plano import get_setting
    return get_setting(s, KEY, {"ultima_conclusao": None, "checkins": [], "xp_total": 0, "vistos": {}, "xp_dias": {}})


def _save(s: Session, st: dict) -> None:
    from app.analytics.plano import put_setting
    st["checkins"] = st.get("checkins", [])[-400:]
    st["vistos"] = {k: v for k, v in sorted(st.get("vistos", {}).items())[-14:]}
    st["xp_dias"] = {k: v for k, v in sorted(st.get("xp_dias", {}).items())[-60:]}
    put_setting(s, KEY, st)


def streak(checkins: list[str], today) -> int:
    """Dias seguidos com o dia concluído, terminando hoje ou ontem (o dia de hoje ainda pode ser concluído)."""
    days = {datetime.fromisoformat(d).date() for d in checkins}
    d = today if today in days else today - timedelta(days=1)
    n = 0
    while d in days:
        n += 1
        d -= timedelta(days=1)
    return n


def _since(st: dict):
    last = st.get("ultima_conclusao")
    return datetime.fromisoformat(last) if last else utcnow() - timedelta(days=1)


def news(s: Session, since: datetime) -> dict:
    from app.models import Category, FinancialEvent, Transaction
    cats = {c.id: c.name for c in s.scalars(select(Category))}
    rows = s.execute(select(FinancialEvent, Transaction.first_seen_at)
                     .join(Transaction, Transaction.id == FinancialEvent.source_id)
                     .where(Transaction.first_seen_at > since, FinancialEvent.is_removed.is_(False),
                            FinancialEvent.event_type.not_in(["IGNORE", "INTERNAL_TRANSFER"]))
                     .order_by(func.abs(FinancialEvent.amount).desc())).all()
    evs = [e for e, _ in rows]
    entradas = sum(e.amount for e in evs if e.amount > 0 and e.event_type in ("INCOME", "INVESTMENT_INCOME"))
    saidas = -sum(e.amount for e in evs if e.amount < 0 and e.event_type in EXPENSE_LIKE)
    return {"desde": since, "quantidade": len(evs), "entradas": round(entradas, 2), "gastos": round(saidas, 2),
            "salario": any(e.category_id == "rec.salario" and e.amount > 0 for e in evs),
            "revisar": sum(1 for e in evs if e.needs_review),
            "destaques": [{"id": e.source_id, "data": e.competence_date, "descricao": e.counterparty or e.description,
                           "valor": e.amount, "categoria": cats.get(e.category_id), "revisar": e.needs_review}
                          for e in evs[:6]]}


def yesterday(s: Session, today) -> dict:
    from app.models import FinancialEvent
    y = today - timedelta(days=1)
    by_day = dict(s.execute(select(FinancialEvent.competence_date, func.sum(FinancialEvent.amount)).where(
        FinancialEvent.is_removed.is_(False), FinancialEvent.event_type.in_(EXPENSE_LIKE),
        FinancialEvent.competence_date.between(today - timedelta(days=31), y))
        .group_by(FinancialEvent.competence_date)).all())
    spent = -(by_day.get(y) or 0.0)
    days = [-(by_day.get(today - timedelta(days=k)) or 0.0) for k in range(2, 32)]
    typical = statistics.median(days) if days else 0.0
    top = s.execute(select(FinancialEvent.counterparty, FinancialEvent.description, FinancialEvent.amount).where(
        FinancialEvent.is_removed.is_(False), FinancialEvent.event_type.in_(EXPENSE_LIKE),
        FinancialEvent.competence_date == y).order_by(FinancialEvent.amount).limit(3)).all()
    return {"data": y, "gasto": round(spent, 2), "dia_tipico": round(typical, 2),
            "comparacao": None if not typical else round(spent / typical - 1, 3),
            "maiores": [{"descricao": c or d, "valor": a} for c, d, a in top]}


def upcoming(s: Session, today, days: int = 7) -> list[dict]:
    from app.models import Account, RecurringRule
    end = today + timedelta(days=days)
    out = []
    for r in s.scalars(select(RecurringRule).where(RecurringRule.status != "ignored",
                                                   RecurringRule.next_date.between(today, end))):
        anual = (r.frequency_days or 30) >= 300
        sign = 1 if r.direction == "in" else -1
        out.append({"data": r.next_date, "descricao": r.description, "valor": r.expected_amount * sign,
                    "tipo": "anual" if anual else ("entrada" if r.direction == "in" else "conta fixa")})
    for a in s.scalars(select(Account).where(Account.type == "CREDIT", Account.removed_at.is_(None),
                                             Account.bill_due_date.between(today, end))):
        out.append({"data": a.bill_due_date, "descricao": f"Fatura {a.name}", "valor": -abs(a.balance or 0.0),
                    "tipo": "fatura"})
    return sorted(out, key=lambda x: x["data"])


DECISION_KINDS = {"low_confidence", "uncategorized", "recurring_income", "duplicate", "exit_no_counterpart"}


def pending_decisions(s: Session) -> int:
    """Mesma regra da Revisão para "decisão" (classificação), não avisos do sistema."""
    from app.models import ReviewItem
    kinds = s.scalars(select(ReviewItem.kind).where(ReviewItem.status == "open"))
    return sum(1 for k in kinds if k.startswith("pix_") or k in DECISION_KINDS)


def _missions(s: Session, st: dict, today, ctx: dict) -> list[dict]:
    from app.models import ManualAsset
    vistos = set(st.get("vistos", {}).get(today.isoformat(), []))
    m = []
    n = ctx["decisoes"]
    m.append({"id": "decisoes", "titulo": "Zerar as decisões pendentes" if n else "Nenhuma decisão pendente",
              "detalhe": f"{n} {'decisão' if n == 1 else 'decisões'} — as de maior impacto primeiro" if n else
              "a fila de revisão está em dia", "xp": min(50, 5 * max(n, 1)) if n else 5, "feito": n == 0,
              "link": "/revisao", "tipo": "diaria"})
    nv = ctx["novidades"]["quantidade"]
    m.append({"id": "novidades", "titulo": "Conferir os lançamentos novos",
              "detalhe": f"{nv} desde a última vez" if nv else "nada novo desde a última vez", "xp": 10,
              "feito": nv == 0 or "novidades" in vistos, "acao": "ver" if nv else None, "link": "/razao",
              "tipo": "diaria"})
    m.append({"id": "ontem", "titulo": "Ver como foi ontem", "detalhe": "gasto de ontem contra um dia típico",
              "xp": 5, "feito": "ontem" in vistos, "acao": "ver", "tipo": "diaria"})
    sync = ctx.get("ultima_sincronizacao")
    if sync is None or (utcnow() - sync) > timedelta(hours=26):
        m.append({"id": "sincronizar", "titulo": "Sincronizar os bancos", "detalhe": "dados com mais de um dia",
                  "xp": 10, "feito": False, "link": "/conexoes", "tipo": "extra"})
    res = ctx["reserva"]
    if res.get("abaixo_do_colchao"):
        m.append({"id": "reserva", "titulo": "Montar o colchão da reserva",
                  "detalhe": f"faltam {fmt_brl(res['proximo_degrau']['falta'])} para 1 mês de essenciais",
                  "xp": 20, "feito": False, "link": "/patrimonio", "tipo": "extra"})
    if ctx["bolsos_vazios"]:
        m.append({"id": "bolsos", "titulo": "Separar o dinheiro em bolsos",
                  "detalhe": "reserva e objetivos sem dinheiro",
                  "xp": 30, "feito": False, "link": "/patrimonio", "tipo": "extra"})
    stale = [x for x in s.scalars(select(ManualAsset).where(ManualAsset.active.is_(True)))
             if x.as_of and (today - x.as_of).days > 90]
    if stale:
        m.append({"id": "manuais", "titulo": "Atualizar o valor dos itens manuais",
                  "detalhe": ", ".join(x.name for x in stale[:3]) + " (mais de 3 meses)", "xp": 20, "feito": False,
                  "link": "/config", "tipo": "extra"})
    ap = ctx["aporte"]
    if ap["meta"]:
        m.append({"id": "aporte", "titulo": "Aporte do mês",
                  "detalhe": f"{fmt_brl(ap['realizado'])} de {fmt_brl(ap['meta'])}",
                  "xp": 50, "feito": ap["realizado"] >= ap["meta"] * 0.98, "link": "/planejamento",
                  "tipo": "mensal", "progresso": min(1.0, ap["realizado"] / ap["meta"]) if ap["meta"] else None})
    return m


def _badges(ctx: dict, st: dict, today) -> list[dict]:
    res, saude, ap = ctx["reserva"], ctx["saude"], ctx["aporte_hist"]
    deg = {g["nome"]: g for g in res.get("degraus", [])}
    sq = streak(st.get("checkins", []), today)
    b = [
        ("colchao", "Colchão", "1 mês de custo essencial guardado",
         bool(deg.get("Colchão inicial", {}).get("atingido"))),
        ("tres_meses", "Três meses", "3 meses de reserva", bool(deg.get("Três meses", {}).get("atingido"))),
        ("reserva", "Reserva completa", "meta de reserva do plano atingida", bool(res.get("ok") and res.get("meses"))),
        ("revisao_zero", "Caixa de entrada zero", "nenhuma decisão pendente", ctx["decisoes"] == 0),
        ("aporte_3", "Aportador", "3 meses seguidos com a meta de aporte", (ap or {}).get("sequencia", 0) >= 3),
        ("sequencia_7", "Uma semana", "7 dias seguidos concluídos", sq >= 7),
        ("sequencia_30", "Um mês", "30 dias seguidos concluídos", sq >= 30),
        ("bolso", "Organizado", "dinheiro separado em pelo menos um objetivo", ctx["bolsos_com_dinheiro"] > 0),
        ("saude_80", "Saudável", "saúde financeira 80 ou mais",
         (saude or {}).get("nota") is not None and saude["nota"] >= 80),
    ]
    return [{"id": i, "nome": n, "descricao": d, "conquistada": ok} for i, n, d, ok in b]


def today_view(s: Session) -> dict:
    from app.accounting.balance import current_position
    from app.analytics.bolsos import buckets_report
    from app.analytics.metas import contributions_history
    from app.analytics.plano import plan, reserve_status, safe_to_spend
    from app.analytics.saude_financeira import financial_health
    from app.models import Item
    today = today_brt()
    st = _state(s)
    pos = current_position(s)
    p = plan(s)
    sts = safe_to_spend(s)
    res = reserve_status(s, pos, p["reserva_meses_minima"])
    bk = buckets_report(s, pos)
    goal_buckets = [b for b in bk["bolsos"] if b["tipo"] != "reserva"]
    hist = contributions_history(s, p["meta_aporte_mensal"] or sts["meta_aporte"], 6)
    try:
        saude = financial_health(s)
    except Exception:  # noqa: BLE001 - o índice nunca derruba a tela do dia
        saude = None
    last_sync = s.scalar(select(func.max(Item.last_synced_at)))
    if last_sync is not None and last_sync.tzinfo is None:
        last_sync = last_sync.replace(tzinfo=timezone.utc)
    ctx = {"novidades": news(s, _since(st)), "reserva": res, "aporte": hist["mes_atual"],
           "aporte_hist": hist, "saude": saude, "decisoes": pending_decisions(s),
           "bolsos_vazios": all(b["valor"] == 0 for b in bk["bolsos"]),
           "bolsos_com_dinheiro": sum(1 for b in goal_buckets if b["valor"] > 0), "ultima_sincronizacao": last_sync}
    missions = _missions(s, st, today, ctx)
    done_today = today.isoformat() in st.get("checkins", [])
    xp_total = int(st.get("xp_total", 0))
    a, b = month_bounds(month_key(today))
    return {
        "data": today, "saudacao": _greeting(), "concluido_hoje": done_today,
        "sequencia": streak(st.get("checkins", []), today), "xp_total": xp_total,
        "nivel": xp_total // XP_PER_LEVEL + 1, "xp_no_nivel": xp_total % XP_PER_LEVEL, "xp_por_nivel": XP_PER_LEVEL,
        "xp_disponivel": sum(m["xp"] for m in missions if m["feito"]) if not done_today else 0,
        "missoes": missions, "novidades": ctx["novidades"], "ontem": yesterday(s, today),
        "proximos_7_dias": upcoming(s, today),
        "inventario": {
            "patrimonio_liquido": round(pos["totals"]["net_worth"], 2),
            "disponivel_1_dia": round(pos["totals"]["liquid_net_worth"], 2),
            "pode_gastar_hoje": sts.get("por_dia"), "pode_gastar_mes": sts.get("disponivel"),
            "dias_restantes": sts.get("dias_restantes"),
            "reserva": {"meses": res["meses"], "degraus": res["degraus"], "proximo": res["proximo_degrau"]},
            "bolsos": [{"nome": x["nome"], "valor": x["valor"], "alvo": x["alvo"], "progresso": x["progresso"]}
                       for x in bk["bolsos"]]
            + [{"nome": "Livre", "valor": bk["livre"], "alvo": None, "progresso": None}],
            "saude": {"nota": saude["nota"], "faixa": saude["faixa"]} if saude else None,
            "aporte_mes": ctx["aporte"], "mes": {"inicio": a, "fim": b},
        },
        "conquistas": _badges(ctx, st, today),
    }


def _greeting() -> str:
    h = (utcnow() - timedelta(hours=3)).hour
    return "Bom dia" if 5 <= h < 12 else "Boa tarde" if 12 <= h < 18 else "Boa noite"


def acknowledge(s: Session, mission: str) -> None:
    st = _state(s)
    key = today_brt().isoformat()
    seen = set(st.setdefault("vistos", {}).get(key, []))
    seen.add(mission)
    st["vistos"][key] = sorted(seen)
    _save(s, st)


def check_in(s: Session) -> dict:
    """Conclui o dia: soma o XP das missões cumpridas (uma vez por dia), registra a sequência e marca o ponto a
    partir do qual as próximas "novidades" são contadas."""
    view = today_view(s)
    st = _state(s)
    key = today_brt().isoformat()
    gained = 0
    if key not in st.get("checkins", []):
        gained = view["xp_disponivel"]
        st["xp_total"] = int(st.get("xp_total", 0)) + gained
        st.setdefault("checkins", []).append(key)
        st.setdefault("xp_dias", {})[key] = gained
    st["ultima_conclusao"] = utcnow().isoformat()
    _save(s, st)
    total = st["xp_total"]
    return {"xp_ganho": gained, "xp_total": total, "nivel": total // XP_PER_LEVEL + 1,
            "sequencia": streak(st["checkins"], today_brt())}
