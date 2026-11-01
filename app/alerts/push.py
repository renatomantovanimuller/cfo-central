"""Notificação no celular por Web Push (o padrão dos navegadores), sem app extra nem porta aberta.

O celular abre o CFO Central pelo endereço do Tailscale, aceita as notificações e o navegador devolve um endereço de
entrega do serviço de push do próprio sistema (Google no Android, Apple no iPhone). O servidor envia a mensagem
cifrada de ponta a ponta para esse endereço (RFC 8291): o serviço de push só repassa, não lê o conteúdo.
Nada entra pela internet até o PC; o envio é uma conexão de saída.

No iPhone, o Web Push só funciona com o app instalado na Tela de Início (Compartilhar › Adicionar à Tela de Início).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging

from sqlalchemy.orm import Session

from app.models import AppSetting, NotificationLog
from app.utils.time import utcnow

log = logging.getLogger(__name__)
KEYS = "webpush_vapid"
SUBS = "webpush_inscricoes"
CONTACT = "mailto:cfo-central@localhost"


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _setting(s: Session, key: str):
    row = s.get(AppSetting, key)
    return row.value if row else None


def _put(s: Session, key: str, value) -> None:
    row = s.get(AppSetting, key)
    if row is None:
        s.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    s.flush()


def vapid(s: Session) -> dict:
    """Par de chaves do servidor (VAPID), criado uma vez e guardado no banco local."""
    keys = _setting(s, KEYS)
    if keys and keys.get("private_pem") and keys.get("public_key"):
        return keys
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid02
    v = Vapid02()
    v.generate_keys()
    pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    keys = {"private_pem": v.private_pem().decode(), "public_key": _b64url(pub), "criado_em": utcnow().isoformat()}
    _put(s, KEYS, keys)
    return keys


def sub_id(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()[:12]


def subscriptions(s: Session) -> list[dict]:
    return list(_setting(s, SUBS) or [])


def _origin(endpoint: str) -> str:
    host = endpoint.split("/")[2] if endpoint.count("/") >= 2 else endpoint
    if "google" in host:
        return "Android / Chrome"
    if "apple" in host:
        return "iPhone / Safari"
    if "mozilla" in host:
        return "Firefox"
    if "windows" in host or "notify.windows" in host:
        return "Edge / Windows"
    return host


def subscribe(s: Session, sub: dict, label: str | None = None) -> dict:
    ep = (sub or {}).get("endpoint") or ""
    keys = (sub or {}).get("keys") or {}
    if not ep.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("inscrição inválida")
    subs = [x for x in subscriptions(s) if x["endpoint"] != ep]
    subs.append({"endpoint": ep, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]},
                 "nome": (label or _origin(ep))[:60], "criado_em": utcnow().isoformat(), "ultimo_ok": None, "ultimo_erro": None})
    _put(s, SUBS, subs)
    return public(s)


def unsubscribe(s: Session, ident: str) -> dict:
    _put(s, SUBS, [x for x in subscriptions(s) if sub_id(x["endpoint"]) != ident and x["endpoint"] != ident])
    return public(s)


def public(s: Session) -> dict:
    return {"public_key": vapid(s)["public_key"],
            "aparelhos": [{"id": sub_id(x["endpoint"]), "nome": x.get("nome"), "origem": _origin(x["endpoint"]),
                           "criado_em": x.get("criado_em"), "ultimo_ok": x.get("ultimo_ok"), "ultimo_erro": x.get("ultimo_erro")}
                          for x in subscriptions(s)]}


def enabled(s: Session) -> bool:
    return bool(subscriptions(s))


def send(s: Session, title: str, body: str, url: str = "/", tag: str | None = None, fingerprint: str | None = None) -> dict:
    """Envia para todos os aparelhos inscritos. Inscrição que o serviço diz não existir mais (404/410) é removida."""
    subs = subscriptions(s)
    if not subs:
        return {"sent": 0, "reason": "nenhum aparelho inscrito"}
    from py_vapid import Vapid02
    from pywebpush import WebPushException, webpush
    key = Vapid02.from_pem(vapid(s)["private_pem"].encode())
    payload = json.dumps({"title": title, "body": body[:400], "url": url, "tag": tag or fingerprint or title}, ensure_ascii=False)
    ok, keep, errors = 0, [], []
    now = utcnow().isoformat()
    for x in subs:
        try:
            webpush({"endpoint": x["endpoint"], "keys": x["keys"]}, data=payload, vapid_private_key=key,
                    vapid_claims={"sub": CONTACT}, ttl=24 * 3600, timeout=20)
            ok += 1
            keep.append({**x, "ultimo_ok": now, "ultimo_erro": None})
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            if code in (404, 410):
                log.info("inscrição de push expirada removida: %s", sub_id(x["endpoint"]))
                continue
            errors.append(f"{x.get('nome')}: {code or ''} {str(e)[:120]}")
            keep.append({**x, "ultimo_erro": f"{now} {code or ''} {str(e)[:160]}"})
        except Exception as e:  # noqa: BLE001 — rede: guarda o motivo e segue para o próximo aparelho
            errors.append(f"{x.get('nome')}: {e.__class__.__name__}")
            keep.append({**x, "ultimo_erro": f"{now} {e.__class__.__name__}: {str(e)[:160]}"})
    _put(s, SUBS, keep)
    s.add(NotificationLog(channel="push", fingerprint=fingerprint or f"push:{now}", subject=title[:300],
                          status="sent" if ok else "error", error="; ".join(errors)[:500] or None))
    return {"sent": ok, "errors": errors}
