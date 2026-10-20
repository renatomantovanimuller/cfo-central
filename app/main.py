"""CFO Central — app FastAPI: API + SPA + agendador."""
from __future__ import annotations

import json
import logging
import math
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from app.api import routes_ledger, routes_reports, routes_system
from app.config.settings import get_settings
from app.connectors.pluggy.client import PluggyError
from app.database.migrate import migrate
from app.database.session import session_scope
from app.models import SyncRun
from app.services.pipeline import pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cfo")


def _alerts_job() -> None:
    from app.alerts.notify import daily_digest, monthly_close
    from app.utils.time import today_brt
    try:
        with session_scope() as s:
            if today_brt().day <= 3:  # fechamento do mês anterior (repete até 3 dias se falhar; envia uma vez)
                monthly_close(s)
            daily_digest(s)
    except Exception:  # noqa: BLE001
        log.exception("alertas por e-mail falharam")


def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    st = get_settings()
    sched = BackgroundScheduler(timezone=st.timezone)
    sched.add_job(lambda: pipeline.sync("schedule"), "interval", hours=st.pluggy_sync_hours, id="pluggy",
                  next_run_time=datetime.now(timezone.utc) + timedelta(seconds=10), max_instances=1, coalesce=True)
    sched.add_job(lambda: (pipeline.market("schedule"), pipeline.rebuild_now("market")), "cron",
                  hour=st.market_sync_hour, minute=45, id="market", max_instances=1, coalesce=True)
    sched.add_job(_alerts_job, "cron", hour=st.alerts_hour, minute=5, id="alerts", max_instances=1, coalesce=True)
    with session_scope() as s:
        last = s.scalar(select(func.max(SyncRun.started_at)).where(SyncRun.kind == "market", SyncRun.status == "ok"))
    if last is None or (datetime.now(last.tzinfo) - last).total_seconds() > 20 * 3600:
        sched.add_job(lambda: pipeline.market("startup"), id="market_startup")
    sched.start()
    return sched


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate()
    from app.config.integrations import apply as apply_integrations
    with session_scope() as s:
        apply_integrations(s)
    sched = start_scheduler() if get_settings().scheduler_enabled else None
    yield
    if sched:
        sched.shutdown(wait=False)


def _sanitize(v):
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, dict):
        return {k: _sanitize(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_sanitize(x) for x in v]
    return v


class Encoder(JSONResponse):
    def render(self, content) -> bytes:
        data = _sanitize(jsonable_encoder(content, custom_encoder={date: lambda d: d.isoformat()}))
        return json.dumps(data, ensure_ascii=False, allow_nan=False, default=str).encode("utf-8")


def create_app() -> FastAPI:
    app = FastAPI(title="CFO Central", version="1.0", lifespan=lifespan, default_response_class=Encoder)
    app.include_router(routes_system.public)
    app.include_router(routes_system.router)
    app.include_router(routes_ledger.router)
    app.include_router(routes_reports.router)

    @app.exception_handler(PluggyError)
    async def pluggy_error(_: Request, exc: PluggyError):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    dist: Path = get_settings().frontend_dist
    if (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            f = dist / path
            if path and f.is_file() and dist in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")
    return app


app = create_app()
