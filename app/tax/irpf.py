"""Imposto de renda da pessoa física: prévia da declaração a partir dos dados conectados.

Ano-base N (declaração entregue em N+1). Monta, com a origem de cada número:
- Bens e direitos em 31/12 (contas, renda fixa/Tesouro, ETFs/ações, cripto, empréstimos a receber), com grupo/código;
- Rendimentos sujeitos à tributação exclusiva (código 06 — aplicações financeiras; IR retido na fonte);
- Rendimentos isentos (14 — heranças e doações; 09 — dividendos; 12 — LCI/LCA; 20 — ganhos em ações até R$ 20 mil);
- Renda variável — operações comuns: resultado por mês, compensação de prejuízo e DARF 6015;
- Pagamentos efetuados dedutíveis (saúde e instrução), com CPF/CNPJ do prestador quando o Pix o informa;
- Rendimentos tributáveis recebidos (valores líquidos, só para conferir com o informe da fonte pagadora);
- Pendências: o que os dados não têm e você precisa completar.

É uma prévia de conferência: os informes de rendimentos das instituições (fevereiro) prevalecem.
"""
from __future__ import annotations

import io
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.reviews import fmt_brl
from app.categorization.text import norm
from app.models import (Account, AccountBalance, AccountSetting, Asset, FinancialEvent, Institution, Investment,
                        InvestmentBalance, InvestmentTransaction, Item)
from app.utils.time import today_brt

# CNPJ público das instituições mais comuns (raiz + filial matriz); conferir no informe
INSTITUTION_CNPJ = {
    "nu pagamentos": "18.236.120/0001-58", "nubank": "18.236.120/0001-58",
    "nu financeira": "30.680.829/0001-43",
    "banco inter": "00.416.968/0001-01", "inter": "00.416.968/0001-01",
}
BENS = {  # classe → (grupo, código, descrição do código, valor declarado)
    "conta": ("06", "01", "Depósito em conta corrente ou conta pagamento", "saldo"),
    "poupanca": ("04", "01", "Depósito em conta poupança", "saldo"),
    "RF Pós": ("04", "02", "Títulos públicos e privados sujeitos à tributação (CDB, RDB, Tesouro e outros)", "saldo"),
    "RF Pré": ("04", "02", "Títulos públicos e privados sujeitos à tributação (CDB, RDB, Tesouro e outros)", "saldo"),
    "RF IPCA+": ("04", "02", "Títulos públicos e privados sujeitos à tributação (CDB, RDB, Tesouro e outros)", "saldo"),
    "Tesouro Selic": ("04", "02", "Títulos públicos e privados sujeitos à tributação (CDB, RDB, Tesouro e outros)", "saldo"),
    "Tesouro IPCA+": ("04", "02", "Títulos públicos e privados sujeitos à tributação (CDB, RDB, Tesouro e outros)", "saldo"),
    "Tesouro Prefixado": ("04", "02", "Títulos públicos e privados sujeitos à tributação (CDB, RDB, Tesouro e outros)", "saldo"),
    "isento": ("04", "03", "Títulos isentos de tributação (LCI, LCA, CRI, CRA e outros)", "saldo"),
    "Ações BR": ("03", "01", "Ações (inclusive as listadas em bolsa)", "custo"),
    "ETF Ações BR": ("07", "06", "Fundos de índice (ETF) de renda variável", "custo"),
    "ETF Internacional": ("07", "06", "Fundos de índice (ETF) de renda variável", "custo"),
    "ETF Renda Fixa": ("07", "08", "Fundos de índice (ETF) de renda fixa", "custo"),
    "FIIs": ("07", "03", "Fundos de investimento imobiliário (FII)", "custo"),
    "Fundos": ("07", "01", "Fundos de investimento (consulte o informe para o código exato)", "saldo"),
    "Cripto": ("08", "02", "Criptoativos (escolha o código do ativo: 01 Bitcoin, 02 outras, 03 stablecoins)", "custo"),
    "emprestimo": ("05", "01", "Empréstimos concedidos", "saldo"),
}
ISENTO_SUBTYPES = {"LCI", "LCA", "CRI", "CRA", "DEBENTURE_INCENTIVADA"}
HEALTH_CATS = {"saude.consultas": "Saúde (consultas, terapias e exames)", "saude.dentista": "Dentistas",
               "saude.plano": "Planos de saúde"}
EDU_CATS = {"educacao.faculdade": "Instrução (ensino regular, superior e pós)"}
JCP_KEYS = ("jcp", "jscp", "juros sobre", "juros s/cap", "juros s/ cap")
EDU_LIMIT = 3561.50  # por dependente/titular, ano-calendário (sem reajuste desde 2015)


