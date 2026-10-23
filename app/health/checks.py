"""Saúde dos dados: conferências automáticas que provam que os números batem com a fonte.

Cada verificação devolve status ok | atencao | falha | info, um resumo em português e os detalhes que permitem
achar o problema. Roda a cada reconstrução do razão (sincronização a cada 4 h) e o resultado fica guardado em
health_runs. Falhas e alertas viram itens da fila de revisão (kind data_health) — o resumo diário por e-mail
avisa quando algo deixa de bater.

Identidades verificadas:
- fatura: total(n) = total(n−1) + Σ lançamentos da fatura n (o pagamento da fatura anterior entra como crédito)
- cartão: saldo devedor informado = total da última fatura + Σ lançamentos depois do fechamento
- conta: saldo de hoje − Σ fluxos posteriores = saldo de fim de dia (nunca abaixo do limite de cheque especial)
- investimentos: aplicações/resgates no banco ≈ compras/vendas na corretora do mesmo banco (D+1, IR no resgate)
- razão: todo lançamento ativo tem evento e a soma dos eventos de cada conta = soma dos fluxos
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.reviews import ReviewCandidate, fmt_brl
from app.accounting.effective import excluded_pending_ids, find_posted_twin
from app.categorization.text import norm
from app.models import (Account, AccountBalance, Asset, AssetPrice, CardPaymentLink, CreditCardBill, FinancialEvent,
                        Investment, InvestmentTransaction, Item, MarketSeries, ReviewItem, SyncEvent,
                        SyncRun, Transaction)
from app.utils.time import today_brt, utcnow

ORDER = {"falha": 3, "atencao": 2, "info": 1, "ok": 0}
STATUS_LABEL = {"ok": "OK", "atencao": "Atenção", "falha": "Falha", "info": "Informativo"}
CRYPTO_RE = ("cripto", "bitcoin", "btc ")
RV_RE = ("renda variavel", "renda variável", "acoes", "ações", "bolsa", "etf", "fii")


@dataclass
class Check:
    id: str
    grupo: str
    titulo: str
    status: str = "ok"
    resumo: str = ""
    detalhes: list = field(default_factory=list)
    metricas: dict = field(default_factory=dict)

    def worse(self, st: str) -> None:
        if ORDER[st] > ORDER[self.status]:
            self.status = st

    def as_dict(self) -> dict:
        return {"id": self.id, "grupo": self.grupo, "titulo": self.titulo, "status": self.status,
                "resumo": self.resumo, "detalhes": self.detalhes[:40], "n_detalhes": len(self.detalhes),
                "metricas": self.metricas}


def _acc_names(s: Session) -> dict[str, str]:
    from app.models import AccountSetting
    nick = {a.account_id: a.nickname for a in s.scalars(select(AccountSetting)) if a.nickname}
    return {a.id: nick.get(a.id) or a.marketing_name or a.name or a.id[:8] for a in s.scalars(select(Account))}


def _item_names(s: Session) -> dict[str, str]:
    from app.accounting.institutions import institution_labels
    return institution_labels(s)


# ================================================================== coleta
def check_sync(s: Session, today: date) -> Check:
    c = Check("sync", "Coleta", "Sincronização com os bancos")
    names = _item_names(s)
    now = utcnow()
    items = list(s.scalars(select(Item).where(Item.is_active.is_(True))))
    if not items:
        c.status, c.resumo = "atencao", "Nenhuma conexão ativa."
        return c
    for it in items:
        nm = names.get(it.id, it.id[:8])
        last = it.last_synced_at
        if last is None:
            c.worse("falha")
            c.detalhes.append({"conexao": nm, "problema": "nunca sincronizou"})
            continue
        if last.tzinfo is None:  # SQLite devolve sem fuso (gravado em UTC)
            last = last.replace(tzinfo=timezone.utc)
        age_h = (now - last).total_seconds() / 3600
        if age_h > 72:
            c.worse("falha")
            c.detalhes.append({"conexao": nm, "problema": f"última sincronização há {age_h / 24:.0f} dias"})
        elif age_h > 26:
            c.worse("atencao")
            c.detalhes.append({"conexao": nm, "problema": f"última sincronização há {age_h:.0f} h"})
        if it.status in ("LOGIN_ERROR", "OUTDATED", "WAITING_USER_INPUT"):
            c.worse("falha")
            c.detalhes.append({"conexao": nm, "problema": f"status {it.status} na Pluggy: reconecte"})
        run = s.scalars(select(SyncRun).where(SyncRun.kind == "pluggy", SyncRun.item_id == it.id)
                        .order_by(SyncRun.id.desc()).limit(1)).first()
        if run is not None:
            errs = list(s.scalars(select(SyncEvent).where(SyncEvent.run_id == run.id, SyncEvent.level == "error")))
            for e in errs:
                # um passo que falha deixa os dados daquele tipo congelados na última leitura boa
                c.worse("falha")
                c.detalhes.append({"conexao": nm, "problema": f"erro em {e.step}: {e.message.splitlines()[0][:160]}"})
        if it.consent_expires_at:
            days = (it.consent_expires_at.date() - today).days
            if days <= 30:
                c.worse("falha" if days <= 7 else "atencao")
                c.detalhes.append({"conexao": nm, "problema": f"consentimento vence em {days} dias"})
    c.metricas = {"conexoes": len(items)}
    c.resumo = (f"{len(items)} conexões sincronizando normalmente." if c.status == "ok"
                else f"{len(c.detalhes)} problema(s) de coleta.")
    return c


def check_market(s: Session, today: date) -> Check:
    c = Check("mercado", "Coleta", "Cotações e índices")
    last_cdi = s.scalar(select(func.max(MarketSeries.date)).where(MarketSeries.code == "CDI"))
    if last_cdi is None:
        c.worse("atencao")
        c.detalhes.append({"serie": "CDI", "problema": "sem dados"})
    else:
        lag = int((today - last_cdi).days)
        if lag > 6:
            c.worse("atencao")
            c.detalhes.append({"serie": "CDI", "problema": f"último dado de {last_cdi:%d/%m/%Y}"})
    held = {a.yahoo_symbol for a, i in s.execute(select(Asset, Investment).join(Investment, Investment.asset_id == Asset.id)
                                                  .where(Investment.removed_at.is_(None), Investment.balance > 0))
            if a.yahoo_symbol}
    stale = []
    for sym in sorted(held):
        d = s.scalar(select(func.max(AssetPrice.date)).where(AssetPrice.symbol == sym))
        if d is None or (today - d).days > 6:
            stale.append(sym)
            c.detalhes.append({"serie": sym, "problema": "sem cotação" if d is None else f"última cotação {d:%d/%m/%Y}"})
    if stale:
        c.worse("atencao")
    c.metricas = {"ativos_cotados": len(held), "cdi_ate": last_cdi}
    c.resumo = ("CDI e cotações dos ativos em carteira atualizados." if c.status == "ok"
                else f"{len(c.detalhes)} série(s) desatualizada(s): métricas de carteira podem estar defasadas.")
    return c


# ================================================================== cartões
def check_bills(s: Session, today: date) -> Check:
    c = Check("faturas", "Conciliação", "Faturas × lançamentos do cartão")
    names = _acc_names(s)
    sums = dict(s.execute(select(Transaction.bill_id, func.sum(Transaction.amount_brl))
                          .where(Transaction.bill_id.is_not(None), Transaction.removed_at.is_(None),
                                 Transaction.id.not_in(excluded_pending_ids(s)))
                          .group_by(Transaction.bill_id)).all())
    by_acc: dict[str, list[CreditCardBill]] = defaultdict(list)
    for b in s.scalars(select(CreditCardBill).where(CreditCardBill.removed_at.is_(None))):
        if b.due_date:
            by_acc[b.account_id].append(b)
    checked = ok = 0
    for acc, bills in by_acc.items():
        bills.sort(key=lambda b: b.due_date)
        for prev, cur in zip(bills, bills[1:]):
            # faturas consecutivas (≈ 1 mês): buraco no histórico impede a conferência
            if (cur.due_date - prev.due_date).days > 40 or prev.total_amount is None or cur.total_amount is None:
                continue
            checked += 1
            got = sums.get(cur.id, 0.0) or 0.0
            diff = cur.total_amount - (prev.total_amount + got)
            if abs(diff) <= 1.0:
                ok += 1
                continue
            recent = (today - cur.due_date).days <= 200
            c.worse("falha" if recent else "atencao")
            c.detalhes.append({"cartao": names.get(acc), "vencimento": cur.due_date, "total_fatura": cur.total_amount,
                               "anterior": prev.total_amount, "soma_lancamentos": round(got, 2),
                               "diferenca": round(diff, 2)})
    c.metricas = {"faturas_conferidas": checked, "batem": ok}
    c.resumo = (f"{ok} de {checked} faturas batem centavo a centavo com os lançamentos." if c.status == "ok"
                else f"{checked - ok} fatura(s) não batem: falta ou sobra lançamento no cartão.")
    if not checked:
        c.status, c.resumo = "info", "Ainda não há duas faturas consecutivas para conferir."
    return c


def check_card_balance(s: Session, today: date) -> Check:
    from app.accounting.balance import card_usage
    c = Check("cartao_saldo", "Conciliação", "Saldo devedor do cartão × lançamentos em aberto")
    names = _acc_names(s)
    for a in s.scalars(select(Account).where(Account.type == "CREDIT", Account.removed_at.is_(None))):
        last = s.scalars(select(CreditCardBill).where(CreditCardBill.account_id == a.id, CreditCardBill.removed_at.is_(None),
                                                      CreditCardBill.close_date.is_not(None))
                         .order_by(CreditCardBill.close_date.desc()).limit(1)).first()
        _, used = card_usage(a)
        used = used if used is not None else a.balance
        if last is None or used is None or last.total_amount is None:
            continue
        after = s.scalar(select(func.coalesce(func.sum(Transaction.amount_brl), 0.0))
                         .where(Transaction.account_id == a.id, Transaction.removed_at.is_(None),
                                Transaction.date > last.close_date,
                                Transaction.id.not_in(excluded_pending_ids(s)))) or 0.0
        expected = last.total_amount + after
        diff = used - expected
        row = {"cartao": names.get(a.id), "saldo_informado": round(used, 2), "ultima_fatura": round(last.total_amount, 2),
               "lancado_depois_do_fechamento": round(after, 2), "diferenca": round(diff, 2)}
        c.detalhes.append(row)
        if abs(diff) > max(1.0, 0.01 * abs(used)):
            # pendentes ainda não enviados pela fonte explicam diferenças pequenas e temporárias
            c.worse("atencao" if abs(diff) < 500 else "falha")
    diffs = [f"{d['cartao']}: {fmt_brl(d['diferenca'])}" for d in c.detalhes if abs(d["diferenca"]) > 1.0]
    c.resumo = ("Saldo devedor de cada cartão = última fatura + compras/pagamentos posteriores." if c.status == "ok"
                else f"Saldo informado pelo banco difere dos lançamentos em aberto ({'; '.join(diffs)}). Compras dos "
                     "últimos dias costumam chegar depois do saldo; se a diferença persistir, falta lançamento.")
    return c


def check_card_payments(s: Session, today: date) -> Check:
    c = Check("pagamento_fatura", "Conciliação", "Pagamentos de fatura casados com o cartão")
    linked = set(s.scalars(select(CardPaymentLink.payment_tx_id)))
    rows = list(s.scalars(select(FinancialEvent).where(FinancialEvent.event_type == "CARD_PAYMENT",
                                                        FinancialEvent.is_removed.is_(False))))
    bank = [e for e in rows if e.amount < 0]
    unl = [e for e in bank if e.source_id not in linked]
    for e in unl:
        c.detalhes.append({"data": e.competence_date, "valor": e.amount, "descricao": e.description})
    if unl:
        c.worse("atencao")
    c.metricas = {"pagamentos": len(bank), "casados": len(bank) - len(unl)}
    c.resumo = (f"{len(bank)} pagamentos de fatura, todos ligados a um cartão conectado." if not unl
                else f"{len(unl)} pagamento(s) de fatura sem cartão correspondente.")
    return c


# ================================================================== contas
def check_bank_balances(s: Session, today: date) -> Check:
    c = Check("saldo_conta", "Conciliação", "Saldos bancários reconstruídos dia a dia")
    names = _acc_names(s)
    for a in s.scalars(select(Account).where(Account.type == "BANK", Account.removed_at.is_(None))):
        if a.balance is None:
            continue
        v = (a.bank_data or {}).get("overdraftContractedLimit")
        od = float(v) if isinstance(v, (int, float)) else 0.0
        flows = s.execute(select(Transaction.date, func.sum(Transaction.flow))
                          .where(Transaction.account_id == a.id, Transaction.removed_at.is_(None),
                                 Transaction.status != "PENDING")
                          .group_by(Transaction.date).order_by(Transaction.date.desc())).all()
        bal = a.balance
        worst = (None, bal)
        for d, f in flows:  # do mais recente para o mais antigo: saldo no fim do dia d−1 = saldo fim de d − fluxo de d
            if d > today:
                bal -= f or 0
                continue
            if bal < worst[1]:
                worst = (d, bal)
            bal -= f or 0
        if flows and bal < worst[1]:  # saldo antes do primeiro lançamento conhecido
            worst = (flows[-1][0] - timedelta(days=1), bal)
        neg = worst[1] < -od - 1.0
        if neg:
            c.worse("falha")
        c.detalhes.append({"conta": names.get(a.id), "saldo_atual": round(a.balance, 2),
                           "menor_saldo_reconstruido": round(worst[1], 2), "em": worst[0], "limite_cheque_especial": od,
                           "dias": len(flows)})
        # continuidade entre fotos de saldo (uma por dia de sincronização)
        snaps = list(s.scalars(select(AccountBalance).where(AccountBalance.account_id == a.id,
                                                            AccountBalance.balance.is_not(None))
                               .order_by(AccountBalance.date)))
        if len(snaps) >= 2:
            first, last = snaps[max(0, len(snaps) - 31)], snaps[-1]
            day_flow = {d: f or 0 for d, f in flows}
            inner = sum(f for d, f in day_flow.items() if first.date < d < last.date)
            # a foto é tirada no meio do dia: cada lançamento dos dias das pontas pode ou não estar nela
            edge = [t.flow or 0 for t in s.scalars(select(Transaction).where(
                Transaction.account_id == a.id, Transaction.removed_at.is_(None), Transaction.status != "PENDING",
                Transaction.date.in_([first.date, last.date])))]
            lo = inner + sum(f for f in edge if f < 0)
            hi = inner + sum(f for f in edge if f > 0)
            delta = last.balance - first.balance
            if not (lo - 1.0 <= delta <= hi + 1.0):
                c.worse("atencao")
                c.detalhes.append({"conta": names.get(a.id), "problema": "variação de saldo entre sincronizações não "
                                   "fecha com os lançamentos", "de": first.date, "ate": last.date,
                                   "variacao_saldo": round(delta, 2), "soma_lancamentos": round(inner, 2)})
    c.resumo = ("Reconstruindo para trás a partir do saldo atual, nenhuma conta fica negativa em nenhum dia."
                if c.status == "ok" else "Saldo reconstruído fica negativo ou não fecha: provável entrada faltando.")
    return c


# ================================================================== investimentos
def _clusters(points: list[tuple[date, str, float, str]], gap: int = 3) -> list[list]:
    out: list[list] = []
    for p in sorted(points, key=lambda x: x[0]):
        if out and (p[0] - out[-1][-1][0]).days <= gap:
            out[-1].append(p)
        else:
            out.append([p])
    return out


def check_investments(s: Session, today: date) -> Check:
    c = Check("investimentos", "Conciliação", "Aplicações e resgates: banco × corretora")
    names = _item_names(s)
    inv_item = {i.id: i.item_id for i in s.scalars(select(Investment))}
    broker: dict[str, list] = defaultdict(list)
    for t in s.scalars(select(InvestmentTransaction).where(InvestmentTransaction.removed_at.is_(None))):
        d = t.date or t.trade_date
        typ = (t.type or "").upper()
        if d is None or typ not in ("BUY", "SELL"):
            continue
        broker[inv_item.get(t.investment_id)].append((d, "c_buy" if typ == "BUY" else "c_sell",
                                                     abs(t.amount or t.net_amount or 0), ""))
    bank: dict[str, list] = defaultdict(list)
    crypto = 0.0
    for e in s.scalars(select(FinancialEvent).where(FinancialEvent.is_removed.is_(False), FinancialEvent.event_type.in_(
            ["INVESTMENT_CONTRIBUTION", "INVESTMENT_REDEMPTION"]))):
        text = norm(e.description)
        if any(k in text for k in CRYPTO_RE):
            crypto += -e.amount
            continue
        bank[e.item_id].append((e.competence_date, "b_out" if e.amount < 0 else "b_in", abs(e.amount), e.description or ""))
    since = today - timedelta(days=180)
    episodes = bad = 0
    for item_id, pts in bank.items():
        if not broker.get(item_id):
            c.worse("info")
            tot = sum(p[2] for p in pts if p[0] >= since)
            if tot:
                c.detalhes.append({"conexao": names.get(item_id), "problema": "movimentação de investimento sem corretora "
                                   f"conectada nessa instituição ({fmt_brl(tot)} em 6 meses)"})
            continue
        start = min(p[0] for p in broker[item_id]) + timedelta(days=3)
        for cl in _clusters(pts + broker[item_id]):
            d0, d1 = cl[0][0], cl[-1][0]
            if d0 < max(start, since) or (today - d1).days < 4:
                continue  # antes do histórico da corretora, ou ainda liquidando
            tot = defaultdict(float)
            for p in cl:
                tot[p[1]] += p[2]
            episodes += 1
            out_ok = abs(tot["b_out"] - tot["c_buy"]) <= max(60.0, 0.02 * tot["c_buy"])
            # no resgate o banco recebe o líquido: entre 94% e 100% do bruto vendido (IR/IOF)
            in_ok = tot["c_sell"] * 0.94 - 60 <= tot["b_in"] <= tot["c_sell"] + 60
            net_bank, net_broker = tot["b_in"] - tot["b_out"], tot["c_sell"] - tot["c_buy"]
            net_ok = abs(net_bank - net_broker) <= max(60.0, 0.03 * (tot["c_sell"] + tot["c_buy"]))
            if (out_ok and in_ok) or net_ok:
                continue
            bad += 1
            c.worse("atencao")
            c.detalhes.append({"conexao": names.get(item_id), "de": d0, "ate": d1,
                               "aplicado_no_banco": round(tot["b_out"], 2), "comprado_na_corretora": round(tot["c_buy"], 2),
                               "resgatado_no_banco": round(tot["b_in"], 2), "vendido_na_corretora": round(tot["c_sell"], 2)})
    if crypto:
        c.detalhes.append({"conexao": "—", "problema": f"cripto comprada pelo banco sem custódia conectada: {fmt_brl(crypto)}"})
    c.metricas = {"episodios": episodes, "divergentes": bad, "cripto": round(crypto, 2)}
    c.resumo = (f"{episodes - bad} de {episodes} movimentações dos últimos 6 meses batem entre banco e corretora."
                if not bad else f"{bad} movimentação(ões) sem correspondência entre banco e corretora.")
    return c


# ================================================================== razão
def check_ledger(s: Session, today: date) -> Check:
    c = Check("razao", "Razão", "Livro razão completo e somando certo")
    names = _acc_names(s)
    tx = s.execute(select(Transaction.id, Transaction.account_id, Transaction.flow)
                   .where(Transaction.removed_at.is_(None))).all()
    ev = s.execute(select(FinancialEvent.source_id, FinancialEvent.account_id, FinancialEvent.amount)
                   .where(FinancialEvent.source_type == "transaction", FinancialEvent.is_removed.is_(False))).all()
    ev_ids = {e.source_id for e in ev}
    tx_ids = {t.id for t in tx}
    missing = [t for t in tx if t.id not in ev_ids]
    orphan = [e for e in ev if e.source_id not in tx_ids]
    if missing:
        c.worse("falha")
        c.detalhes.append({"problema": f"{len(missing)} lançamento(s) sem evento no razão"})
    if orphan:
        c.worse("falha")
        c.detalhes.append({"problema": f"{len(orphan)} evento(s) cujo lançamento de origem não existe mais"})
    st = defaultdict(float)
    se = defaultdict(float)
    for t in tx:
        st[t.account_id] += round(t.flow or 0, 2)
    for e in ev:
        se[e.account_id] += e.amount or 0
    for acc in st:
        if abs(st[acc] - se[acc]) > 0.05:
            c.worse("falha")
            c.detalhes.append({"conta": names.get(acc), "soma_lancamentos": round(st[acc], 2),
                               "soma_eventos": round(se[acc], 2)})
    c.metricas = {"lancamentos": len(tx), "eventos": len(ev)}
    c.resumo = (f"{len(tx)} lançamentos ativos, todos no razão; soma por conta igual à fonte."
                if c.status == "ok" else "Razão incompleto ou com soma diferente da fonte: reconstrua o razão.")
    return c


def check_transfers(s: Session, today: date) -> Check:
    c = Check("transferencias", "Razão", "Transferências entre contas próprias pareadas")
    rows = list(s.scalars(select(FinancialEvent).where(FinancialEvent.event_type == "INTERNAL_TRANSFER",
                                                        FinancialEvent.is_removed.is_(False))))
    alone = [e for e in rows if e.transfer_id is None]
    for e in alone:
        c.detalhes.append({"data": e.competence_date, "valor": e.amount, "descricao": e.description})
    if alone:
        c.worse("atencao")
    ext = s.scalar(select(func.count()).select_from(FinancialEvent).where(
        FinancialEvent.event_type == "EXTERNAL_OWN_TRANSFER", FinancialEvent.is_removed.is_(False))) or 0
    c.metricas = {"transferencias": len(rows), "sem_par": len(alone), "contas_nao_conectadas": ext}
    c.resumo = (f"{len(rows)} pontas de transferência, todas com a outra ponta encontrada." if not alone
                else f"{len(alone)} transferência(s) interna(s) sem a outra ponta.")
    if ext:
        c.resumo += f" {ext} movimento(s) com conta própria não conectada."
    return c


def check_pending(s: Session, today: date) -> Check:
    c = Check("pendentes", "Razão", "Lançamentos pendentes e duplicidades")
    names = _acc_names(s)
    acc_type = {a.id: a.type for a in s.scalars(select(Account))}
    pend = list(s.scalars(select(Transaction).where(Transaction.removed_at.is_(None), Transaction.status == "PENDING")))
    stale_card = [t for t in pend if acc_type.get(t.account_id) == "CREDIT" and (today - t.date).days > 40]
    stale_bank = [t for t in pend if acc_type.get(t.account_id) == "BANK" and (today - t.date).days > 7]
    for t in stale_bank:
        c.detalhes.append({"conta": names.get(t.account_id), "data": t.date, "valor": t.flow, "descricao": t.description,
                           "problema": "pendente há mais de 7 dias na conta"})
    if stale_bank:
        c.worse("atencao")
    # pendente que virou definitivo com outro id (a fonte deveria ter removido o pendente)
    posted = defaultdict(list)
    since = today - timedelta(days=120)
    for t in s.scalars(select(Transaction).where(Transaction.removed_at.is_(None), Transaction.status != "PENDING",
                                                  Transaction.date >= since)):
        posted[(t.account_id, round(abs(t.flow or 0.0), 2))].append(t)
    # gêmeos já são descartados na fonte única (app/accounting/effective.py): aqui só informa quantos foram
    twins = 0
    for p in pend:
        if find_posted_twin(p, posted) is not None:
            twins += 1
            c.detalhes.append({"conta": names.get(p.account_id), "data": p.date, "valor": p.flow,
                               "descricao": p.description,
                               "problema": "pendente com efetivado igual: descartado do razão (informativo)"})
    future = list(s.scalars(select(Transaction).where(Transaction.removed_at.is_(None), Transaction.status != "PENDING",
                                                       Transaction.date > today + timedelta(days=1))))
    for t in future:
        c.detalhes.append({"conta": names.get(t.account_id), "data": t.date, "valor": t.flow, "descricao": t.description,
                           "problema": "lançamento efetivado com data futura"})
    if future:
        c.worse("atencao")
    c.metricas = {"pendentes": len(pend), "pendentes_antigos_cartao": len(stale_card), "duplicados": twins}
    c.resumo = (f"{len(pend)} pendentes normais; {len(stale_card)} parcelas antigas fora de fatura já ignoradas; "
                f"{twins} duplicidade(s) pendente→efetivado já descartada(s) do razão." if c.status == "ok"
                else f"{len(c.detalhes)} lançamento(s) pendente(s) suspeito(s).")
    return c


def check_classification(s: Session, today: date) -> Check:
    c = Check("classificacao", "Razão", "Cobertura da classificação (90 dias)")
    since = today - timedelta(days=90)
    rows = s.execute(select(FinancialEvent.category_id, FinancialEvent.amount, FinancialEvent.confidence,
                            FinancialEvent.rule_source)
                     .where(FinancialEvent.is_removed.is_(False), FinancialEvent.competence_date >= since,
                            FinancialEvent.event_type.in_(["EXPENSE", "INCOME", "REFUND"]))).all()
    spend = sum(-r.amount for r in rows if r.amount < 0) or 1.0
    nc = sum(-r.amount for r in rows if r.amount < 0 and r.category_id == "nc")
    pend_in = sum(r.amount for r in rows if r.amount > 0 and r.category_id == "rec.pix_terceiros")
    low = sum(abs(r.amount) for r in rows if r.confidence < 0.6 and r.rule_source not in ("manual", "rule"))
    by_src = defaultdict(float)
    for r in rows:
        by_src[r.rule_source] += abs(r.amount)
    tot = sum(by_src.values()) or 1.0
    c.metricas = {"gasto_90d": round(spend, 2), "sem_categoria": round(nc, 2), "recebidos_a_classificar": round(pend_in, 2),
                  "baixa_confianca": round(low, 2),
                  "por_origem": {k: round(v / tot, 3) for k, v in sorted(by_src.items(), key=lambda x: -x[1])}}
    if nc / spend > 0.05:
        c.worse("atencao")
    if low / tot > 0.15:
        c.worse("atencao")
    c.resumo = (f"{1 - nc / spend:.0%} do gasto com categoria; {low / tot:.0%} do volume com confiança baixa.")
    return c


def check_reviews(s: Session, today: date) -> Check:
    c = Check("revisoes", "Razão", "Fila de revisão")
    rows = s.execute(select(ReviewItem.severity, func.count()).where(ReviewItem.status == "open",
                                                                      ReviewItem.kind != "data_health")
                     .group_by(ReviewItem.severity)).all()
    cnt = {k: v for k, v in rows}
    c.metricas = cnt
    c.status = "info"
    c.resumo = f"{sum(cnt.values())} itens em aberto ({cnt.get('high', 0)} graves, {cnt.get('warn', 0)} de atenção)."
    return c


CHECKS = [check_sync, check_market, check_bills, check_card_balance, check_card_payments, check_bank_balances,
          check_investments, check_ledger, check_transfers, check_pending, check_classification, check_reviews]


def run_checks(s: Session, today: date | None = None) -> dict:
    today = today or today_brt()
    results = []
    for fn in CHECKS:
        try:
            results.append(fn(s, today).as_dict())
        except Exception as exc:  # noqa: BLE001 — uma verificação quebrada não derruba as outras
            results.append(Check(fn.__name__.removeprefix("check_"), "Sistema", fn.__name__, "atencao",
                                 f"A verificação não rodou: {str(exc)[:200]}").as_dict())
    overall = max((r["status"] for r in results), key=lambda x: ORDER[x], default="ok")
    if overall == "info":
        overall = "ok"
    counts = defaultdict(int)
    for r in results:
        counts[r["status"]] += 1
    return {"em": utcnow(), "status": overall, "contagem": dict(counts), "verificacoes": results}


def health_reviews(report: dict) -> list[ReviewCandidate]:
    out = []
    for r in report["verificacoes"]:
        if r["status"] not in ("falha", "atencao"):
            continue
        out.append(ReviewCandidate(f"health:{r['id']}", "data_health", "high" if r["status"] == "falha" else "warn",
                                   "health", r["id"], f"Saúde dos dados: {r['titulo']}", r["resumo"],
                                   {"detalhes": _jsonable(r["detalhes"][:10])}))
    return out


def _jsonable(v):
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, date):
        return v.isoformat()
    return v


def save_run(s: Session, report: dict, trigger: str) -> None:
    from app.models import HealthRun
    s.add(HealthRun(trigger=trigger, status=report["status"], summary=report["contagem"],
                    results=_jsonable(report["verificacoes"])))
    s.flush()
    ids = list(s.scalars(select(HealthRun.id).order_by(HealthRun.id.desc()).offset(300)))
    if ids:
        from sqlalchemy import delete
        s.execute(delete(HealthRun).where(HealthRun.id.in_(ids)))


def latest(s: Session) -> dict | None:
    from app.models import HealthRun
    r = s.scalars(select(HealthRun).order_by(HealthRun.id.desc()).limit(1)).first()
    if r is None:
        return None
    hist = s.execute(select(HealthRun.at, HealthRun.status).order_by(HealthRun.id.desc()).limit(60)).all()
    return {"em": r.at, "gatilho": r.trigger, "status": r.status, "contagem": r.summary, "verificacoes": r.results,
            "historico": [{"em": a, "status": st} for a, st in reversed(hist)]}
