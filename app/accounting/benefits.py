"""Benefícios de alimentação (VR/VA) que não chegam pelo Open Finance.

Os cartões de benefício (Pluxee, Alelo, VR, Ticket, Caju, Flash…) não têm conector na Pluggy hoje. Enquanto isso,
o crédito mensal é gerado a partir do que você informou (valor, dia do crédito e histórico de reajustes) e entra
no razão como dois eventos do mesmo mês:

* crédito: receita em "Benefícios e auxílios" (+valor);
* consumo: despesa em "Alimentação › Pago com VR/VA" (−valor).

Premissa do consumo: o saldo do cartão de benefício é gasto em alimentação no próprio mês do crédito. O resultado do
mês não muda (os dois eventos se anulam); o que muda é a leitura: a receita bruta inclui o benefício e o gasto com
alimentação passa a mostrar o que é pago com ele. Nada disso mexe em saldo de conta, fluxo de caixa ou patrimônio.

Se a Pluggy passar a ter conector para o seu cartão de benefício, `pluggy_benefit_connectors` avisa; ao conectar,
desligue o benefício informado aqui para não contar em dobro.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import AppSetting, FinancialEvent
from app.utils.time import month_add, month_key, today_brt, utcnow

SETTING = "beneficios"
PLUGGY_CACHE = "beneficios_pluggy"
SOURCE = "benefit"
CREDIT_CAT = "rec.beneficios"
USE_CAT = "alimentacao.beneficio"
CHECK_EVERY = timedelta(days=7)
# nomes de emissores de benefício alimentação/refeição/multibenefício
BENEFIT_RE = re.compile(r"alelo|pluxee|sodexo|ticket|\bvr\b|vr benef|caju|flash|swile|ben visa|valecard|"
                        r"green ?card|up brasil|verocard|ifood benef|benefic", re.I)


def _valid_month(v: str | None) -> bool:
    return bool(v) and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v) is not None


def normalize(cfg: dict | None) -> dict:
    """Valida e ordena a configuração; descarta entradas incompletas em vez de gerar eventos errados."""
    itens = []
    for i, it in enumerate((cfg or {}).get("itens", [])):
        valores = sorted([{"desde": v["desde"], "valor": round(float(v["valor"]), 2)}
                          for v in it.get("valores", []) if _valid_month(v.get("desde")) and v.get("valor") is not None
                          and float(v["valor"]) >= 0], key=lambda v: v["desde"])
        if not valores:
            continue
        dia = int(it.get("dia") or 1)
        itens.append({
            "id": re.sub(r"[^a-z0-9_-]", "", str(it.get("id") or f"b{i + 1}").lower())[:16] or f"b{i + 1}",
            "nome": (it.get("nome") or "Vale-refeição").strip()[:60],
            "fornecedor": (it.get("fornecedor") or "").strip()[:60] or None,
            "dia": min(max(dia, 1), 28),
            "valores": valores,
            "ate": it.get("ate") if _valid_month(it.get("ate")) else None,
            "ativo": bool(it.get("ativo", True)),
        })
    return {"itens": itens}


def get_config(s: Session) -> dict:
    row = s.get(AppSetting, SETTING)
    return normalize(row.value if row else None)


def save_config(s: Session, cfg: dict) -> dict:
    clean = normalize(cfg)
    row = s.get(AppSetting, SETTING)
    if row is None:
        s.add(AppSetting(key=SETTING, value=clean))
    else:
        row.value = clean
    s.flush()
    return clean


def monthly_credits(cfg: dict, today: date | None = None) -> list[dict]:
    """Um crédito por benefício e mês, do primeiro valor até hoje (o mês atual só depois do dia do crédito)."""
    today = today or today_brt()
    cur = month_key(today)
    out = []
    for it in cfg["itens"]:
        if not it["ativo"]:
            continue
        m, last = it["valores"][0]["desde"], min(it["ate"] or cur, cur)
        while m <= last:
            valor = next(v["valor"] for v in reversed(it["valores"]) if v["desde"] <= m)
            y, mo = int(m[:4]), int(m[5:])
            d = date(y, mo, it["dia"])
            if valor > 0 and d <= today:
                out.append({"id": it["id"], "nome": it["nome"], "fornecedor": it["fornecedor"], "month": m,
                            "date": d, "valor": valor})
            m = month_add(m, 1)
    return out


def sync_benefit_events(s: Session, today: date | None = None) -> int:
    """Recria os eventos de benefício a partir da configuração. Idempotente; chamado a cada reconstrução do razão."""
    s.execute(delete(FinancialEvent).where(FinancialEvent.source_type == SOURCE))
    now = utcnow()
    n = 0
    for c in monthly_credits(get_config(s), today):
        base = dict(source_type=SOURCE, split_seq=0, account_id=None, item_id=None, competence_date=c["date"],
                    cash_date=None, merchant_id=None, counterparty=c["fornecedor"], rule_source="benefit",
                    rule_id=f"benefit:{c['id']}", needs_review=False, is_pending=False, is_removed=False,
                    built_at=now, tags=["beneficio"])
        s.add(FinancialEvent(source_id=f"benef:{c['id']}:{c['month']}:credito", amount=c["valor"],
                             event_type="INCOME", category_id=CREDIT_CAT, description=f"Crédito {c['nome']}",
                             confidence=1.0, is_inferred=False, **base))
        s.add(FinancialEvent(source_id=f"benef:{c['id']}:{c['month']}:consumo", amount=-c["valor"],
                             event_type="EXPENSE", category_id=USE_CAT,
                             description=f"Consumo {c['nome']} (igual ao crédito do mês)",
                             confidence=0.9, is_inferred=True,
                             note="Premissa: o saldo do benefício é gasto em alimentação no mês do crédito.", **base))
        n += 2
    s.flush()
    return n


def pluggy_benefit_connectors(s: Session, client, refresh: bool = False) -> dict:
    """Procura, na lista viva de conectores da Pluggy, algum emissor de benefício. Guarda o resultado por 7 dias."""
    row = s.get(AppSetting, PLUGGY_CACHE)
    cached = row.value if row else None
    if cached and not refresh:
        try:
            if datetime.fromisoformat(cached["verificado_em"]) > utcnow() - CHECK_EVERY:
                return cached
        except (KeyError, ValueError, TypeError):
            pass
    try:
        data = client.request("GET", "/connectors", params={"countries": "BR"}) or {}
        results = data.get("results", data if isinstance(data, list) else [])
        found = [{"id": c.get("id"), "nome": c.get("name"), "tipo": c.get("type"), "produtos": c.get("products")}
                 for c in results if not c.get("isSandbox") and BENEFIT_RE.search(c.get("name") or "")
                 and (c.get("type") or "").upper() not in ("INVESTMENT",)]
        res = {"verificado_em": utcnow().isoformat(), "total_conectores": len(results), "encontrados": found, "erro": None}
    except Exception as exc:  # noqa: BLE001 — sem rede/credencial: a tela mostra o motivo, a última resposta continua valendo
        res = {**(cached or {"encontrados": [], "total_conectores": None}), "verificado_em": utcnow().isoformat(),
               "erro": f"{exc.__class__.__name__}: {str(exc)[:160]}"}
    if row is None:
        s.add(AppSetting(key=PLUGGY_CACHE, value=res))
    else:
        row.value = res
    s.flush()
    return res


def summary(s: Session, today: date | None = None) -> dict:
    cfg = get_config(s)
    credits = monthly_credits(cfg, today)
    cur = month_key(today or today_brt())
    last12 = [c for c in credits if c["month"] > month_add(cur, -12)]
    return {"config": cfg, "creditos_12m": round(sum(c["valor"] for c in last12), 2),
            "meses": len({c["month"] for c in credits}),
            "ultimos": [{**c, "date": c["date"].isoformat()} for c in credits[-6:][::-1]],
            "premissa": "O consumo é estimado igual ao crédito do mês; o resultado do mês não muda, "
                        "só a receita bruta e o gasto com alimentação."}