def _cnpj_for(name: str | None) -> str | None:
    n = norm(name)
    for k, v in INSTITUTION_CNPJ.items():
        if k in n:
            return v
    return None


def _fmt_doc(doc: str | None) -> str | None:
    d = "".join(ch for ch in (doc or "") if ch.isdigit())
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return doc or None


def _bal_at(s: Session, model, key_col, key, ref: date, today: date, current: float | None):
    """Saldo em `ref`: foto do próprio dia (ou do último dia útil antes, até 5 dias) ou o atual se ref ainda não chegou."""
    if ref >= today:
        return current, "prévia (posição de hoje)"
    row = s.scalars(select(model).where(key_col == key, model.date <= ref, model.date >= ref - timedelta(days=5))
                    .order_by(model.date.desc()).limit(1)).first()
    if row is not None:
        return row.balance, f"foto de {row.date:%d/%m/%Y}"
    return None, "sem foto do saldo nessa data"


def _last_business_day(year: int, month: int) -> date:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _regressive_rate(days: int) -> float:
    return 0.225 if days <= 180 else 0.20 if days <= 360 else 0.175 if days <= 720 else 0.15


# ------------------------------------------------------------------ bens e direitos
def bens_e_direitos(s: Session, ano: int, pend: list[str]) -> list[dict]:
    from app.portfolio.realized import equity_lots
    today = today_brt()
    ref, prev = date(ano, 12, 31), date(ano - 1, 12, 31)
    insts = {i.id: i.name for i in s.scalars(select(Institution))}
    nick = {a.account_id: a.nickname for a in s.scalars(select(AccountSetting)) if a.nickname}
    out = []
    # contas
    for a in s.scalars(select(Account).where(Account.type == "BANK", Account.removed_at.is_(None))):
        g, c, desc, _ = BENS["conta"]
        cur, src = _bal_at(s, AccountBalance, AccountBalance.account_id, a.id, ref, today, a.balance)
        before, src_prev = _bal_at(s, AccountBalance, AccountBalance.account_id, a.id, prev, today, None)
        cnpj = _cnpj_for(a.name) or _cnpj_for(a.marketing_name)
        out.append({"grupo": g, "codigo": c, "tipo": desc, "bem": nick.get(a.id) or a.name,
                    "discriminacao": f"Saldo em conta {'pagamento' if 'pagamento' in norm(a.name) else 'corrente'} "
                                     f"nº {a.number or '—'} no(a) {a.name}.",
                    "cnpj": cnpj, "situacao_anterior": before, "situacao_atual": cur, "origem": src,
                    "origem_anterior": src_prev, "obrigatorio": (cur or 0) > 140 or (before or 0) > 140})
    # investimentos (agrupa CDB/RDB do mesmo emissor e indexador num item, como o informe faz)
    assets = {a.id: a for a in s.scalars(select(Asset))}
    rv = {r["investment_id"]: r for r in equity_lots(s)["ativos"]}
    sold_in_year = {t.investment_id for t in s.scalars(select(InvestmentTransaction).where(
        InvestmentTransaction.removed_at.is_(None), InvestmentTransaction.date >= date(ano, 1, 1),
        InvestmentTransaction.date <= ref))}
    groups: dict[tuple, dict] = {}
    item_inst = {}
    for it in s.scalars(select(Item)):
        item_inst[it.id] = insts.get(it.institution_id)
    acc_by_item = {a.item_id: a.name for a in s.scalars(select(Account).where(Account.type == "BANK"))}
    for inv in s.scalars(select(Investment).where(Investment.removed_at.is_(None))):
        a = assets.get(inv.asset_id)
        cls = a.asset_class if a else "Outros"
        if (inv.subtype or "").upper() in ISENTO_SUBTYPES:
            cls = "isento"
        spec = BENS.get(cls)
        if spec is None:
            spec = ("99", "99", "Outros bens e direitos (confira o código)", "saldo")
        active = (inv.balance or 0) > 0.005
        started = inv.purchase_date or inv.issue_date
        if not active and (inv.id not in sold_in_year or not (started and started < date(ano, 1, 1))):
            continue  # só entra zerado o título que existia em 31/12 do ano anterior e foi resgatado no ano
        if started and started > ref:
            continue
        custodian = acc_by_item.get(inv.item_id) or item_inst.get(inv.item_id) or "instituição"
        g, c, desc, basis = spec
        if basis == "custo":
            r = rv.get(inv.id, {})
            qty = inv.quantity or 0
            cost = r.get("custo_conhecido") if r.get("custo_completo") else None
            if active and cost is None:
                pend.append(f"Custo de aquisição de {inv.code or inv.name}: a Pluggy não envia o preço médio e as compras "
                            f"são anteriores ao histórico. Copie o preço médio da Área do Investidor da B3 "
                            f"(investidor.b3.com.br) ou da nota de corretagem.")
            out.append({"grupo": g, "codigo": c, "tipo": desc, "bem": inv.code or inv.name,
                        "discriminacao": f"{qty:g} cotas de {inv.code or inv.name}"
                                         f"{' — ' + inv.issuer if inv.issuer else ''}, custodiadas em {custodian}. "
                                         f"Custo médio de aquisição.",
                        "cnpj": _fmt_doc(inv.issuer_cnpj), "situacao_anterior": None,
                        "situacao_atual": round(cost, 2) if cost is not None else None,
                        "valor_de_mercado": inv.balance, "origem": "custo de aquisição" + ("" if cost is not None else
                                                                                           " — pendente"),
                        "origem_anterior": "copie da declaração anterior", "obrigatorio": True,
                        "pendente": cost is None and active})
            continue
        key = (g, c, inv.issuer_cnpj or inv.code or inv.name, cls, inv.item_id) if (inv.subtype or "").upper() in (
            "CDB", "RDB", "LC") else (g, c, inv.id)
        cur, src = _bal_at(s, InvestmentBalance, InvestmentBalance.investment_id, inv.id, ref, today, inv.balance)
        if not active and ref < today:
            cur, src = 0.0, "resgatado no ano"
        grp = groups.setdefault(key, {
            "grupo": g, "codigo": c, "tipo": desc, "bem": inv.name if (inv.subtype or "").upper() != "CDB"
            else f"CDB/RDB {inv.issuer or ''}".strip(),
            # CDB: CNPJ do emissor (banco que deve); Tesouro e outros: da instituição custodiante
            "cnpj": _fmt_doc(inv.issuer_cnpj) or (_cnpj_for(inv.issuer) if (inv.subtype or "").upper() in (
                "CDB", "RDB", "LC") else _cnpj_for(custodian)),
            "situacao_anterior": None, "situacao_atual": 0.0, "custo": 0.0, "titulos": 0, "origem": src,
            "origem_anterior": "copie da declaração anterior (saldo em 31/12 do informe)", "obrigatorio": True,
            "_parts": []})
        grp["situacao_atual"] = (grp["situacao_atual"] or 0) + (cur or 0)
        grp["custo"] += inv.amount_original or 0
        grp["titulos"] += 1 if active else 0
        if active:
            grp["_parts"].append(f"{inv.name}{' venc. ' + inv.due_date.strftime('%d/%m/%Y') if inv.due_date else ''}"
                                 f", custodiado em {custodian}")
    for grp in groups.values():
        parts = grp.pop("_parts")
        grp["discriminacao"] = (f"{grp['bem']} — {grp['titulos']} aplicação(ões) ativa(s) custodiada(s) na instituição. "
                                f"Valor aplicado (custo): {fmt_brl(grp['custo'])}.") if grp["titulos"] > 1 else \
            (f"{parts[0] if parts else grp['bem']}. Valor aplicado: {fmt_brl(grp['custo'])}." if grp["titulos"] else
             f"{grp['bem']} — resgatado durante {ano}.")
        grp["situacao_atual"] = round(grp["situacao_atual"], 2)
        grp["custo"] = round(grp["custo"], 2)
        out.append(grp)
    # cripto comprada pelo banco (sem custódia conectada): custo = compras − vendas até 31/12
    cripto = 0.0
    for e in s.scalars(select(FinancialEvent).where(FinancialEvent.is_removed.is_(False), FinancialEvent.competence_date <= ref,
                                                     FinancialEvent.event_type.in_(["INVESTMENT_CONTRIBUTION",
                                                                                     "INVESTMENT_REDEMPTION"]))):
        if "cripto" in norm(e.description) or "bitcoin" in norm(e.description):
            cripto += -e.amount
    if cripto > 0.005:
        g, c, desc, _ = BENS["Cripto"]
        out.append({"grupo": g, "codigo": c, "tipo": desc, "bem": "Criptoativos (compras pelo banco)",
                    "discriminacao": "Criptoativos adquiridos pelo app do banco. Informe quantidade e ativo.",
                    "cnpj": None, "situacao_anterior": None, "situacao_atual": round(cripto, 2),
                    "origem": "custo: compras − vendas no extrato", "origem_anterior": "copie da declaração anterior",
                    "obrigatorio": cripto >= 5000})
        pend.append("Cripto: confirme qual ativo e a quantidade (o extrato só mostra o valor). Declarar é obrigatório "
                    "quando o custo de um mesmo tipo de criptoativo chega a R$ 5.000.")
    # empréstimos concedidos ainda não devolvidos
    lent = defaultdict(float)
    for e in s.scalars(select(FinancialEvent).where(FinancialEvent.is_removed.is_(False),
                                                     FinancialEvent.category_id == "pat.emprestimo_concedido",
                                                     FinancialEvent.competence_date <= ref)):
        lent[e.counterparty or "terceiro"] += -e.amount
    for who, v in lent.items():
        if v > 0.005:
            g, c, desc, _ = BENS["emprestimo"]
            out.append({"grupo": g, "codigo": c, "tipo": desc, "bem": f"Empréstimo a {who}",
                        "discriminacao": f"Valor emprestado a {who}, a receber.", "cnpj": None,
                        "situacao_anterior": None, "situacao_atual": round(v, 2), "origem": "Pix enviados − devolvidos",
                        "origem_anterior": "—", "obrigatorio": True})
            pend.append(f"CPF de {who} para o item de empréstimo concedido.")
    out.sort(key=lambda b: (b["grupo"], b["codigo"], -(b["situacao_atual"] or 0)))
    return out


