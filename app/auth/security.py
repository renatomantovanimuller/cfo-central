"""Autenticação local de usuário único: argon2 + cookie de sessão assinado (HttpOnly)."""
from __future__ import annotations

import hashlib
import hmac

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from sqlalchemy import func, select

from app.config.settings import get_settings
from app.database.session import session_scope
from app.models import User
from app.utils.time import utcnow

COOKIE = "cfo_session"
_ph = PasswordHasher()


def _signer() -> TimestampSigner:
    return TimestampSigner(get_settings().secret_key, salt="cfo-session")


def has_users() -> bool:
    with session_scope() as s:
        return bool(s.scalar(select(func.count()).select_from(User)))


def set_password(username: str, password: str) -> None:
    if len(password) < 8:
        raise ValueError("a senha precisa de pelo menos 8 caracteres")
    with session_scope() as s:
        u = s.scalar(select(User).where(User.username == username))
        if u is None:
            u = User(username=username, password_hash=_ph.hash(password))
            s.add(u)
        else:
            u.password_hash = _ph.hash(password)


def authenticate(username: str, password: str) -> bool:
    with session_scope() as s:
        u = s.scalar(select(User).where(User.username == username))
        if u is None:
            _ph.hash(password)  # tempo constante
            return False
        try:
            _ph.verify(u.password_hash, password)
        except VerifyMismatchError:
            return False
        u.last_login_at = utcnow()
        return True


def issue_token(username: str) -> str:
    return _signer().sign(username.encode()).decode()


def read_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _signer().unsign(token, max_age=get_settings().session_hours * 3600).decode()
    except (BadSignature, SignatureExpired):
        return None


INTERNAL_HEADER = "X-CFO-Internal"
_LOCAL = {"127.0.0.1", "::1", "localhost"}


def internal_token() -> str:
    """Credencial de processos do próprio container (ex.: servidor MCP) para chamar a API sem cookie.
    Só vale vinda de 127.0.0.1 dentro do container; a porta publicada no host chega por outro IP."""
    return hmac.new(get_settings().secret_key.encode(), b"cfo-internal-v1", hashlib.sha256).hexdigest()


def require_user(request: Request) -> str:
    tok = request.headers.get(INTERNAL_HEADER)
    if tok and request.client and request.client.host in _LOCAL and hmac.compare_digest(tok, internal_token()):
        return "assistente"
    user = read_token(request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(status_code=401, detail="não autenticado")
    return user


CurrentUser = Depends(require_user)
