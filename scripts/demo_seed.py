"""Popula o banco com dados de demonstração (cliente Pluggy falso) — útil para testar a UI sem dados reais.

    DATABASE_URL=... python -m scripts.demo_seed
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth.security import has_users, set_password  # noqa: E402
from app.database.migrate import migrate  # noqa: E402
from app.database.session import session_factory  # noqa: E402
from app.ingestion.pluggy_sync import sync_item  # noqa: E402
from app.services.pipeline import pipeline  # noqa: E402
from tests.fixtures.fake_pluggy import ITEM_ID, FakePluggyClient  # noqa: E402

migrate()
sync_item(session_factory(), FakePluggyClient(), ITEM_ID, full=True, trigger="demo")
if "--no-market" not in sys.argv:
    print(pipeline.market("demo").get("errors"))
print(pipeline.post_process("demo")["counts"])
if not has_users():
    set_password("demo", "demo12345")
    print("usuário demo / senha demo12345")
