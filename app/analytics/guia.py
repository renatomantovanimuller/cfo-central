"""Guia do CFO: o que você precisa saber hoje e o que vem nos próximos dias, em linguagem simples.

Duas camadas:
- fatos: calculados aqui, de forma determinística, a partir do razão já conferido (saúde dos dados, revisão,
  "quanto posso gastar", cartões, recorrências, orçamento, reserva, previsão de caixa). É sempre a fonte dos números;
- briefing: um texto curto escrito uma vez por dia pelo Claude (Claude Code no plano do usuário, via MCP). Ele só
  pode reescrever e reordenar os itens existentes e citar valores que aparecem nos fatos; `publicar_briefing`
  recusa qualquer valor em R$ que não esteja nos fatos. Sem briefing recente, o guia funciona só com os fatos.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.reviews import fmt_brl
from app.models import AppSetting, FinancialEvent, Institution, Item, RecurringRule, ReviewItem
from app.utils.time import month_add, month_key, today_brt, utcnow

log = logging.getLogger(__name__)

NIVEIS = {"importante": 0, "atencao": 1, "info": 2, "bom": 3}
HORIZONTE_DIAS = 10
BRIEFING_KEY = "briefing"
BRIEFING_VALIDADE_H = 36
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]
# decisões que o usuário resolve em um clique na Revisão (o resto são avisos do sistema)
DECISOES = {"uncategorized", "low_confidence", "pix_pf_out", "pix_in_unknown", "recurring_income",
            "card_not_connected", "card_payment_unmatched", "override_superseded"}
_BRL_RE = re.compile(r"R\$\s*(-?\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|-?\d+(?:,\d{1,2})?)")


@dataclass
class Aviso:
    id: str
    nivel: str
    titulo: str
    texto: str
    acao: dict | None = None
    valores: list[float] = field(default_factory=list)

    @property
    def chave(self) -> str:
        """Muda quando a situação muda: um "entendi" vale só para esta versão do aviso."""
        base = f"{self.id}|{'|'.join(str(round(v)) for v in self.valores)}"
        return hashlib.sha1(base.encode()).hexdigest()[:12]

    def as_dict(self) -> dict:
        return {**asdict(self), "chave": self.chave}


def _acao(label: str, to: str) -> dict:
    return {"label": label, "to": to}


def _mes_nome(ym: str) -> str:
    return MESES[int(ym[5:7]) - 1]


def _dia(d: date) -> str:
    return f"{d:%d/%m}"


def _num(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".").replace(".", ",")


# ------------------------------------------------------------------ fontes
def _saude(s: Session) -> list[Aviso]:
    from app.health.checks import latest
    h = latest(s)
    if not h:
        return []
    falhas = [v for v in h["verificacoes"] if v["status"] == "falha"]
    if not falhas:
        return []
    nomes = "; ".join(v["titulo"].lower() for v in falhas[:2])
    return [Aviso("saude", "importante", "Alguns números podem não bater com o banco",
                 f"A conferência automática encontrou problema em: {nomes}. Até resolver, trate os totais com cautela.",
                 _acao("Ver conferências", "/saude"))]


def _conexoes(s: Session, today: date) -> tuple[list[Aviso], list[dict]]:
    itens, lembretes = [], []
    insts = {i.id: i.name for i in s.scalars(select(Institution))}
    for it in s.scalars(select(Item).where(Item.is_active.is_(True))):
        nome = it.nickname or insts.get(it.institution_id) or "banco"
        if it.status in ("LOGIN_ERROR", "OUTDATED", "WAITING_USER_INPUT"):
            itens.append(Aviso(f"conexao:{it.id}", "importante", f"Reconecte o {nome}",
                              "A leitura desse banco parou. Os dados antigos continuam aqui, mas nada novo entra até "
                              "você renovar a conexão.", _acao("Abrir conexões", "/conexoes")))
        if it.consent_expires_at:
            vence = it.consent_expires_at.date()
            dias = (vence - today).days
            if dias <= 7:
                itens.append(Aviso(f"consentimento:{it.id}", "importante", f"A autorização do {nome} vence em {max(dias, 0)} dias",
                                  "Renove em meu.pluggy.ai para não perder a leitura do banco.",
                                  _acao("Abrir conexões", "/conexoes")))
            elif dias <= 30:
                lembretes.append({"data": vence, "titulo": f"Autorização do {nome} vence", "valor": None, "to": "/conexoes"})
    return itens, lembretes


def _mes(s: Session, today: date) -> tuple[dict | None, list[Aviso]]:
    """Manchete do mês ("quanto posso gastar") e o alerta de ritmo."""
    from app.analytics.plano import safe_to_spend
    sts = safe_to_spend(s, today)
    if sts["renda_prevista"] <= 0 and sts["gasto_ate_hoje"] <= 0:
        return None, []
    itens = []
    disp, mes = sts["disponivel"], _mes_nome(sts["mes"])
    if disp < 0:
        manchete = (f"{mes.capitalize()} já passou do previsto em {fmt_brl(-disp)}. Segure gastos que não são "
                    "essenciais até o próximo salário.")
    else:
        dia = f" ({fmt_brl(sts['por_dia'])} por dia)" if sts["por_dia"] else ""
        aporte = ", já guardando a meta de aporte" if sts["meta_aporte"] > 0 else ""
        manchete = f"Você ainda pode gastar {fmt_brl(disp)} em {mes}{dia}{aporte}."
        teto = sts["renda_prevista"] - sts["meta_aporte"]
        excesso = sts["projecao_gasto_mes"] - teto
        if today.day >= 7 and excesso > max(100.0, 0.05 * teto):
            itens.append(Aviso("mes:ritmo", "atencao", "No ritmo atual, o mês fecha acima do previsto",
                              f"Mantido o ritmo, os gastos de {mes} chegam a {fmt_brl(sts['projecao_gasto_mes'])}, "
                              f"{fmt_brl(excesso)} além do que cabe depois da meta de aporte.",
                              _acao("Ver ritmo de gastos", "/"), [sts["projecao_gasto_mes"], excesso]))
    return {"texto": manchete, "disponivel": disp, "por_dia": sts["por_dia"], "dias_restantes": sts["dias_restantes"],
            "gasto_ate_hoje": sts["gasto_ate_hoje"], "renda_prevista": sts["renda_prevista"],
            "meta_aporte": sts["meta_aporte"]}, itens


def _cartoes(s: Session, today: date, pos: dict) -> tuple[list[Aviso], list[dict]]:
    lembretes, total, ultima = [], 0.0, None
    for c in pos["cards"]:
        due = c.get("due_date")
        if not due or c["current"] <= 0 or not (today <= due <= today + timedelta(days=HORIZONTE_DIAS)):
            continue
        lembretes.append({"data": due, "titulo": f"Fatura do {c['name']} vence", "valor": round(c["current"], 2),
                          "to": "/cartoes"})
        total += c["current"]
        ultima = max(ultima or due, due)
    itens = []
    caixa = pos["totals"]["cash"]
    if total and caixa < total:
        itens.append(Aviso("cartao:saldo", "importante", "O saldo em conta não cobre as faturas que vencem",
                          f"Vencem {fmt_brl(total)} em faturas até {_dia(ultima)} e há {fmt_brl(caixa)} nas contas. "
                          "Planeje um resgate ou transferência antes do vencimento para não pagar juros.",
                          _acao("Ver cartões", "/cartoes"), [round(total, 2), round(caixa, 2)]))
    return itens, lembretes


def _recorrencias(s: Session, today: date) -> list[dict]:
    out = []
    fim = today + timedelta(days=HORIZONTE_DIAS)
    for r in s.scalars(select(RecurringRule).where(RecurringRule.status != "ignored",
                                                   RecurringRule.next_date.between(today, fim))):
        verbo = "deve entrar" if r.direction == "in" else "deve sair"
        out.append({"data": r.next_date, "titulo": f"{r.description} {verbo}", "valor": round(r.expected_amount, 2),
                    "to": "/planejamento", "aproximado": True})
    return out


def _orcamento(s: Session, today: date) -> list[Aviso]:
    from app.analytics.overview import budget_execution
    rows = [r for r in budget_execution(s, month_key(today)) if r["usage"] is not None]
    over = sorted((r for r in rows if r["usage"] > 1), key=lambda r: -(r["actual"] - r["budget"]))
    if over:
        nomes = ", ".join(f"{r['name']} ({fmt_brl(r['actual'])} de {fmt_brl(r['budget'])})" for r in over[:3])
        return [Aviso("orcamento:estouro", "atencao", "Orçamento estourado" if len(over) == 1 else
                     f"{len(over)} orçamentos estourados", f"{nomes}.", _acao("Ver categorias", "/categorias"),
                     [v for r in over[:3] for v in (round(r["actual"], 2), round(r["budget"], 2))])]
    perto = [r for r in rows if r["usage"] >= 0.85]
    if perto and today.day <= 22:
        nomes = ", ".join(f"{r['name']} ({r['usage']:.0%})" for r in perto[:3])
        return [Aviso("orcamento:perto", "info", "Perto do limite do orçamento",
                     f"Já usado: {nomes}, e o mês ainda não acabou.", _acao("Ver categorias", "/categorias"))]
    return []


def _caixa(s: Session) -> list[Aviso]:
    from app.analytics.overview import liquidity_forecast
    f = liquidity_forecast(s)
    neg = [m for m in f["months"] if m["end_cash"] < 0]
    if not neg:
        return []
    m = neg[0]
    return [Aviso("caixa:negativo", "atencao", f"O caixa pode ficar negativo em {_mes_nome(m['month'])}",
                 f"Pela previsão (só renda recorrente e gastos típicos), as contas fecham {_mes_nome(m['month'])} em "
                 f"{fmt_brl(m['end_cash'])}. Não conta com resgates de investimento.",
                 _acao("Ver previsão de caixa", "/planejamento"), [m["end_cash"]])]


def _reserva(s: Session) -> list[Aviso]:
    from app.analytics.plano import policy_report
    r = policy_report(s)["reserva"]
    if r["ok"] or r["meses"] is None:
        return []
    return [Aviso("reserva", "atencao", "Reserva de emergência abaixo do seu mínimo",
                 f"O dinheiro de acesso rápido ({fmt_brl(r['liquido_d0_d1'])}) cobre {_num(r['meses'])} meses do custo "
                 f"essencial; seu mínimo é {_num(r['minimo_meses'])}. Priorize a reserva antes de outros aportes.",
                 _acao("Ver planejamento", "/planejamento"), [r["liquido_d0_d1"]])]


def _revisao(s: Session, today: date) -> list[Aviso]:
    itens = []
    abertos = list(s.scalars(select(ReviewItem).where(ReviewItem.status == "open", ReviewItem.kind != "data_health")))
    graves = [r for r in abertos if r.severity == "high" and r.kind not in DECISOES
              and not r.kind.startswith(("consent", "item_error"))]  # conexões já entram por _conexoes
    for r in graves[:3]:
        itens.append(Aviso(f"revisao:{r.id}", "importante", r.title, r.detail or "", _acao("Resolver", "/revisao")))
    decisoes = [r for r in abertos if r.kind in DECISOES]
    if decisoes:
        n = len(decisoes)
        itens.append(Aviso("revisao:decisoes", "info", f"{n} {'decisão rápida' if n == 1 else 'decisões rápidas'} esperando você",
                          "Classificar salário, transferências e Pix deixa os números do mês mais certos. Cada decisão "
                          "vale para todos os lançamentos da mesma pessoa ou loja.", _acao("Revisar", "/revisao"), [n]))
    desde = datetime.combine(today - timedelta(days=7), datetime.min.time(), tzinfo=timezone.utc)
    atipicos = [r for r in abertos if r.kind == "anomaly" and r.created_at and
                (r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)) >= desde]
    for r in atipicos[:2]:
        itens.append(Aviso(f"atipico:{r.entity_id}", "info", r.title, f"{r.detail}. Se foi planejado, pode dispensar.",
                          _acao("Ver na revisão", "/revisao")))
    return itens


def _provisorio(s: Session, today: date) -> list[Aviso]:
    since = today - timedelta(days=95)
    q = select(func.coalesce(func.sum(FinancialEvent.amount), 0.0)).where(
        FinancialEvent.is_removed.is_(False), FinancialEvent.event_type == "INCOME",
        FinancialEvent.competence_date >= since)
    total = s.scalar(q) or 0.0
    pend = s.scalar(q.where(FinancialEvent.category_id.in_(["rec.pix_terceiros", "nc"]))) or 0.0
    if total > 0 and pend / total >= 0.3:
        return [Aviso("provisorio", "atencao", "Os números do mês ainda são provisórios",
                     f"{pend / total:.0%} do que entrou nos últimos 3 meses ainda está \"a classificar\". "
                     "Enquanto isso, receita e sobra podem estar distorcidas.", _acao("Revisar", "/revisao"))]
    return []


def _fechamento(s: Session, today: date) -> list[Aviso]:
    if today.day > 7:
        return []
    from app.accounting.management import dre_gerencial
    ant = month_add(month_key(today), -1)
    g = dre_gerencial(s, ant)
    row = next((r for r in g["rows"] if r["key"] == "resultado_liquido"), None)
    if row is None:
        return []
    sobra, taxa = row["mes"], g["indicadores"]["taxa_poupanca_mes"]
    media = g["indicadores"]["taxa_poupanca_6m"]
    comp = ""
    if taxa is not None and media is not None:
        comp = f", {'acima' if taxa >= media else 'abaixo'} da média dos 6 meses anteriores ({media:.0%})"
    if sobra >= 0:
        texto = f"Sobraram {fmt_brl(sobra)}" + (f", {taxa:.0%} da renda{comp}." if taxa is not None else ".")
    else:
        texto = f"Faltaram {fmt_brl(-sobra)}: os gastos passaram da renda recorrente."
    return [Aviso(f"fechamento:{ant}", "bom" if sobra >= 0 else "atencao", f"{_mes_nome(ant).capitalize()} fechou",
                 texto, _acao("Ver o mês", "/dre-gerencial"), [abs(sobra)])]


def _imposto(today: date) -> list[Aviso]:
    if today.month not in (3, 4, 5):
        return []
    return [Aviso(f"irpf:{today.year - 1}", "info", f"Prévia do imposto de renda de {today.year - 1} pronta",
                 "Bens, rendimentos e despesas dedutíveis já montados a partir dos seus dados, com a lista do que "
                 "falta completar. O prazo de entrega costuma ir até o fim de maio.",
                 _acao("Abrir prévia do IR", "/imposto-de-renda"))]


# ------------------------------------------------------------------ montagem
def fatos(s: Session, today: date | None = None) -> dict:
    from app.accounting.balance import current_position
    today = today or today_brt()
    itens: list[Aviso] = []
    lembretes: list[dict] = []
    manchete = None

    def run(nome, fn, *a):
        try:
            return fn(*a)
        except Exception:  # noqa: BLE001 — uma fonte quebrada não derruba o guia
            log.exception("guia: fonte %s falhou", nome)
            return None

    pos = run("posicao", current_position, s) or {"cards": [], "totals": {"cash": 0.0}}
    itens += run("saude", _saude, s) or []
    con = run("conexoes", _conexoes, s, today)
    if con:
        itens += con[0]
        lembretes += con[1]
    mes = run("mes", _mes, s, today)
    if mes:
        manchete, extra = mes
        itens += extra
    car = run("cartoes", _cartoes, s, today, pos)
    if car:
        itens += car[0]
        lembretes += car[1]
    lembretes += run("recorrencias", _recorrencias, s, today) or []
    for nome, fn, args in (("orcamento", _orcamento, (s, today)), ("caixa", _caixa, (s,)), ("reserva", _reserva, (s,)),
                           ("revisao", _revisao, (s, today)), ("provisorio", _provisorio, (s, today)),
                           ("fechamento", _fechamento, (s, today)), ("imposto", _imposto, (today,))):
        itens += run(nome, fn, *args) or []
    itens.sort(key=lambda i: NIVEIS[i.nivel])
    lembretes.sort(key=lambda x: x["data"])
    return {"em": today, "manchete": manchete, "itens": [i.as_dict() for i in itens], "proximos": lembretes,
            "tudo_em_dia": not any(i.nivel in ("importante", "atencao") for i in itens)}


# ------------------------------------------------------------------ briefing do Claude
def valores_permitidos(f: dict) -> list[float]:
    vals: list[float] = []
    m = f.get("manchete") or {}
    vals += [m[k] for k in ("disponivel", "por_dia", "gasto_ate_hoje", "renda_prevista", "meta_aporte") if m.get(k) is not None]
    for i in f["itens"]:
        vals += i["valores"]
        vals += [_parse_brl(x) for x in _BRL_RE.findall(f"{i['titulo']} {i['texto']}")]
    vals += [x["valor"] for x in f["proximos"] if x.get("valor") is not None]
    return [abs(v) for v in vals if v is not None]


def _parse_brl(raw: str) -> float:
    return float(raw.replace(".", "").replace(",", "."))


def valores_estranhos(texto: str, permitidos: list[float]) -> list[str]:
    """Valores em R$ do texto que não aparecem nos fatos (tolerância de R$ 1 ou 0,5 %, para arredondamento)."""
    ruins = []
    for raw in _BRL_RE.findall(texto or ""):
        v = abs(_parse_brl(raw))
        if not any(abs(v - p) <= max(1.0, 0.005 * p) for p in permitidos):
            ruins.append(f"R$ {raw}")
    return ruins


def publicar_briefing(s: Session, resumo: str, itens: list[dict] | None = None, autor: str = "claude") -> dict:
    """Grava o texto do dia. `itens`: [{id, texto}] na ordem de prioridade, só com ids que existem nos fatos."""
    resumo = (resumo or "").strip()
    if not resumo:
        return {"ok": False, "erro": "resumo vazio"}
    if len(resumo) > 900:
        return {"ok": False, "erro": "resumo longo demais: no máximo ~4 frases (900 caracteres)"}
    f = fatos(s)
    ids = {i["id"] for i in f["itens"]}
    permitidos = valores_permitidos(f)
    limpos, problemas = [], []
    for it in itens or []:
        iid, txt = str(it.get("id", "")), (it.get("texto") or "").strip()
        if iid not in ids:
            problemas.append(f"item desconhecido: {iid!r} (use só ids de `guia`)")
            continue
        if len(txt) > 400:
            problemas.append(f"texto do item {iid} longo demais (máx. 400 caracteres)")
            continue
        limpos.append({"id": iid, "texto": txt or None})
        problemas += [f"valor {v} no item {iid} não está nos fatos" for v in valores_estranhos(txt, permitidos)]
    problemas += [f"valor {v} no resumo não está nos fatos" for v in valores_estranhos(resumo, permitidos)]
    if problemas:
        return {"ok": False, "erro": "briefing recusado", "problemas": problemas,
                "dica": "Use apenas valores que aparecem em `guia`, no formato R$ 1.234,56, sem somar nem arredondar para 'mil'."}
    row = s.get(AppSetting, BRIEFING_KEY) or AppSetting(key=BRIEFING_KEY)
    row.value = {"resumo": resumo, "itens": limpos, "gerado_em": utcnow().isoformat(), "autor": autor,
                 "fatos_de": f["em"].isoformat()}
    s.add(row)
    s.flush()
    return {"ok": True, "itens": len(limpos)}


def briefing_atual(s: Session) -> dict | None:
    row = s.get(AppSetting, BRIEFING_KEY)
    if not row or not row.value or not row.value.get("gerado_em"):
        return None
    em = datetime.fromisoformat(row.value["gerado_em"])
    if em.tzinfo is None:
        em = em.replace(tzinfo=timezone.utc)
    return {**row.value, "recente": utcnow() - em <= timedelta(hours=BRIEFING_VALIDADE_H)}


def guia(s: Session) -> dict:
    """Fatos + texto do Claude (se recente). Itens citados pelo Claude vêm primeiro, com o texto dele."""
    f = fatos(s)
    b = briefing_atual(s)
    if b and b["recente"]:
        por_id = {i["id"]: i for i in f["itens"]}
        ordem = [x for x in b.get("itens", []) if x["id"] in por_id]
        for x in ordem:
            if x.get("texto"):
                por_id[x["id"]]["texto_claude"] = x["texto"]
        citados = {x["id"] for x in ordem}
        f["itens"] = [por_id[x["id"]] for x in ordem] + [i for i in f["itens"] if i["id"] not in citados]
    f["briefing"] = ({"resumo": b["resumo"], "gerado_em": b["gerado_em"], "autor": b.get("autor")}
                     if b and b["recente"] else None)
    f["briefing_ultimo"] = b["gerado_em"] if b else None
    return f
