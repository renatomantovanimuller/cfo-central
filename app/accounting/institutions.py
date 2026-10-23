"""Nome da instituição de cada conexão: fonte única para Balanço, Carteira, IR, revisões, saúde e exportação.

Ordem: apelido dado pelo usuário em Conexões → nome do conector (quando não é um agregador como o MeuPluggy) →
nome da conta corrente da conexão (o banco de verdade, no caso do agregador) → nome do conector → id curto.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

AGGREGATOR_RE = re.compile(r"pluggy", re.I)
_SUFFIX_RE = re.compile(r"\s*(-|–|,).*$|\s+(s\.?\s?a\.?|ltda|institui[cç][aã]o de pagamento)\b.*$", re.I)


def _from_account(name: str | None) -> str | None:
    """'NU PAGAMENTOS S.A. - INSTITUIÇÃO DE PAGAMENTO' → 'Nu Pagamentos'."""
    n = _SUFFIX_RE.sub("", (name or "").strip()).strip()
    if not n:
        return None
    return n.title() if n.isupper() or n.islower() else n


def institution_labels(s: Session) -> dict[str, str]:
    from app.models import Account, Institution, Item
    insts = {i.id: i.name for i in s.scalars(select(Institution))}
    by_item: dict[str, list] = {}
    for a in s.scalars(select(Account).where(Account.removed_at.is_(None)).order_by(Account.type)):
        by_item.setdefault(a.item_id, []).append(a)  # BANK antes de CREDIT
    out: dict[str, str] = {}
    for it in s.scalars(select(Item)):
        conn = insts.get(it.institution_id)
        if it.nickname:
            out[it.id] = it.nickname
        elif conn and not AGGREGATOR_RE.search(conn):
            out[it.id] = conn
        else:
            accs = by_item.get(it.id, [])
            out[it.id] = next((lbl for a in accs if (lbl := _from_account(a.marketing_name or a.name))), None) \
                or conn or it.id[:8]
    return out


def is_aggregator_label(label: str | None) -> bool:
    return bool(label and AGGREGATOR_RE.search(label))
