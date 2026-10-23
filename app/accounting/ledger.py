"""Reconstrução determinística do livro razão (camada 4).

transações (camada 2) + cadastro (camada 3) + ajustes manuais → financial_events, vínculos, auditoria e revisões.
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.accounting.effective import SUPERSEDED, ineffective_pending
from app.alerts.reviews import ReviewCandidate, fmt_brl
from app.categorization.chart import MCC_MAP, seed_chart
from app.categorization.cnae import cnae_category, norm_cnae
from app.categorization.engine import (Decision, TxView, compile_rules, keyword_category, match_rule,
                                       merchant_key)
from app.categorization.text import counterparty_from_description, merchant_alias, norm
from app.config.settings import get_settings
from app.models import (Account, AccountSetting, CardPaymentLink, Category, CategoryRule, CreditCardBill,
                        EventOverride, EventType, FinancialEvent, IdentityRecord, InternalTransfer, Item, LedgerAudit,
                        Merchant, MerchantAlias, PluggyCategoryMap, Transaction)
from app.reconciliation.matching import (card_payments, connected_card_issuers, installment_key, investment_flows,
                                         transfers)
from app.utils.time import today_brt, utcnow

log = logging.getLogger(__name__)
ESTORNO_RE = re.compile(r"\bestorno|devolucao|devolvid[oa]|reembolso|chargeback|cancelamento de compra")
STALE_PENDING_DAYS = 40
TOLL_TAG_RE = re.compile(r"sem parar|semparar|conectcar|veloe|move mais|\btag\b|pedagio")
_FLIP = {
    "INVESTMENT_CONTRIBUTION": ("INVESTMENT_REDEMPTION", "pat.resgate", 1),
    "INVESTMENT_REDEMPTION": ("INVESTMENT_CONTRIBUTION", "pat.aporte", -1),
    "LOAN_PAYMENT": ("LOAN_IN", "pat.emprestimo_in", 1),
    "LOAN_IN": ("LOAN_PAYMENT", "pat.emprestimo_pg", -1),
}


def resolve_event_type(cat: Category | None, flow: float, explicit: str | None) -> tuple[str, str | None]:
    """Tipo econômico a partir da categoria e do sentido do fluxo. Retorna (tipo, categoria ajustada)."""
    if explicit:
        return explicit, None
    if cat is None:
        return (EventType.EXPENSE if flow < 0 else EventType.INCOME), None
    if cat.nature == "patrimonial":
        base = cat.default_event_type or EventType.IGNORE
        flip = _FLIP.get(base)
        if flip and ((flip[2] > 0 and flow > 0) or (flip[2] < 0 and flow < 0)):
            return flip[0], flip[1]
        return base, None
    if cat.nature == "receita":
        return EventType.INCOME, None
    if cat.nature == "imposto":
        return EventType.TAX, None
    if cat.nature == "financeiro":
        return cat.default_event_type or EventType.FINANCIAL_EXPENSE, None
    return (EventType.EXPENSE if flow <= 0 else EventType.REFUND), None


def owner_identity(s: Session) -> tuple[set[str], list[list[str]]]:
    docs = {d for d in s.scalars(select(Account.tax_number).where(Account.tax_number.is_not(None))) if d}
    names: set[str] = set()
    for rec in s.scalars(select(IdentityRecord)):
        if rec.tax_number:
            docs.add(rec.tax_number)
        if rec.full_name:
            names.add(rec.full_name)
    for owner in s.scalars(select(Account.owner).where(Account.owner.is_not(None))):
        names.add(owner)
    names.update(n for n in get_settings().owner_names.split(",") if n.strip())
    tokens = [[w for w in norm(n).split() if len(w) > 2] for n in names]
    return {d for d in docs if len(d) == 11}, [t for t in tokens if len(t) >= 2]


def load_tx_views(s: Session) -> list[TxView]:
    rows = s.execute(select(Transaction, Account.type).join(Account, Account.id == Transaction.account_id)).all()
    out = []
    for t, acc_type in rows:
        out.append(TxView(
            id=t.id, account_id=t.account_id, item_id=t.item_id, account_type=acc_type or "BANK", date=t.date,
            flow=t.flow or 0.0, description=t.description or "", description_raw=t.description_raw,
            pluggy_cat=t.pluggy_category_id, merchant_name=t.merchant_name, merchant_cnpj=t.merchant_cnpj,
            mcc=t.mcc, payment_method=t.payment_method,
            counterparty_name=t.counterparty_name or counterparty_from_description(t.description),
            counterparty_doc=t.counterparty_doc, payer_doc=t.payer_doc, receiver_doc=t.receiver_doc,
            status=t.status, installment_number=t.installment_number, total_installments=t.total_installments,
            removed=t.removed_at is not None, merchant_cnae=norm_cnae(t.merchant_cnae)))
    return out


def pretty_name(description: str | None) -> str | None:
    """'UBER *TRIP 1234' → 'Uber Trip'; mantém a grafia original quando já é mista."""
    d = re.sub(r"[*#_]+", " ", (description or "").split("|")[-1])
    d = re.sub(r"\b\d[\d./-]*\b", " ", d)
    d = re.sub(r"\s+", " ", d).strip()
    if not d:
        return None
    return d.title() if d.isupper() or d.islower() else d


class MerchantResolver:
    def __init__(self, s: Session):
        self.s = s
        self.by_doc = {m.cnpj: m for m in s.scalars(select(Merchant).where(Merchant.cnpj.is_not(None)))}
        self.by_alias: dict[str, Merchant] = {}
        merchants = {m.id: m for m in s.scalars(select(Merchant))}
        for a in s.scalars(select(MerchantAlias)):
            if a.merchant_id in merchants:
                self.by_alias[a.alias] = merchants[a.merchant_id]

    def resolve(self, tx: TxView) -> Merchant | None:
        key = merchant_key(tx)
        if key is None:
            return None
        kind, value = key
        if kind == "doc":
            m = self.by_doc.get(value)
            if m is None:
                m = Merchant(canonical_name=(tx.party_name or merchant_alias(tx.description) or value)[:200],
                             cnpj=value)
                self.s.add(m)
                self.by_doc[value] = m
            if tx.merchant_cnae and not m.cnae:  # o CNAE informado pela Pluggy fica no cadastro do comerciante
                m.cnae, m.cnae_source = tx.merchant_cnae, "pluggy"
            return m
        m = self.by_alias.get(value)
        if m is None:
            m = Merchant(canonical_name=(tx.merchant_name or tx.counterparty_name or pretty_name(tx.description) or value).strip()[:200])
            self.s.add(m)
            self.s.flush()
            self.s.add(MerchantAlias(alias=value, merchant_id=m.id))
            self.by_alias[value] = m
        return m


def rebuild_ledger(s: Session, actor: str = "system", reason: str = "rebuild") -> dict:
    settings = get_settings()
    seed_chart(s)
    cats = {c.id: c for c in s.scalars(select(Category))}
    pmap = {m.pluggy_category_id: (m.category_id, m.confidence) for m in s.scalars(select(PluggyCategoryMap))}
    rule_objs = list(s.scalars(select(CategoryRule)))
    rules = compile_rules(rule_objs)
    overrides = {o.source_id: o for o in s.scalars(select(EventOverride).where(EventOverride.source_type == "transaction"))}
    own_docs, own_names = owner_identity(s)
    txs = load_tx_views(s)
    bills = [{"id": b.id, "account_id": b.account_id, "due_date": b.due_date, "total_amount": b.total_amount}
             for b in s.scalars(select(CreditCardBill))]
    card_rows = list(s.scalars(select(Account).where(Account.type == "CREDIT", Account.removed_at.is_(None))))
    card_accounts = {a.id: a.item_id for a in card_rows}
    nick = {x.account_id: x.nickname for x in s.scalars(select(AccountSetting)) if x.nickname}
    item_nick = {i.id: i.nickname for i in s.scalars(select(Item)) if i.nickname}
    card_issuers = connected_card_issuers([" ".join(filter(None, (a.name, a.marketing_name, nick.get(a.id),
                                                                  item_nick.get(a.item_id)))) for a in card_rows])
    bill_due = {b["id"]: b["due_date"] for b in bills}
    tx_bill = dict(s.execute(select(Transaction.id, Transaction.bill_id).where(Transaction.bill_id.is_not(None))).all())

    # 0. pendentes duplicados (têm POSTED equivalente) ou velhos sem efetivação: fora do razão e das conciliações
    dropped = ineffective_pending(txs)
    txs_live = [t for t in txs if t.id not in dropped]

    # 1. reconciliação estrutural
    structural: dict[str, Decision] = {
        tid: Decision("pat.ignorar", "IGNORE", "structural", why, 0.95,
                      review=["pending_stale"] if why != SUPERSEDED else [])
        for tid, why in dropped.items()}
    structural.update(investment_flows(txs_live))
    cp, card_links = card_payments(txs_live, bills, card_accounts, skip=set(structural), connected_issuers=card_issuers)
    structural.update(cp)
    tr, transfer_links = transfers(txs_live, own_docs, own_names, skip=set(structural))
    structural.update(tr)

    # vínculos derivados são recriados a cada reconstrução
    s.execute(delete(InternalTransfer))
    s.execute(delete(CardPaymentLink))
    s.flush()
    transfer_ids: dict[str, int] = {}
    for l in transfer_links:
        it = InternalTransfer(out_tx_id=l.out_tx, in_tx_id=l.in_tx, amount=l.amount, days_apart=l.days,
                              method=l.method, confidence=l.confidence)
        s.add(it)
        s.flush()
        transfer_ids[l.out_tx] = transfer_ids[l.in_tx] = it.id
    for l in card_links:
        s.add(CardPaymentLink(payment_tx_id=l.payment_tx, card_account_id=l.card_account_id, card_tx_id=l.card_tx,
                              bill_id=l.bill_id, method=l.method, diff=l.diff, confidence=l.confidence))

    # 2. decisão por transação
    merchants = MerchantResolver(s)
    hits: Counter = Counter()
    decided: dict[str, tuple[TxView, Decision, Merchant | None, EventOverride | None]] = {}
    for tx in txs:
        m = merchants.resolve(tx) if not tx.removed else None
        o = overrides.get(tx.id)
        d = _decide(tx, o, rules, structural, m, pmap, cats, hits)
        decided[tx.id] = (tx, d, m, o)
    s.flush()
    model_info = {}
    if settings.classifier_enabled:
        from app.categorization.model import apply_model
        try:
            model_info = apply_model(s, decided, cats)
        except Exception as exc:  # noqa: BLE001 — o razão nunca deixa de ser reconstruído por causa do modelo
            log.exception("classificador falhou")
            model_info = {"habilitado": False, "motivo": f"erro: {str(exc)[:200]}"}
    _mirror_refunds(decided, cats, own_docs)

    for r in rule_objs:
        r.hits = hits.get(r.id, 0)

    # 3. eventos + auditoria + candidatos a revisão
    existing = {e.source_id: e for e in s.scalars(select(FinancialEvent).where(
        FinancialEvent.source_type == "transaction", FinancialEvent.split_seq == 0))}
    now = utcnow()
    review_candidates: list[ReviewCandidate] = []
    by_merchant: dict[tuple[int, str], list] = defaultdict(list)
    counts: Counter = Counter()
    for tx_id, (tx, d, m, o) in decided.items():
        cat = cats.get(d.category_id or "nc") or cats["nc"]
        etype, adjusted_cat = resolve_event_type(cat, tx.flow, d.event_type)
        cat_id = adjusted_cat or cat.id
        reasons = list(d.review)
        if d.rule_source not in ("manual", "rule", "merchant") and not tx.removed:
            amount = abs(tx.flow)
            if cat_id == "nc":
                reasons.append("uncategorized")
            elif d.confidence < settings.review_min_confidence and amount >= settings.review_min_amount \
                    and etype in EventType.PNL:
                reasons.append("low_confidence")
            if cat_id == "terceiros.pf" and tx.flow < 0 and amount >= settings.review_min_amount:
                reasons.append("pix_pf_out")
            if cat_id == "rec.pix_terceiros" and amount >= settings.review_min_amount:
                reasons.append("pix_in_unknown")
            if "low_confidence" in reasons and ("pix_pf_out" in reasons or "pix_in_unknown" in reasons):
                reasons.remove("low_confidence")
        reasons = list(dict.fromkeys(reasons))
        values = dict(
            account_id=tx.account_id, item_id=tx.item_id,
            competence_date=(o.competence_date if o and o.competence_date else tx.date),
            cash_date=tx.date if tx.account_type == "BANK" else bill_due.get(tx_bill.get(tx.id)),
            amount=round(tx.flow, 2), event_type=etype, category_id=cat_id,
            merchant_id=m.id if m else None, description=tx.description,
            counterparty=tx.party_name, rule_source=d.rule_source, rule_id=d.rule_id,
            confidence=round(d.confidence, 3), is_inferred=d.rule_source != "manual",
            needs_review=bool(reasons), review_reason=",".join(reasons) or None,
            transfer_id=transfer_ids.get(tx_id), installment_key=installment_key(tx),
            is_pending=tx.status == "PENDING", is_removed=tx.removed,
            note=o.note if o else None, tags=o.tags if o else None, built_at=now)
        ev = existing.get(tx_id)
        if ev is None:
            s.add(FinancialEvent(source_type="transaction", source_id=tx_id, split_seq=0, **values))
            counts["created"] += 1
        else:
            for fld in ("event_type", "category_id", "amount", "is_removed"):
                old, new = getattr(ev, fld), values[fld]
                if old != new:
                    s.add(LedgerAudit(source_id=tx_id, field=fld, old=str(old), new=str(new), actor=actor,
                                      reason=f"{reason}: {d.rule_source}/{d.rule_id or '-'}"))
                    counts["changed"] += 1
            for k, v in values.items():
                setattr(ev, k, v)
        counts[etype] += 1
        for rs in reasons:
            if m is not None and rs in GROUPABLE:
                by_merchant[(m.id, rs)].append((tx, cat, d))
            else:
                review_candidates.append(_event_review(rs, tx, cat, d))
    # revisões agrupadas por comerciante/contraparte: uma decisão vale para todos os lançamentos
    for (mid, rs), group in by_merchant.items():
        if len(group) == 1:
            tx, cat, d = group[0]
            review_candidates.append(_event_review(rs, tx, cat, d))
            continue
        total = sum(t.flow for t, _, _ in group)
        tx0, cat0, d0 = max(group, key=lambda g: g[0].date)
        name = tx0.party_name or tx0.description
        review_candidates.append(ReviewCandidate(
            fingerprint=f"merchant:{mid}:{rs}", kind=rs, severity="info", entity_type="merchant", entity_id=str(mid),
            title=f"{name}: {len(group)} lançamentos, {fmt_brl(total)}",
            detail=f"De {min(g[0].date for g in group):%d/%m/%Y} a {tx0.date:%d/%m/%Y}. Sugestão atual: {cat0.name} "
                   f"({d0.confidence:.0%} de confiança).",
            data={"count": len(group), "total": total, "category_id": cat0.id, "merchant_id": mid,
                  "confidence": round(sum(g[2].confidence for g in group) / len(group), 3),
                  "tx_ids": [g[0].id for g in group][:200]}))
    s.flush()
    return {"events": len(decided), "transfers": len(transfer_links), "card_links": len(card_links),
            "review_candidates": review_candidates, "counts": dict(counts),
            "classificador": {k: model_info.get(k) for k in ("habilitado", "amostras", "reclassificados", "confirmados")}}


def _decide(tx: TxView, o: EventOverride | None, rules, structural: dict[str, Decision], m: Merchant | None,
            pmap: dict, cats: dict, hits: Counter) -> Decision:
    paired = structural.get(tx.id)
    if paired and paired.rule_id in (SUPERSEDED, "pending:stale") and not (o and (o.category_id or o.event_type)):
        return paired
    if paired and paired.event_type == EventType.INTERNAL_TRANSFER:
        # as duas pontas estão em contas conectadas: dinheiro só mudou de bolso. Um ajuste/regra que dizia
        # "receita" (feito quando a origem não estava conectada) contaria a receita duas vezes; vale a conciliação.
        r = None if o and (o.category_id or o.event_type) else match_rule(tx, rules, m.id if m else None)
        forced = (o and (o.category_id or o.event_type) and (o.event_type or "") != EventType.INTERNAL_TRANSFER) \
            or (r is not None and r.event_type != EventType.INTERNAL_TRANSFER)
        if forced:
            return Decision(paired.category_id, paired.event_type, paired.rule_source, paired.rule_id,
                            paired.confidence, review=[*paired.review, "override_superseded"])
        return paired
    if o and (o.category_id or o.event_type):
        return Decision(o.category_id, o.event_type, "manual", f"override:{o.id}", 1.0)
    r = match_rule(tx, rules, m.id if m else None)
    if r:
        hits[r.id] += 1
        return Decision(r.category_id, r.event_type, "rule", f"rule:{r.id}", r.confidence)
    if tx.id in structural:
        return structural[tx.id]
    # lançamento de cartão que ficou "pendente" muito depois da data e nunca entrou numa fatura (parcela
    # cancelada/estornada pelo banco, mas que o Open Finance continua enviando): fora do resultado
    if tx.status == "PENDING" and tx.account_type == "CREDIT" and (today_brt() - tx.date).days > STALE_PENDING_DAYS:
        return Decision("pat.ignorar", "IGNORE", "structural", "pending:stale", 0.9, review=["pending_stale"])
    if m and m.default_category_id and m.default_category_id in cats:
        mcat = cats[m.default_category_id]
        # categoria de receita do comerciante só vale para entradas (Pix enviado a ele não é "receita negativa")
        if not (mcat.nature == "receita" and tx.flow < 0) \
                and not (tx.account_type == "CREDIT" and tx.flow < 0 and m.default_category_id.startswith("terceiros")):
            return Decision(m.default_category_id, None, "merchant", f"merchant:{m.id}",
                            0.85 if m.category_origin == "user" else 0.75)
    mapped = pmap.get(tx.pluggy_cat or "")
    is_card_purchase = tx.account_type == "CREDIT" and tx.flow < 0
    # tag de pedágio no cartão é transporte/pedágio, nunca transferência a terceiros
    if is_card_purchase and TOLL_TAG_RE.search(f"{norm(tx.text)} {norm(tx.party_name)}"):
        return Decision("transporte.estacionamento", "EXPENSE", "heuristic", "keyword:toll_tag", 0.85)
    # compra no cartão nunca é Pix/transferência a pessoa física, mesmo que a Pluggy diga "Transferências"
    card_transfer_noise = bool(is_card_purchase and mapped and mapped[0].startswith("terceiros"))
    if card_transfer_noise:
        mapped = None
    # no cartão não existe aporte/resgate/transferência: categoria patrimonial da Pluggy ali é ruído
    if mapped and tx.account_type == "CREDIT" and cats.get(mapped[0]) is not None \
            and cats[mapped[0]].nature == "patrimonial" and mapped[0] != "pat.fatura":
        mapped = None
    # ramo do estabelecimento pelo CNAE do CNPJ (Pluggy ou consulta pública): sinal de despesa, nunca de receita
    cn = cnae_category(tx.merchant_cnae or (m.cnae if m else None))
    # estorno/crédito no cartão: nunca é receita; reduz a despesa da categoria de origem
    if tx.flow > 0 and (tx.account_type == "CREDIT" or ESTORNO_RE.search(tx.text)):
        kw = keyword_category(tx, direction="out")
        if kw:
            return Decision(kw[0], "REFUND", "heuristic", f"refund:{kw[0]}", kw[1])
        if cn:
            return Decision(cn[0], "REFUND", "heuristic", f"refund:cnae:{cn[2]}", cn[1])
        if mapped and cats.get(mapped[0]) is not None and cats[mapped[0]].nature == "despesa" \
                and not mapped[0].startswith("terceiros"):
            return Decision(mapped[0], "REFUND", "pluggy_map", f"refund:pluggy:{tx.pluggy_cat}", mapped[1])
        if mapped and mapped[0].startswith("finrec"):
            return Decision(mapped[0], None, "pluggy_map", f"pluggy:{tx.pluggy_cat}", mapped[1])
        return Decision("compras.diversos", "REFUND", "default", "refund:generic", 0.4)
    kw = keyword_category(tx)
    mcc = MCC_MAP.get(tx.mcc) if tx.mcc and tx.flow < 0 and tx.account_type == "CREDIT" else None
    # sinais mais específicos vencem empates: palavra-chave da marca > CNAE do estabelecimento > MCC do cartão
    best = _best_signal([(kw, f"keyword:{kw[0]}" if kw else None),
                         ((cn[0], cn[1]) if cn and tx.flow < 0 else None, f"cnae:{cn[2]}" if cn else None),
                         (mcc, f"mcc:{tx.mcc}")])
    if mapped:
        cat_id, conf = mapped
        # Pix/TED recebido classificado como "transferência a terceiros" → recebimento a classificar
        if cat_id.startswith("terceiros") and tx.flow > 0:
            cat_id, conf = "rec.pix_terceiros", 0.4
        # crédito em "Empréstimos e financiamentos" é dinheiro emprestado entrando, não juros negativos nem receita
        elif tx.flow > 0 and tx.pluggy_cat == "02000000":
            cat_id = "pat.emprestimo_in"
        elif cat_id == "terceiros.pf" and tx.party_doc and len(tx.party_doc) == 14:
            cat_id = "terceiros.pj"
        # ...e todos eles vencem a categoria (genérica) da Pluggy no empate
        if best and best[0][1] >= conf:
            return Decision(best[0][0], None, "heuristic", best[1], best[0][1])
        return Decision(cat_id, None, "pluggy_map", f"pluggy:{tx.pluggy_cat}", conf)
    if best:
        return Decision(best[0][0], None, "heuristic", best[1], best[0][1])
    if card_transfer_noise:
        return Decision("compras.diversos", "EXPENSE", "default", "card_purchase:generic", 0.3)
    if tx.flow > 0 and tx.account_type == "BANK":
        return Decision("rec.pix_terceiros", None, "default", None, 0.2)
    return Decision("nc", None, "default", None, 0.1)


def _best_signal(signals: list[tuple[tuple[str, float] | None, str | None]]):
    """((categoria, confiança), rule_id) do sinal mais confiante; empate fica com o primeiro da lista."""
    best = None
    for sig, rid in signals:
        if sig and (best is None or sig[1] > best[0][1]):
            best = (sig, rid)
    return best


MIRROR_SOURCES = {"merchant", "pluggy_map", "heuristic", "default", "modelo"}


def _mirror_refunds(decided: dict, cats: dict, own_docs: set[str]) -> None:
    """Reembolso espelho: Pix de pessoa física com o MESMO valor quebrado (com centavos) de uma despesa sua
    dos 45 dias anteriores é reembolso daquela despesa (ex.: alguém te devolve a assinatura que você paga).
    Vira REFUND na categoria da despesa. Não mexe em ajuste manual, regra ou conciliação estrutural."""
    expenses = []
    for tx, d, _, _ in decided.values():
        cat = cats.get(d.category_id or "")
        if tx.removed or tx.flow >= 0 or cat is None or cat.nature != "despesa" or (cat.id or "").startswith("terceiros"):
            continue
        if d.event_type not in (None, EventType.EXPENSE):
            continue
        expenses.append(tx)
    expenses.sort(key=lambda t: t.date)
    used: set[str] = set()
    for tx_id, (tx, d, m, o) in list(decided.items()):
        doc = tx.counterparty_doc or ""
        if tx.removed or tx.flow <= 0 or tx.account_type != "BANK" or d.rule_source not in MIRROR_SOURCES:
            continue
        if len(doc) != 11 or doc in own_docs or round(tx.flow * 100) % 100 == 0:
            continue
        best = None
        for e in expenses:
            if e.id in used or abs(abs(e.flow) - tx.flow) > 0.05:
                continue
            gap = (tx.date - e.date).days
            if -3 <= gap <= 45 and (best is None or abs(gap) < abs((tx.date - best.date).days)):
                best = e
        if best is None:
            continue
        used.add(best.id)
        exp_cat = decided[best.id][1].category_id
        decided[tx_id] = (tx, Decision(exp_cat, EventType.REFUND, "structural", f"mirror:{best.id}", 0.8,
                                       merchant_id=d.merchant_id), m, o)


GROUPABLE = {"pix_pf_out", "pix_in_unknown", "low_confidence", "uncategorized"}
_TITLES = {
    "uncategorized": "Sem categoria",
    "low_confidence": "Categoria incerta",
    "pix_pf_out": "Pix para pessoa física — despesa, reembolso ou empréstimo?",
    "pix_in_unknown": "Recebimento de terceiro — receita ou reembolso?",
    "card_payment_unmatched": "Pagamento de fatura sem correspondência no cartão",
    "card_not_connected": "Pagamento de cartão não conectado (tratado como despesa)",
    "override_superseded": "Ajuste manual substituído: a conta de origem agora está conectada",
    "pending_stale": "Lançamento pendente antigo fora de fatura (ignorado)",
}


def _event_review(reason: str, tx: TxView, cat: Category, d: Decision) -> ReviewCandidate:
    who = tx.party_name or tx.description
    sev = "warn" if reason in ("uncategorized", "card_payment_unmatched", "card_not_connected",
                               "override_superseded") else "info"
    if reason == "override_superseded":
        return ReviewCandidate(
            fingerprint=f"tx:{tx.id}:{reason}", kind=reason, severity=sev, entity_type="transaction",
            entity_id=tx.id, title=f"{tx.description.split('|')[-1].strip()}: {fmt_brl(tx.flow)} em {tx.date:%d/%m/%Y}",
            detail="Você tinha classificado esta entrada manualmente (ex.: como receita) quando a conta de origem não "
                   "estava conectada. Agora as duas pontas aparecem e o valor é transferência entre suas contas. "
                   "Classifique o crédito original na conta de origem.",
            data={"date": tx.date.isoformat(), "amount": tx.flow, "category_id": cat.id, "confidence": d.confidence})
    return ReviewCandidate(
        fingerprint=f"tx:{tx.id}:{reason}", kind=reason, severity=sev, entity_type="transaction",
        entity_id=tx.id, title=f"{who}: {fmt_brl(tx.flow)} em {tx.date:%d/%m/%Y}",
        detail=f"{tx.description}. Sugestão atual: {cat.name} ({d.confidence:.0%} de confiança).",
        data={"date": tx.date.isoformat(), "amount": tx.flow, "category_id": cat.id, "confidence": d.confidence})
