"""Consulta pública do CNPJ (dados abertos da Receita Federal, via BrasilAPI) para obter o CNAE do comerciante.

Opcional e desligada por padrão: envia a um serviço externo os CNPJs dos estabelecimentos em que você compra
(nunca CPFs nem valores). Cada CNPJ é consultado uma vez; falhas são tentadas de novo depois de RETRY_DAYS.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.categorization.cnae import norm_cnae
from app.models import Merchant
from app.utils.time import utcnow

log = logging.getLogger(__name__)
API = "https://brasilapi.com.br/api/cnpj/v1/{}"
SETTING = "enriquecimento"
RETRY_DAYS = 90
PAUSE = 0.35  # gentileza com o serviço público


def enabled(s: Session) -> bool:
    from app.analytics.plano import get_setting
    return bool(get_setting(s, SETTING, {"cnpj": False}).get("cnpj"))


def _pending_q():
    stale = utcnow() - timedelta(days=RETRY_DAYS)
    return select(Merchant).where(Merchant.cnpj.is_not(None), func.length(Merchant.cnpj) == 14,
                                  Merchant.cnae.is_(None),
                                  or_(Merchant.enriched_at.is_(None), Merchant.enriched_at < stale))


def status(s: Session) -> dict:
    with_doc = s.scalar(select(func.count()).select_from(Merchant).where(func.length(Merchant.cnpj) == 14)) or 0
    with_cnae = s.scalar(select(func.count()).select_from(Merchant).where(Merchant.cnae.is_not(None))) or 0
    pending = s.scalar(select(func.count()).select_from(_pending_q().subquery())) or 0
    return {"habilitado": enabled(s), "com_cnpj": with_doc, "com_cnae": with_cnae, "pendentes": pending}


def _looks_like_doc(name: str | None, doc: str) -> bool:
    return not name or name.replace(".", "").replace("/", "").replace("-", "").strip() == doc


def enrich_merchants(s: Session, limit: int = 40, client: httpx.Client | None = None) -> dict:
    """Consulta até `limit` CNPJs ainda sem CNAE. Para no primeiro limite de taxa (429) ou falha de rede."""
    out = {"consultados": 0, "com_cnae": 0, "nao_encontrados": 0, "erro": None}
    own = client is None
    client = client or httpx.Client(timeout=8.0, headers={"User-Agent": "cfo-central (uso pessoal)"})
    try:
        for m in s.scalars(_pending_q().order_by(Merchant.id).limit(limit)):
            try:
                r = client.get(API.format(m.cnpj))
            except httpx.HTTPError as exc:
                out["erro"] = f"rede: {exc.__class__.__name__}"
                break
            if r.status_code == 429:
                out["erro"] = "limite de consultas do serviço; continua na próxima sincronização"
                break
            out["consultados"] += 1
            m.enriched_at = utcnow()
            if r.status_code == 200:
                data = r.json()
                code = norm_cnae(data.get("cnae_fiscal"))
                if code:
                    m.cnae, m.cnae_source = code, "receita"
                    m.cnae_desc = (data.get("cnae_fiscal_descricao") or "")[:200] or None
                    out["com_cnae"] += 1
                name = data.get("nome_fantasia") or data.get("razao_social")
                if name and _looks_like_doc(m.canonical_name, m.cnpj):
                    m.canonical_name = name.strip().title()[:200]
            elif r.status_code in (400, 404):
                out["nao_encontrados"] += 1
            if PAUSE:
                time.sleep(PAUSE)
    finally:
        if own:
            client.close()
    s.flush()
    return out
