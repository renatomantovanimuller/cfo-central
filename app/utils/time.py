from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

BRT = timezone(timedelta(hours=-3))  # Brasil sem horário de verão desde 2019


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today_brt() -> date:
    return datetime.now(BRT).date()


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    if len(value) == 10:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def local_date(value: str | None) -> date | None:
    """Data civil em Brasília a partir de um ISO da Pluggy (que vem em UTC)."""
    if not value:
        return None
    if len(value) == 10:
        return date.fromisoformat(value)
    dt = parse_dt(value)
    return dt.astimezone(BRT).date() if dt else None


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_add(ym: str, n: int) -> str:
    y, m = map(int, ym.split("-"))
    m += n
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def month_bounds(ym: str) -> tuple[date, date]:
    y, m = map(int, ym.split("-"))
    start = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return start, nxt - timedelta(days=1)
