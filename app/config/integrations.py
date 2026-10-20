"""Credenciais configuráveis pela interface (Pluggy e e-mail), guardadas em app_settings.

O que o usuário salva na tela de Configurações vale por cima do .env: assim ninguém precisa editar arquivo
nem reiniciar o app. Os valores ficam no banco local, como o .env fica no disco local.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.config.settings import get_settings

KEY = "integracoes"
FIELDS = ("pluggy_client_id", "pluggy_client_secret", "smtp_user", "smtp_password", "alert_email_to")
SECRETS = {"pluggy_client_secret", "smtp_password"}
_ENV: dict[str, str] = {}  # valores originais do .env, para saber a origem e poder voltar a eles


def _stored(s: Session) -> dict:
    from app.models import AppSetting
    row = s.get(AppSetting, KEY)
    return dict(row.value or {}) if row else {}


def apply(s: Session) -> None:
    """Sobrepõe as credenciais salvas pela interface às do .env e descarta o cliente Pluggy em cache."""
    st = get_settings()
    if not _ENV:
        _ENV.update({f: getattr(st, f) for f in FIELDS})
    stored = _stored(s)
    before = (st.pluggy_client_id, st.pluggy_client_secret)
    for f in FIELDS:
        setattr(st, f, stored.get(f) or _ENV.get(f, ""))
    if (st.pluggy_client_id, st.pluggy_client_secret) != before:
        from app.services.pipeline import pipeline
        pipeline._client = None


def save(s: Session, values: dict) -> None:
    """Grava só os campos enviados; string vazia apaga (volta ao .env). Segredo omitido (None) fica como está."""
    from app.models import AppSetting
    row = s.get(AppSetting, KEY) or AppSetting(key=KEY, value={})
    cur = dict(row.value or {})
    for f in FIELDS:
        if f in values and values[f] is not None:
            v = str(values[f]).strip()
            if v:
                cur[f] = v
            else:
                cur.pop(f, None)
    row.value = cur
    s.add(row)
    s.flush()
    apply(s)


def public_view(s: Session) -> dict:
    st = get_settings()
    stored = _stored(s)

    def origin(f: str) -> str | None:
        return "app" if stored.get(f) else ("env" if _ENV.get(f) else None)

    return {
        "pluggy": {"client_id": st.pluggy_client_id, "has_secret": bool(st.pluggy_client_secret),
                   "configured": bool(st.pluggy_client_id and st.pluggy_client_secret),
                   "origin": origin("pluggy_client_id")},
        "email": {"smtp_user": st.smtp_user, "has_password": bool(st.smtp_password), "alert_email_to": st.alert_email_to,
                  "configured": st.email_enabled, "host": st.smtp_host, "port": st.smtp_port,
                  "origin": origin("smtp_user")},
    }
