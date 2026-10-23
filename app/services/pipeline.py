"""Orquestração: sync Pluggy → razão → revisões → snapshots; sync de mercado. Uma execução por vez."""
from __future__ import annotations

import logging
import threading
import time
from contextlib import ExitStack
from typing import Any

from sqlalchemy import func, select

from app.accounting.ledger import rebuild_ledger
from app.alerts.reviews import sync_reviews, system_reviews
from app.config.settings import get_settings
from app.connectors.pluggy.client import PluggyClient
from app.database.advisory import advisory_lock
from app.database.session import session_factory
from app.ingestion.pluggy_sync import sync_categories, sync_item
from app.ingestion.store import RunLogger
from app.models import Item, PluggyCategory

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: PluggyClient | None = None
        self._lock = threading.Lock()
        self._ledger_lock = threading.RLock()
        self.state: dict[str, Any] = {"running": False, "step": None, "last": None, "last_error": None}
        self._recent: dict[str, float] = {}

    @property
    def client(self) -> PluggyClient:
        if self._client is None:
            self._client = PluggyClient(self.settings.pluggy_client_id, self.settings.pluggy_client_secret)
        return self._client

    def item_ids(self) -> list[str]:
        with session_factory()() as s:
            ids = list(s.scalars(select(Item.id).where(Item.is_active.is_(True)).order_by(Item.first_seen_at)))
        return list(dict.fromkeys(ids + self.settings.extra_item_ids))

    # ------------------------------------------------------------------ Pluggy
    def sync(self, trigger: str = "manual", item_ids: list[str] | None = None, full: bool = False) -> dict:
        if not self._lock.acquire(blocking=False):
            return {"status": "busy"}
        try:
            self.state.update(running=True, step="iniciando", last_error=None)
            # ordem: lock de thread (_lock) → _ledger_lock → advisory (entre processos)
            with ExitStack() as stack:
                stack.enter_context(self._ledger_lock)
                stack.enter_context(advisory_lock())
                return self._sync_locked(trigger, item_ids, full)
        except Exception as exc:
            self.state["last_error"] = str(exc)[:300]  # a tela mostra o motivo em vez de "concluída"
            raise
        finally:
            self.state.update(running=False, step=None)
            self._lock.release()

    def _sync_locked(self, trigger: str, item_ids: list[str] | None, full: bool) -> dict:
        sf = session_factory()
        with sf() as s:
            if not s.scalar(select(func.count()).select_from(PluggyCategory)):
                sync_categories(sf, self.client)
        results = {}
        for iid in item_ids or self.item_ids():
            results[iid] = sync_item(sf, self.client, iid, full=full, trigger=trigger,
                                     progress=lambda m, _i=iid: self.state.update(step=f"{_i[:8]} · {m}"))
            self._recent[iid] = time.time()
        self._enrich_merchants()
        if self._missing_market_data():
            self.state["step"] = "cotações dos novos ativos"
            self.market("post-sync")
        self.state["step"] = "livro razão"
        post = self.post_process(trigger)
        self.state["last"] = {"at": time.time(), "items": results, "post": post}
        return self.state["last"]

    def _enrich_merchants(self) -> None:
        """CNAE dos comerciantes novos pela consulta pública do CNPJ, se o usuário ativou. Nunca derruba o sync."""
        from app.categorization import cnpj
        try:
            with session_factory()() as s:
                if cnpj.enabled(s):
                    self.state["step"] = "ramo dos comerciantes (CNPJ)"
                    cnpj.enrich_merchants(s)
                    s.commit()
        except Exception:  # noqa: BLE001
            log.exception("consulta de CNPJ falhou")

    def _missing_market_data(self) -> bool:
        from app.models import Asset, AssetPrice, Investment
        from app.portfolio.service import classify_investments
        with session_factory()() as s:
            classify_investments(s)
            s.commit()
            wanted = {a.yahoo_symbol for a in s.scalars(select(Asset)) if a.yahoo_symbol}
            wanted |= {a.risk_proxy for a in s.scalars(select(Asset)) if a.risk_proxy and any(c in a.risk_proxy for c in ".^=")}
            have = set(s.scalars(select(AssetPrice.symbol).distinct()))
            has_cdi = bool(s.scalar(select(func.count()).select_from(Investment)))
        return bool(wanted - have) and has_cdi

    def rebuild_now(self, trigger: str = "manual") -> dict:
        return self.post_process(trigger)

    def post_process(self, trigger: str = "manual") -> dict:
        """Reconstrói razão, revisões, recorrências e snapshots (sem chamar a Pluggy)."""
        with self._ledger_lock, advisory_lock():
            return self._post_process(trigger)

    def _post_process(self, trigger: str) -> dict:
        from app.analytics.recurring import detect_recurring
        from app.accounting.balance import snapshot_net_worth
        from app.portfolio.service import classify_investments, portfolio_reviews

        sf = session_factory()
        rl = RunLogger(sf, "ledger", trigger)
        try:
            with sf() as s:
                classify_investments(s)
                res = rebuild_ledger(s)
                candidates = res.pop("review_candidates")
                rec = detect_recurring(s)
                candidates += rec.pop("review_candidates", [])
                candidates += system_reviews(s)
                candidates += portfolio_reviews(s)
                from app.analytics.plano import policy_reviews, salary_raise_reviews
                candidates += policy_reviews(s)
                candidates += salary_raise_reviews(s)
                from app.health.checks import health_reviews, run_checks, save_run
                s.flush()
                health = run_checks(s)
                candidates += health_reviews(health)
                save_run(s, health, trigger)
                res["saude"] = {"status": health["status"], **health["contagem"]}
                res["reviews"] = sync_reviews(s, candidates)
                res["recurring"] = rec
                res["net_worth"] = snapshot_net_worth(s)
                try:
                    from app.analytics.saude_financeira import snapshot_health
                    res["saude_financeira"] = snapshot_health(s)
                except Exception:  # noqa: BLE001 - o índice nunca derruba a reconstrução
                    log.exception("índice de saúde financeira falhou")
                s.commit()
            rl.finish(_jsonable(res))
            return res
        except Exception as exc:
            log.exception("post_process falhou")
            rl.log("error", "ledger", str(exc))
            rl.finish({}, error=str(exc))
            raise

    def debounced_sync(self, item_id: str, seconds: int = 120) -> None:
        if time.time() - self._recent.get(item_id, 0) < seconds:
            return
        self._recent[item_id] = time.time()

        def later() -> None:
            time.sleep(15)
            while self.state["running"]:
                time.sleep(5)
            self.sync("webhook", [item_id])
        threading.Thread(target=later, daemon=True).start()

    def sync_async(self, **kwargs) -> bool:
        if self.state["running"]:
            return False
        threading.Thread(target=self.sync, kwargs=kwargs, daemon=True).start()
        return True

    # ------------------------------------------------------------------ mercado
    def market(self, trigger: str = "schedule") -> dict:
        from app.portfolio.market import sync_market
        from app.portfolio.service import classify_investments
        sf = session_factory()
        rl = RunLogger(sf, "market", trigger)
        try:
            with sf() as s:
                classify_investments(s)
                res = sync_market(s, rl)
                s.commit()
            rl.finish(res)
            return res
        except Exception as exc:
            log.exception("market falhou")
            rl.finish({}, error=str(exc))
            return {"error": str(exc)}


def _jsonable(d: Any) -> Any:
    if isinstance(d, dict):
        return {str(k): _jsonable(v) for k, v in d.items()}
    if isinstance(d, (list, tuple)):
        return [_jsonable(v) for v in d]
    if isinstance(d, (int, float, str, bool)) or d is None:
        return d
    return str(d)


pipeline = Pipeline()
