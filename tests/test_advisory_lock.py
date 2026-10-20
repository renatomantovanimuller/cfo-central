"""Helper de advisory lock: no SQLite é no-op e reentrante."""
from app.database.advisory import advisory_lock


def test_advisory_lock_noop_no_sqlite():
    with advisory_lock() as is_pg:
        assert is_pg is False
        with advisory_lock():  # reentrância não bloqueia
            pass