# ------------------------------------------------------------------ tributação exclusiva (aplicações)
def aplicacoes_financeiras(s: Session, ano: int) -> dict:
    start, end = date(ano, 1, 1), date(ano, 12, 31)
    insts = {i.id: i.name for i in s.scalars(select(Institution))}
    item_inst = {it.id: insts.get(it.institution_id) for it in s.scalars(select(Item))}
    acc_by_item = {a.item_id: a.name for a in s.scalars(select(Account).where(Account.type == "BANK"))}
    assets = {a.id: a for a in s.scalars(select(Asset))}
    invs = {i.id: i for i in s.scalars(select(Investment))}
    buys: dict[str, list] = defaultdict(list)
    for t in s.scalars(select(InvestmentTransaction).where(InvestmentTransaction.removed_at.is_(None),
                                                            InvestmentTransaction.type == "BUY")):
        buys[t.investment_id].append(t)
    by_payer: dict[str, dict] = {}
    linhas = []
    for t in s.scalars(select(InvestmentTransaction).where(InvestmentTransaction.removed_at.is_(None),
                                                            InvestmentTransaction.type == "SELL",
                                                            InvestmentTransaction.date >= start,
                                                            InvestmentTransaction.date <= end)):
        inv = invs.get(t.investment_id)
        if inv is None:
            continue
        a = assets.get(inv.asset_id)
        cls = a.asset_class if a else ""
        if (inv.type or "").upper() not in ("FIXED_INCOME",) and cls != "ETF Renda Fixa":
            continue
        if (inv.subtype or "").upper() in ISENTO_SUBTYPES:
            continue
        gross = abs(t.amount or 0)
        net = abs(t.net_amount) if t.net_amount is not None else None
        ir = round(gross - net, 2) if net is not None else None
        # custo das unidades vendidas: preço unitário médio das compras do título (quando no histórico)
        b = [x for x in buys.get(inv.id, []) if x.quantity and x.amount]
        method = None
        cost = None
        if b and t.quantity:
            unit = sum(abs(x.amount) for x in b) / sum(abs(x.quantity) for x in b)
            cost = abs(t.quantity) * unit
            method = "custo das unidades (compras no histórico)"
        elif ir and ir > 0 and (inv.purchase_date or inv.issue_date):
            days = (t.date - (inv.purchase_date or inv.issue_date)).days
            rend_bruto = ir / _regressive_rate(days)
            cost = gross - rend_bruto
            method = f"estimado pela alíquota regressiva ({_regressive_rate(days):.1%}, {days} dias)"
        rend_bruto = gross - cost if cost is not None else None
        rend_liq = (rend_bruto - (ir or 0)) if rend_bruto is not None else None
        payer = inv.issuer if (inv.subtype or "").upper() in ("CDB", "RDB", "LC") else \
            (acc_by_item.get(inv.item_id) or item_inst.get(inv.item_id) or "instituição")
        cnpj = _fmt_doc(inv.issuer_cnpj) if (inv.subtype or "").upper() in ("CDB", "RDB", "LC") else _cnpj_for(payer)
        p = by_payer.setdefault(payer, {"fonte_pagadora": payer, "cnpj": cnpj, "rendimento_bruto": 0.0,
                                        "ir_retido": 0.0, "rendimento_liquido": 0.0, "resgates": 0, "estimado": False})
        p["resgates"] += 1
        p["rendimento_bruto"] += rend_bruto or 0
        p["ir_retido"] += ir or 0
        p["rendimento_liquido"] += rend_liq or 0
        p["estimado"] |= bool(method and method.startswith("estimado"))
        linhas.append({"data": t.date, "titulo": inv.code or inv.name, "valor_bruto": gross, "valor_liquido": net,
                       "ir_retido": ir, "rendimento_bruto": round(rend_bruto, 2) if rend_bruto is not None else None,
                       "metodo": method})
    fontes = []
    for p in by_payer.values():
        for k in ("rendimento_bruto", "ir_retido", "rendimento_liquido"):
            p[k] = round(p[k], 2)
        fontes.append(p)
    return {"codigo": "06", "descricao": "Rendimentos de aplicações financeiras (valor líquido do IR)",
            "fontes": sorted(fontes, key=lambda x: -x["rendimento_liquido"]),
            "total_liquido": round(sum(p["rendimento_liquido"] for p in fontes), 2),
            "total_ir_retido": round(sum(p["ir_retido"] for p in fontes), 2),
            "resgates": sorted(linhas, key=lambda x: x["data"])}


