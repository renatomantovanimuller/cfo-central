"""Aplica o schema: Alembic (upgrade head) no Postgres; create_all em SQLite (dev/testes)."""
from __future__ import annotations

import logging
from pathlib import Path

from app.config.settings import get_settings
from app.database.session import Base, get_engine, session_scope

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger(__name__)


def migrate() -> None:
    import app.models  # noqa: F401 — registra tabelas

    url = get_settings().database_url
    engine = get_engine()
    if url.startswith("sqlite") or not (ROOT / "alembic.ini").exists():
        Base.metadata.create_all(engine)
    else:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.attributes["configure_logger"] = False
        cfg.set_main_option("script_location", str(ROOT / "migrations"))
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        command.upgrade(cfg, "head")
    from app.categorization.chart import seed_chart
    with session_scope() as s:
        seed_chart(s)
