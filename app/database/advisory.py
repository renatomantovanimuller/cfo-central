"""Lock entre processos via pg_advisory_lock (Postgres). No SQLite é no-op.

Ordem obrigatória para evitar deadlock: locks de thread (Pipeline._lock → _ledger_lock)
primeiro, advisory lock por último. O lock é reentrante dentro da mesma thread.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import text

from app.database.session import get_engine

log = logging.getLogger(__name__)

PIPELINE_LOCK_KEY = 0x43464F43  # "CFOC": chave fixa do pipeline (sync/post_process/rebuild)
DEFAULT_TIMEOUT_S = 900.0
POLL_INTERVAL_S = 1.0
LOG_EVERY_S = 15.0

_local = threading.local()


@contextmanager
def advisory_lock(key: int = PIPELINE_LOCK_KEY, timeout: float = DEFAULT_TIMEOUT_S,
                  poll: float = POLL_INTERVAL_S) -> Iterator[bool]:
    """Segura o advisory lock numa conexão dedicada; libera no finally. Rende True se é Postgres."""
    engine = get_engine()
    if engine.dialect.name != "postgresql" or getattr(_local, "depth", 0) > 0:
        # SQLite: no-op; reentrada na mesma thread: já temos o lock
        _local.depth = getattr(_local, "depth", 0) + 1
        try:
            yield engine.dialect.name == "postgresql"
        finally:
            _local.depth -= 1
        return

    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        start = time.monotonic()
        last_log = start
        while not conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar():
            waited = time.monotonic() - start
            if waited >= timeout:
                raise TimeoutError(f"advisory lock {key} ocupado por outro processo há {waited:.0f}s")
            if time.monotonic() - last_log >= LOG_EVERY_S:
                log.warning("aguardando advisory lock %s (outro processo rodando sync/rebuild) há %.0fs", key, waited)
                last_log = time.monotonic()
            time.sleep(poll)
        _local.depth = 1
        try:
            yield True
        finally:
            _local.depth = 0
            try:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            except Exception:  # fechar a conexão libera o lock de qualquer forma
                log.exception("falha ao liberar advisory lock %s", key)
    finally:
        conn.close()