# ------------------------------------------------------------------ renda variável
def _compensate(result: float, loss: float) -> tuple[float, float]:
    """Resultado do mês e prejuízo acumulado → (base tributável, prejuízo que sobra)."""
    if result <= 0:
        return 0.0, loss - result
    used = min(result, loss)
    return result - used, loss - used


def renda_variavel(s: Session, ano: int, pend: list[str]) -> dict:
    from app.portfolio.realized import equity_lots
    months = {m: {"mes": f"{ano}-{m:02d}", "vendas_acoes": 0.0, "resultado_acoes": 0.0, "resultado_etf": 0.0,
                  "resultado_fii": 0.0, "nao_apuravel": 0.0} for m in range(1, 13)}
    for a in equity_lots(s)["ativos"]:
        cls = a.get("classe") or ""
        if cls == "ETF Renda Fixa":
            continue  # tributação exclusiva, retida na fonte
        for v in a.get("vendas", []):
            d = v["data"]
            if d.year != ano:
                continue
            m = months[d.month]
            if v["resultado"] is None:
                m["nao_apuravel"] += v["valor_venda"]
                pend.append(f"Venda de {a['ativo']} em {d:%d/%m/%Y}: custo das cotas vendidas desconhecido — informe o "
                            "preço médio para apurar o ganho.")
                continue
            if cls == "Ações BR":
                m["vendas_acoes"] += v["valor_venda"]
                m["resultado_acoes"] += v["resultado"]
            elif cls == "FIIs":
                m["resultado_fii"] += v["resultado"]
            else:
                m["resultado_etf"] += v["resultado"]
    loss_common = loss_fii = 0.0
    darf_pending = 0.0
    rows, isento_acoes = [], 0.0
    for mi in range(1, 13):
        m = months[mi]
        acoes_isento = m["vendas_acoes"] <= 20000 and m["resultado_acoes"] > 0
        if acoes_isento:
            isento_acoes += m["resultado_acoes"]
        base_common = (0 if acoes_isento else m["resultado_acoes"]) + m["resultado_etf"]
        base_common, loss_common = _compensate(base_common, loss_common)
        base_fii, loss_fii = _compensate(m["resultado_fii"], loss_fii)
        imposto = round(base_common * 0.15 + base_fii * 0.20, 2) + darf_pending
        due = _last_business_day(ano + (mi == 12), mi % 12 + 1)
        pay = imposto >= 10
        rows.append({**{k: round(v, 2) if isinstance(v, float) else v for k, v in m.items()},
                     "acoes_isento_20k": acoes_isento, "base_tributavel": round(base_common + base_fii, 2),
                     "prejuizo_a_compensar": round(loss_common + loss_fii, 2), "imposto": round(imposto, 2),
                     "darf": {"codigo": "6015", "vencimento": due, "valor": round(imposto, 2)} if pay else None})
        darf_pending = 0.0 if pay else imposto
    return {"meses": rows, "isento_acoes_ate_20k": round(isento_acoes, 2),
            "total_darf": round(sum(r["darf"]["valor"] for r in rows if r["darf"]), 2),
            "nota": "ETFs de renda variável não têm a isenção de R$ 20 mil (15% sobre o ganho); ações têm isenção "
                    "quando as vendas do mês somam até R$ 20 mil; FII 20%. DARF abaixo de R$ 10 acumula para o mês "
                    "seguinte. Vencimento no último dia útil do mês seguinte (feriados não considerados)."}


