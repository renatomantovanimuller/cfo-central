"""Retorno realizado por título e custo de renda variável.

Renda fixa/Tesouro: fluxos reais da Pluggy (aplicações e resgates com IR/IOF) + saldo atual → resultado,
IR retido, TIR e % do CDI (comparado a aplicar os mesmos fluxos no CDI). Só é 'completo' quando a aplicação
inicial está dentro do histórico entregue pela Pluggy (≈12 meses); fora disso o título é marcado como parcial.

Renda variável: a Pluggy não envia preço médio. Daqui em diante, cada mudança de quantidade entre snapshots
diários vira um lote: valor exato quando há negociação informada pela Pluggy ou débito/crédito bancário de
renda variável compatível no período; senão quantidade × fechamento do dia (estimado). A quantidade existente
no primeiro snapshot fica sem custo conhecido — nunca é inventado.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (Asset, AssetPrice, FinancialEvent, Investment, InvestmentBalance, InvestmentTransaction)
from app.portfolio import metrics as M
from app.portfolio.market import accumulated, cdi_daily
from app.utils.time import today_brt

RV_TYPES = {"ETF", "EQUITY", "STOCK", "BDR", "REAL_ESTATE_FUND"}
RV_TEXT = ("renda variavel", "renda variável", "acoes", "ações", "etf", "bolsa", "fii", "bdr")


def _is_rv(inv: Investment) -> bool:
    return (inv.type or "").upper() in RV_TYPES or (inv.subtype or "").upper() in RV_TYPES


# ------------------------------------------------------------------ renda fixa / Tesouro
def fixed_income_titles(s: Session) -> dict:
    today = today_brt()
    assets = {a.id: a for a in s.scalars(select(Asset))}
    txs: dict[str, list[InvestmentTransaction]] = defaultdict(list)
    for t in s.scalars(select(InvestmentTransaction).where(InvestmentTransaction.removed_at.is_(None))):
        if t.date:
            txs[t.investment_id].append(t)
    first = min((t.date for v in txs.values() for t in v), default=today)
    cdi = cdi_daily(s, first - timedelta(days=10))
    out = []
    for inv in s.scalars(select(Investment).where(Investment.removed_at.is_(None))):
        if _is_rv(inv):
            continue
        tl = sorted(txs.get(inv.id, []), key=lambda t: t.date)
        bal = inv.balance or 0.0
        if not tl and bal <= 0.005:
            continue
        buys = [t for t in tl if (t.type or "").upper() == "BUY"]
        sells = [t for t in tl if (t.type or "").upper() == "SELL"]
        start = inv.purchase_date or inv.issue_date
        aplic = sum(abs(t.amount or t.net_amount or 0) for t in buys)
        sells_before = [t for t in sells if buys and t.date < buys[0].date]
        # completo: a 1ª aplicação está no histórico. Se a data de compra informada for anterior (alguns bancos
        # mandam a data de emissão), aceita quando não há resgate antes e o saldo é compatível com o aplicado
        complete = bool(buys) and (start is None or buys[0].date <= start + timedelta(days=5) or (
            not sells_before and not sells and aplic > 0 and 0.9 <= bal / aplic <= 1.3))
        if complete and start and buys[0].date > start + timedelta(days=5):
            start = buys[0].date
        aplicado = sum(abs(t.amount or t.net_amount or 0) for t in buys)
        resg_bruto = sum(abs(t.amount or 0) for t in sells)
        resg_liq = sum(abs(t.net_amount if t.net_amount is not None else (t.amount or 0)) for t in sells)
        ir = max(0.0, resg_bruto - resg_liq)
        a = assets.get(inv.asset_id)
        row = {"id": inv.id, "nome": inv.name, "classe": a.asset_class if a else None, "status":
               "encerrado" if bal <= 0.005 else "ativo", "inicio": start, "vencimento": inv.due_date,
               "aplicado": round(aplicado, 2), "resgatado_bruto": round(resg_bruto, 2),
               "resgatado_liquido": round(resg_liq, 2), "ir_iof_retido": round(ir, 2), "saldo": round(bal, 2),
               "historico_completo": complete, "movimentos": len(tl)}
        if complete:
            end = today if bal > 0.005 else (sells[-1].date if sells else today)
            flows = [(t.date, -abs(t.amount or t.net_amount or 0)) for t in buys] + \
                    [(t.date, abs(t.net_amount if t.net_amount is not None else (t.amount or 0))) for t in sells]
            if bal > 0.005:
                flows.append((today, bal))
            resultado = resg_liq + bal - aplicado
            first_d = min(d for d, _ in flows)
            tir = M.xirr(flows) if (end - first_d).days >= 30 else None  # anualizar poucos dias distorce
            # % do CDI: TIR do título ÷ CDI anualizado no mesmo período (aproximação ponderada no tempo)
            acc = accumulated(cdi, first_d, end) if not cdi.empty else None
            days = max((end - first_d).days, 1)
            cdi_aa = (1 + acc) ** (365.0 / days) - 1 if acc is not None and days >= 5 else None
            row.update(resultado=round(resultado, 2), tir_aa=tir,
                       pct_cdi=(tir / cdi_aa) if tir is not None and cdi_aa and cdi_aa > 0 else None)
        else:
            row.update(resultado=None, tir_aa=None, pct_cdi=None)
        out.append(row)
    done = [r for r in out if r["historico_completo"]]
    totals = {
        "titulos": len(out), "com_historico_completo": len(done),
        "resultado_liquido": round(sum(r["resultado"] for r in done), 2),
        "resultado_realizado": round(sum(r["resultado"] for r in done if r["status"] == "encerrado"), 2),
        "ir_iof_retido": round(sum(r["ir_iof_retido"] for r in out), 2),
        "aplicado": round(sum(r["aplicado"] for r in done), 2),
    }
    return {"titulos": sorted(out, key=lambda r: (r["status"] != "ativo", -(r["saldo"] or 0), str(r["inicio"]))),
            "totais": totals,
            "nota": "Resultado = resgates líquidos + saldo − aplicações. % do CDI compara com aplicar os mesmos "
                    "valores nas mesmas datas a 100% do CDI. Títulos aplicados antes do histórico da Pluggy (~12 meses) "
                    "aparecem como parciais, sem resultado."}


# ------------------------------------------------------------------ renda variável
def _close(s: Session, symbol: str | None, d: date) -> float | None:
    if not symbol:
        return None
    return s.scalar(select(AssetPrice.close).where(AssetPrice.symbol == symbol, AssetPrice.date <= d)
                    .order_by(AssetPrice.date.desc()).limit(1))


def equity_lots(s: Session) -> dict:
    assets = {a.id: a for a in s.scalars(select(Asset))}
    rv_cash = [e for e in s.scalars(select(FinancialEvent).where(
        FinancialEvent.is_removed.is_(False),
        FinancialEvent.event_type.in_(["INVESTMENT_CONTRIBUTION", "INVESTMENT_REDEMPTION"])))
        if any(k in (e.description or "").lower() for k in RV_TEXT)]
    used_cash: set[str] = set()
    report = []
    for inv in s.scalars(select(Investment).where(Investment.removed_at.is_(None))):
        if not _is_rv(inv):
            continue
        a = assets.get(inv.asset_id)
        sym = a.yahoo_symbol if a else None
        snaps = list(s.scalars(select(InvestmentBalance).where(InvestmentBalance.investment_id == inv.id,
                                                              InvestmentBalance.quantity.is_not(None))
                               .order_by(InvestmentBalance.date)))
        trades = sorted(s.scalars(select(InvestmentTransaction).where(
            InvestmentTransaction.investment_id == inv.id, InvestmentTransaction.removed_at.is_(None))),
            key=lambda t: t.date or date.min)
        lots = []
        # 1) negociações informadas pela Pluggy (exatas)
        for t in trades:
            q = abs(t.quantity or 0)
            if not q or not t.date:
                continue
            sign = 1 if (t.type or "").upper() == "BUY" else -1
            lots.append({"data": t.date, "quantidade": sign * q, "valor": sign * abs(t.amount or (q * (t.value or 0))),
                         "origem": "pluggy"})
        covered = {(l["data"], round(l["quantidade"], 6)) for l in lots}
        # 2) variações de quantidade entre snapshots ainda não explicadas
        base_qty = snaps[0].quantity if snaps else (inv.quantity or 0)
        base_date = snaps[0].date if snaps else None
        explained_before_base = sum(l["quantidade"] for l in lots if base_date and l["data"] <= base_date)
        for prev, cur in zip(snaps, snaps[1:]):
            dq = (cur.quantity or 0) - (prev.quantity or 0)
            if abs(dq) < 1e-9:
                continue
            if any(prev.date < d <= cur.date + timedelta(days=3) and abs(q - dq) < 1e-6 for d, q in covered):
                continue
            px = _close(s, sym, cur.date) or cur.value or inv.value
            est = abs(dq) * (px or 0)
            match = None
            for e in rv_cash:
                if e.source_id in used_cash or not (prev.date - timedelta(days=3) <= e.competence_date <= cur.date + timedelta(days=1)):
                    continue
                if (dq > 0) != (e.amount < 0):
                    continue
                if est and abs(abs(e.amount) - est) / est <= 0.15:
                    match = e
                    break
            if match is not None:
                used_cash.add(match.source_id)
                lots.append({"data": cur.date, "quantidade": dq, "valor": (1 if dq > 0 else -1) * abs(match.amount),
                             "origem": "banco"})
            else:
                lots.append({"data": cur.date, "quantidade": dq, "valor": (1 if dq > 0 else -1) * est,
                             "origem": "estimado (fechamento)"})
        lots.sort(key=lambda l: l["data"])
        # custo médio só sobre a quantidade com custo conhecido (método do preço médio)
        known_q, known_cost, realized = 0.0, 0.0, 0.0
        sales = []
        for l in lots:
            if l["quantidade"] > 0:
                known_q += l["quantidade"]
                known_cost += l["valor"]
            elif l["quantidade"] < 0:
                sold = -l["quantidade"]
                q = min(sold, known_q)
                pm = known_cost / known_q if known_q > 0 else None
                gain = (-l["valor"] * (q / sold) - pm * q) if pm is not None and q > 0 else 0.0
                realized += gain
                # venda só é apurável quando toda a quantidade vendida tem custo conhecido
                complete = q >= sold - 1e-6
                sales.append({"data": l["data"], "quantidade": sold, "valor_venda": -l["valor"],
                              "custo": round(pm * sold, 2) if complete and pm is not None else None,
                              "resultado": round(gain, 2) if complete else None, "origem": l["origem"]})
                if q > 0:
                    known_q -= q
                    known_cost -= pm * q
        qty = inv.quantity or 0.0
        unknown_q = max(0.0, (base_qty or 0) - explained_before_base) if snaps else max(0.0, qty - known_q)
        if known_q > qty:  # venda não detectada: corta quantidade e custo na mesma proporção (preço médio intacto)
            known_cost = known_cost * qty / known_q if known_q > 0 else 0.0
            known_q = qty
        pm = known_cost / known_q if known_q > 0 else None
        report.append({
            "ativo": inv.code or inv.name, "quantidade": qty, "preco_atual": inv.value, "saldo": inv.balance,
            "quantidade_com_custo": round(known_q, 6), "quantidade_sem_custo": round(max(0.0, qty - known_q), 6),
            "preco_medio_conhecido": pm, "custo_conhecido": round(known_cost, 2) if pm else None,
            "resultado_nao_realizado_conhecido": round(known_q * (inv.value or 0) - known_cost, 2) if pm else None,
            "resultado_realizado": round(realized, 2), "custo_completo": known_q >= qty - 1e-6 and qty > 0,
            "acompanhado_desde": base_date, "lotes": lots[-20:], "vendas": sales,
            "classe": (assets.get(inv.asset_id).asset_class if assets.get(inv.asset_id) else None),
            "investment_id": inv.id,
        })
    return {"ativos": sorted(report, key=lambda r: -(r["saldo"] or 0)),
            "nota": "Custo só onde há evidência: negociação da Pluggy (exata), débito/crédito de renda variável no banco "
                    "compatível (exato) ou quantidade × fechamento (estimado). Quantidade anterior ao início do "
                    "acompanhamento fica sem custo."}
