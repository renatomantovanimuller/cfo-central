"""Itens manuais (imóvel, veículo, conta não conectada, dívida informal) com histórico.

Valor numa data = último ponto informado até ela, atualizado pela taxa anual (índice do imóvel, depreciação do
veículo). Antes da data de aquisição o item não existe; sem data de aquisição, antes do primeiro ponto informado
ele também não entra (melhor um degrau no mês do cadastro do que inventar o passado).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session


def record_point(s: Session, m) -> None:
    """Grava (ou substitui) o ponto do histórico na data `as_of` do item."""
    from app.models import ManualAssetValue
    d = m.as_of
    row = s.scalar(select(ManualAssetValue).where(ManualAssetValue.manual_asset_id == m.id, ManualAssetValue.date == d))
    if row is None:
        s.add(ManualAssetValue(manual_asset_id=m.id, date=d, value=m.value))
    else:
        row.value = m.value
    s.flush()


def points_by_asset(s: Session) -> dict[int, list[tuple[date, float]]]:
    from app.models import ManualAssetValue
    out: dict[int, list] = defaultdict(list)
    for v in s.scalars(select(ManualAssetValue).order_by(ManualAssetValue.date)):
        out[v.manual_asset_id].append((v.date, v.value))
    return out


def value_at(m, points: list[tuple[date, float]], d: date) -> float:
    pts = sorted(points or [(m.as_of, m.value)])
    if m.acquired_at and d < m.acquired_at:
        return 0.0
    g = m.growth_aa or 0.0
    past = [p for p in pts if p[0] <= d]
    if past:
        pd_, pv = past[-1]
        return pv * (1 + g) ** ((d - pd_).days / 365.25)
    if m.acquired_at:  # entre a aquisição e o primeiro ponto: recua o primeiro valor pela taxa
        pd_, pv = pts[0]
        return pv / (1 + g) ** ((pd_ - d).days / 365.25)
    return 0.0


def manual_net_at(s: Session, d: date) -> float:
    """Ativos − passivos manuais ativos na data `d`."""
    from app.models import ManualAsset
    pts = points_by_asset(s)
    total = 0.0
    for m in s.scalars(select(ManualAsset).where(ManualAsset.active.is_(True))):
        v = value_at(m, pts.get(m.id), d)
        total += v if m.kind == "asset" else -v
    return total
