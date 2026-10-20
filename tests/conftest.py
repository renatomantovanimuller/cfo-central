import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_db = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_db}")
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["PLUGGY_CLIENT_ID"] = "x"
os.environ["PLUGGY_CLIENT_SECRET"] = "y"


@pytest.fixture()
def db_reset():
    from app.database.session import Base, get_engine, session_factory
    import app.models  # noqa: F401
    from app.database.migrate import migrate

    engine = get_engine(os.environ["DATABASE_URL"])
    if engine.dialect.name == "postgresql":  # exercita as migrações Alembic de verdade
        from sqlalchemy import text
        with engine.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    else:
        Base.metadata.drop_all(engine)
    migrate()
    return session_factory()


@pytest.fixture()
def synced(db_reset):
    """Banco com uma sincronização completa do cliente falso + razão reconstruído."""
    from app.ingestion.pluggy_sync import sync_item
    from app.services.pipeline import pipeline
    from tests.fixtures.fake_pluggy import ITEM_ID, FakePluggyClient

    client = FakePluggyClient()
    res = sync_item(db_reset, client, ITEM_ID, full=True, trigger="test")
    post = pipeline.post_process("test")
    return {"sf": db_reset, "client": client, "sync": res, "post": post}
