"""Curadoria versionada: aplica um arquivo JSON de decisões (apelidos de contas, categorias de comerciantes,
regras e ajustes por lançamento) ao banco, de forma idempotente. Útil para revisar decisões fora da tela,
manter histórico em Git e reaplicar tudo após recriar o banco.

Formato (todas as seções são opcionais):
{
  "accounts":  [{"match": {"type": "BANK", "name_contains": "Nu Pagamentos"}, "nickname": "Nubank · Conta"}],
  "merchants": [{"doc": "12345678901", "category": "saude.consultas", "name": "Clínica Exemplo"}],
  "rules":     [{"name": "...", "field": "description", "operator": "contains", "pattern": "...",
                 "direction": "in", "amount_min": null, "amount_max": 500, "category": "...", "event_type": null,
                 "priority": 50}],
  "overrides": [{"tx_id": "...", "category": "rec.bonus", "event_type": null, "note": "..."}]
}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.categorization.chart import seed_chart
from app.models import (Account, AccountSetting, Category, CategoryRule, EventOverride, EventType, LedgerAudit,
                        Merchant, Transaction)


def _digits(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def apply_curation(s: Session, data: dict) -> dict:
    seed_chart(s)
    cats = set(s.scalars(select(Category.id)))
    report: dict[str, list] = {"accounts": [], "merchants": [], "rules": [], "overrides": [], "skipped": []}

    def check_cat(cid: str | None, where: str) -> bool:
        if cid and cid not in cats:
            report["skipped"].append(f"{where}: categoria inexistente {cid}")
            return False
        return True

    def check_type(et: str | None, where: str) -> bool:
        if et and et not in EventType.ALL:
            report["skipped"].append(f"{where}: tipo inválido {et}")
            return False
        return True

    for a in data.get("accounts", []):
        m = a.get("match", {})
        q = select(Account).where(Account.removed_at.is_(None))
        if m.get("id"):
            q = q.where(Account.id == m["id"])
        if m.get("type"):
            q = q.where(Account.type == m["type"])
        hits = [x for x in s.scalars(q)
                if (m.get("name_contains") or "").lower() in (x.name or "").lower()
                and (not m.get("number_endswith") or (x.number or "").endswith(m["number_endswith"]))]
        if len(hits) != 1:
            report["skipped"].append(f"conta {m}: {len(hits)} correspondências")
            continue
        st = s.get(AccountSetting, hits[0].id) or AccountSetting(account_id=hits[0].id)
        st.nickname = a.get("nickname", st.nickname)
        if "purpose" in a:
            st.purpose = a["purpose"]
        if "include_in_net_worth" in a:
            st.include_in_net_worth = bool(a["include_in_net_worth"])
        s.add(st)
        report["accounts"].append(f"{hits[0].name} → {st.nickname}")

    for mm in data.get("merchants", []):
        doc = _digits(mm.get("doc"))
        if not doc or not check_cat(mm.get("category"), f"comerciante {doc}"):
            continue
        m = s.scalar(select(Merchant).where(Merchant.cnpj == doc))
        if m is None:  # ainda não apareceu nos lançamentos: já fica cadastrado para quando aparecer
            m = Merchant(canonical_name=mm.get("name") or doc, cnpj=doc)
            s.add(m)
        m.default_category_id, m.category_origin = mm.get("category"), "user"
        if mm.get("name"):
            m.canonical_name = mm["name"]
        report["merchants"].append(f"{m.canonical_name} → {mm.get('category')}")

    for r in data.get("rules", []):
        name = r.get("name") or r.get("pattern")
        if not r.get("pattern") or not (r.get("category") or r.get("event_type")):
            report["skipped"].append(f"regra {name}: precisa de padrão e categoria/tipo")
            continue
        if not check_cat(r.get("category"), f"regra {name}") or not check_type(r.get("event_type"), f"regra {name}"):
            continue
        rule = s.scalar(select(CategoryRule).where(CategoryRule.name == name)) or CategoryRule(name=name)
        rule.field, rule.operator, rule.pattern = r.get("field", "description"), r.get("operator", "contains"), r["pattern"]
        rule.direction, rule.amount_min, rule.amount_max = r.get("direction"), r.get("amount_min"), r.get("amount_max")
        rule.category_id, rule.event_type = r.get("category"), r.get("event_type")
        rule.priority, rule.active, rule.origin = r.get("priority", 100), r.get("active", True), "user"
        s.add(rule)
        report["rules"].append(name)

    for o in data.get("overrides", []):
        tid = o.get("tx_id")
        if not tid or not s.get(Transaction, tid):
            report["skipped"].append(f"ajuste {tid}: lançamento não encontrado")
            continue
        if not check_cat(o.get("category"), f"ajuste {tid}") or not check_type(o.get("event_type"), f"ajuste {tid}"):
            continue
        ov = s.scalar(select(EventOverride).where(EventOverride.source_id == tid)) \
            or EventOverride(source_type="transaction", source_id=tid)
        before = (ov.category_id, ov.event_type)
        ov.category_id, ov.event_type = o.get("category"), o.get("event_type")
        if "note" in o:
            ov.note = o["note"]
        s.add(ov)
        if before != (ov.category_id, ov.event_type):
            s.add(LedgerAudit(source_id=tid, field="override", old=str(before),
                              new=str((ov.category_id, ov.event_type)), actor="curadoria", reason="arquivo de curadoria"))
        report["overrides"].append(tid)
    s.flush()
    return report


def apply_curation_file(s: Session, path: str | Path) -> dict:
    return apply_curation(s, json.loads(Path(path).read_text(encoding="utf-8")))