# ------------------------------------------------------------------ eventos do razão
def _events(s: Session, ano: int, cats: set[str] | None = None, types: set[str] | None = None) -> list[FinancialEvent]:
    q = select(FinancialEvent).where(FinancialEvent.is_removed.is_(False), FinancialEvent.competence_date >= date(ano, 1, 1),
                                     FinancialEvent.competence_date <= date(ano, 12, 31))
    if cats:
        q = q.where(FinancialEvent.category_id.in_(cats))
    if types:
        q = q.where(FinancialEvent.event_type.in_(types))
    return list(s.scalars(q.order_by(FinancialEvent.competence_date)))


def _doc_of(s: Session, e: FinancialEvent) -> str | None:
    from app.models import Transaction
    t = s.get(Transaction, e.source_id) if e.source_type == "transaction" else None
    if t is None:
        return None
    return t.counterparty_doc or t.merchant_cnpj or (t.receiver_doc if e.amount < 0 else t.payer_doc)


def isentos(s: Session, ano: int, pend: list[str], rv: dict) -> list[dict]:
    out = []
    her = _events(s, ano, {"rec.heranca"})
    if her:
        for e in her:
            doc = _fmt_doc(_doc_of(s, e))
            out.append({"codigo": "14", "tipo": "Transferências patrimoniais — doações e heranças",
                        "beneficiario": "titular", "fonte": e.counterparty or e.description, "cpf_cnpj": doc,
                        "valor": round(e.amount, 2), "data": e.competence_date})
            if not doc or len("".join(ch for ch in doc if ch.isdigit())) != 11:
                pend.append(f"Herança/doação de {fmt_brl(e.amount)} em {e.competence_date:%d/%m/%Y}: informe o CPF do "
                            "doador (ou do espólio) e confira se é doação ou herança (inventário).")
    div = [e for e in _events(s, ano, {"finrec.dividendos"}) if not any(k in norm(e.description) for k in JCP_KEYS)]
    if div:
        tot = defaultdict(float)
        for e in div:
            tot[e.counterparty or e.description] += e.amount
        for k, v in tot.items():
            out.append({"codigo": "09", "tipo": "Lucros e dividendos recebidos", "beneficiario": "titular", "fonte": k,
                        "cpf_cnpj": None, "valor": round(v, 2)})
    if rv["isento_acoes_ate_20k"] > 0:
        out.append({"codigo": "20", "tipo": "Ganhos líquidos em operações no mercado à vista de ações (vendas até "
                                            "R$ 20 mil/mês)", "beneficiario": "titular", "fonte": "B3",
                    "cpf_cnpj": None, "valor": rv["isento_acoes_ate_20k"]})
    return out


