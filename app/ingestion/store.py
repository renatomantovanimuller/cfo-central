"""Primitivas de persistência idempotente: payload bruto versionado e upsert com proveniência."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Iterable, Type

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.models import RawPayload, SyncEvent, SyncRun
from app.utils.time import utcnow


def payload_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def store_raw_many(s: Session, entity_type: str, records: list[tuple[str, dict]], item_id: str | None,
                   run_id: int | None) -> dict[str, int]:
    """Grava (ou só marca como visto) cada payload. Retorna {external_id: raw_payload_id}."""
    if not records:
        return {}
    now = utcnow()
    hashed = [(ext, p, payload_hash(p)) for ext, p in records]
    keys = [(entity_type, ext, h) for ext, _, h in hashed]
    existing: dict[tuple[str, str], RawPayload] = {}
    for chunk in _chunks(keys, 400):
        rows = s.scalars(select(RawPayload).where(
            RawPayload.source == "pluggy",
            tuple_(RawPayload.entity_type, RawPayload.external_id, RawPayload.payload_hash).in_(chunk)))
        for r in rows:
            existing[(r.external_id, r.payload_hash)] = r
    out: dict[str, int] = {}
    new_rows = []
    for ext, p, h in hashed:
        r = existing.get((ext, h))
        if r:
            r.last_seen_at = now
            out[ext] = r.id
        else:
            r = RawPayload(source="pluggy", entity_type=entity_type, external_id=ext, item_id=item_id,
                           payload=p, payload_hash=h, first_seen_at=now, last_seen_at=now, run_id=run_id)
            s.add(r)
            new_rows.append((ext, r))
    if new_rows:
        s.flush()
        out.update({ext: r.id for ext, r in new_rows})
    return out


def upsert_rows(s: Session, model: Type, rows: list[dict], raw_ids: dict[str, int] | None = None,
                key: str = "id") -> tuple[int, int]:
    """Upsert por chave natural preservando first_seen_at. Reaparecimento limpa removed_at."""
    if not rows:
        return 0, 0
    now = utcnow()
    pk = getattr(model, key)
    ids = [r[key] for r in rows]
    current = {}
    for chunk in _chunks(ids, 500):
        for obj in s.scalars(select(model).where(pk.in_(chunk))):
            current[getattr(obj, key)] = obj
    has_prov = hasattr(model, "last_seen_at")
    inserted = updated = 0
    for r in rows:
        data = dict(r)
        if raw_ids is not None and has_prov:
            data["raw_payload_id"] = raw_ids.get(str(r[key]))
        obj = current.get(r[key])
        if obj is None:
            if has_prov:
                data.setdefault("first_seen_at", now)
                data["last_seen_at"] = now
            s.add(model(**data))
            inserted += 1
        else:
            for k, v in data.items():
                setattr(obj, k, v)
            if has_prov:
                obj.last_seen_at = now
                obj.removed_at = None
            updated += 1
    s.flush()
    return inserted, updated


def _chunks(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


class RunLogger:
    """Registra sync_runs + sync_events (log técnico) numa sessão própria, sempre persistida."""

    def __init__(self, session_factory, kind: str, trigger: str, item_id: str | None = None):
        self._sf = session_factory
        with self._sf() as s:
            run = SyncRun(kind=kind, trigger=trigger, item_id=item_id, status="running", started_at=utcnow())
            s.add(run)
            s.commit()
            self.run_id = run.id
        self.warnings = 0
        self.errors = 0

    def log(self, level: str, step: str, message: str, data: dict | None = None) -> None:
        if level == "warn":
            self.warnings += 1
        elif level == "error":
            self.errors += 1
        with self._sf() as s:
            s.add(SyncEvent(run_id=self.run_id, level=level, step=step, message=message[:4000], data=data))
            s.commit()

    def finish(self, stats: dict, error: str | None = None) -> str:
        status = "error" if error else ("partial" if self.errors else "ok")
        with self._sf() as s:
            run = s.get(SyncRun, self.run_id)
            run.finished_at, run.status, run.stats, run.error = utcnow(), status, stats, error
            s.commit()
        return status


def as_dt(v: Any) -> datetime | None:
    return v if isinstance(v, datetime) else None