def exclusivos_extra(s: Session, ano: int) -> list[dict]:
    jcp = [e for e in _events(s, ano, {"finrec.dividendos"}) if any(k in norm(e.description) for k in JCP_KEYS)]
    return [{"codigo": "10", "tipo": "Juros sobre capital próprio", "fonte": e.counterparty or e.description,
             "valor": round(e.amount, 2), "data": e.competence_date} for e in jcp]


def pagamentos(s: Session, ano: int, pend: list[str]) -> list[dict]:
    out = []
    for cats, kind in ((HEALTH_CATS, "saude"), (EDU_CATS, "instrucao")):
        evs = _events(s, ano, set(cats))
        paid: dict[tuple, dict] = {}
        refunds = defaultdict(float)
        mirror = {}
        for e in evs:
            if e.amount < 0 and e.event_type == "EXPENSE":
                doc = _doc_of(s, e)
                key = (e.category_id, "".join(ch for ch in (doc or "") if ch.isdigit()) or norm(e.counterparty or e.description))
                p = paid.setdefault(key, {"categoria": cats[e.category_id], "tipo": kind,
                                          "prestador": e.counterparty or e.description, "cpf_cnpj": _fmt_doc(doc),
                                          "pago": 0.0, "reembolsado": 0.0, "pagamentos": 0, "_ids": set()})
                p["pago"] += -e.amount
                p["pagamentos"] += 1
                p["_ids"].add(e.source_id)
            elif e.amount > 0 and e.event_type == "REFUND":
                if (e.rule_id or "").startswith("mirror:"):
                    mirror[e.rule_id.split(":", 1)[1]] = e.amount
                else:
                    refunds[e.category_id] += e.amount
        for p in paid.values():
            for sid in list(p["_ids"]):
                if sid in mirror:
                    p["reembolsado"] += mirror.pop(sid)
        # reembolso sem vínculo direto (ex.: empresa devolve parte das consultas): rateado pelo pago na categoria
        for cat, amount in refunds.items():
            group = [p for (c, _), p in paid.items() if c == cat]
            tot = sum(p["pago"] for p in group) or 0
            for p in group:
                p["reembolsado"] += amount * (p["pago"] / tot) if tot else 0
                p["reembolso_rateado"] = len(group) > 1
        for p in paid.values():
            p.pop("_ids")
            p["pago"], p["reembolsado"] = round(p["pago"], 2), round(min(p["reembolsado"], p["pago"]), 2)
            p["dedutivel"] = round(p["pago"] - p["reembolsado"], 2)
            if not p["cpf_cnpj"]:
                pend.append(f"CPF/CNPJ de {p['prestador']} ({p['categoria']}): o lançamento não traz o documento — "
                            "pegue no recibo/nota fiscal.")
            out.append(p)
    if any(p["tipo"] == "instrucao" for p in out):
        pend.append("Instrução: só deduzem mensalidades de ensino regular, técnico, superior e pós. Taxas, restaurante "
                    "universitário, cursos livres e material não deduzem — confira os pagamentos listados.")
    edu = sum(p["dedutivel"] for p in out if p["tipo"] == "instrucao")
    if edu > EDU_LIMIT:
        pend.append(f"Instrução: dedução limitada a {fmt_brl(EDU_LIMIT)} por pessoa (você tem {fmt_brl(edu)}).")
    return sorted(out, key=lambda p: -p["dedutivel"])


def tributaveis(s: Session, ano: int) -> list[dict]:
    out: dict[str, dict] = {}
    for e in _events(s, ano, {"rec.salario", "rec.bonus", "rec.freela"}):
        if e.amount <= 0:
            continue
        doc = _doc_of(s, e)
        k = "".join(ch for ch in (doc or "") if ch.isdigit()) or norm(e.counterparty or e.description)
        r = out.setdefault(k, {"fonte_pagadora": e.counterparty or e.description, "cpf_cnpj": _fmt_doc(doc),
                               "salario_liquido": 0.0, "bonus_liquido": 0.0, "outros": 0.0, "creditos": 0})
        if e.category_id == "rec.salario":
            r["salario_liquido"] += e.amount
        elif e.category_id == "rec.bonus":
            r["bonus_liquido"] += e.amount
        else:
            r["outros"] += e.amount
        r["creditos"] += 1
    from app.accounting.ledger import owner_identity
    own = owner_identity(s)[0]
    for k, r in out.items():
        if k in own:
            r["fonte_pagadora"] += " (sua própria conta — a fonte pagadora real está no informe)"
    for r in out.values():
        for k in ("salario_liquido", "bonus_liquido", "outros"):
            r[k] = round(r[k], 2)
    return list(out.values())


def irpf_report(s: Session, ano: int | None = None) -> dict:
    today = today_brt()
    ano = ano or (today.year if today.month >= 3 else today.year - 1)
    pend: list[str] = []
    bens = bens_e_direitos(s, ano, pend)
    aplic = aplicacoes_financeiras(s, ano)
    rv = renda_variavel(s, ano, pend)
    isen = isentos(s, ano, pend, rv)
    excl_extra = exclusivos_extra(s, ano)
    pag = pagamentos(s, ano, pend)
    trib = tributaveis(s, ano)
    if any(b.get("situacao_anterior") is None for b in bens):
        pend.append(f"Situação em 31/12/{ano - 1}: a Pluggy não fornece saldo histórico. Copie os valores da sua "
                    f"declaração do ano passado (ou dos informes de {ano - 1}).")
    if aplic["fontes"] and any(f["estimado"] for f in aplic["fontes"]):
        pend.append("Parte do rendimento de aplicações foi estimada pela alíquota regressiva (títulos comprados antes do "
                    "histórico). Confira com o informe de rendimentos da instituição.")
    if trib:
        pend.append("Rendimentos tributáveis: o extrato mostra o salário/bônus líquido. Na declaração use o informe "
                    "da fonte pagadora (bruto, INSS, IRRF, 13º).")
    pend.append("Dívidas e ônus: só declarar dívidas acima de R$ 5.000 em 31/12 (fatura de cartão em aberto normalmente não entra).")
    total_bens = sum(b["situacao_atual"] or 0 for b in bens)
    return {
        "ano_base": ano, "exercicio": ano + 1, "parcial": today <= date(ano, 12, 31),
        "gerado_em": today, "bens_e_direitos": bens, "total_bens": round(total_bens, 2),
        "tributacao_exclusiva": {"aplicacoes": aplic, "outros": excl_extra},
        "isentos": isen, "renda_variavel": rv, "pagamentos": pag,
        "deducoes": {"saude": round(sum(p["dedutivel"] for p in pag if p["tipo"] == "saude"), 2),
                     "instrucao": round(min(EDU_LIMIT, sum(p["dedutivel"] for p in pag if p["tipo"] == "instrucao")), 2)},
        "tributaveis_conferencia": trib,
        "pendencias": list(dict.fromkeys(pend)),
        "aviso": "Prévia para conferência montada a partir do Open Finance. Os informes de rendimentos das "
                 "instituições e da fonte pagadora prevalecem; confira antes de transmitir.",
    }


def irpf_xlsx(s: Session, ano: int | None = None) -> bytes:
    from openpyxl import Workbook
    from app.analytics.export import _sheet
    r = irpf_report(s, ano)
    wb = Workbook()
    wb.remove(wb.active)
    _sheet(wb, "Bens e direitos", ["Grupo", "Código", "Tipo", "Bem", "Discriminação", "CNPJ",
                                   f"Situação 31/12/{r['ano_base'] - 1}", f"Situação 31/12/{r['ano_base']}",
                                   "Origem do valor", "Obrigatório"],
           [[b["grupo"], b["codigo"], b["tipo"], b["bem"], b["discriminacao"], b.get("cnpj"), b.get("situacao_anterior"),
             b.get("situacao_atual"), b.get("origem"), "sim" if b.get("obrigatorio") else "não"]
            for b in r["bens_e_direitos"]], money={7, 8})
    ap = r["tributacao_exclusiva"]["aplicacoes"]
    _sheet(wb, "Tributação exclusiva", ["Código", "Fonte pagadora", "CNPJ", "Rendimento bruto", "IR retido",
                                        "Rendimento líquido (declarar)", "Resgates", "Estimado"],
           [["06", f["fonte_pagadora"], f["cnpj"], f["rendimento_bruto"], f["ir_retido"], f["rendimento_liquido"],
             f["resgates"], "sim" if f["estimado"] else "não"] for f in ap["fontes"]]
           + [[o["codigo"], o["fonte"], None, o["valor"], None, o["valor"], None, None]
              for o in r["tributacao_exclusiva"]["outros"]], money={4, 5, 6})
    _sheet(wb, "Resgates", ["Data", "Título", "Valor bruto", "Valor líquido", "IR retido", "Rendimento bruto", "Método"],
           [[x["data"], x["titulo"], x["valor_bruto"], x["valor_liquido"], x["ir_retido"], x["rendimento_bruto"],
             x["metodo"]] for x in ap["resgates"]], money={3, 4, 5, 6})
    _sheet(wb, "Isentos", ["Código", "Tipo", "Fonte/doador", "CPF/CNPJ", "Valor"],
           [[i["codigo"], i["tipo"], i["fonte"], i.get("cpf_cnpj"), i["valor"]] for i in r["isentos"]], money={5})
    _sheet(wb, "Renda variável", ["Mês", "Vendas de ações", "Resultado ações", "Resultado ETF", "Resultado FII",
                                  "Não apurável (sem custo)", "Base tributável", "Prejuízo a compensar", "Imposto",
                                  "DARF 6015 vencimento", "DARF valor"],
           [[m["mes"], m["vendas_acoes"], m["resultado_acoes"], m["resultado_etf"], m["resultado_fii"], m["nao_apuravel"],
             m["base_tributavel"], m["prejuizo_a_compensar"], m["imposto"],
             m["darf"]["vencimento"] if m["darf"] else None, m["darf"]["valor"] if m["darf"] else None]
            for m in r["renda_variavel"]["meses"]], money={2, 3, 4, 5, 6, 7, 8, 9, 11})
    _sheet(wb, "Pagamentos efetuados", ["Tipo", "Categoria", "Prestador", "CPF/CNPJ", "Pago", "Reembolsado",
                                        "Dedutível"],
           [[p["tipo"], p["categoria"], p["prestador"], p["cpf_cnpj"], p["pago"], p["reembolsado"], p["dedutivel"]]
            for p in r["pagamentos"]], money={5, 6, 7})
    _sheet(wb, "Tributáveis (conferir)", ["Fonte pagadora", "CPF/CNPJ", "Salário líquido", "Bônus líquido", "Outros",
                                          "Créditos"],
           [[t["fonte_pagadora"], t["cpf_cnpj"], t["salario_liquido"], t["bonus_liquido"], t["outros"], t["creditos"]]
            for t in r["tributaveis_conferencia"]], money={3, 4, 5})
    _sheet(wb, "Pendências", ["O que completar"], [[p] for p in r["pendencias"]] + [[r["aviso"]]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
