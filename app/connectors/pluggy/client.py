"""Cliente REST da Pluggy: API key com renovação, retry (429/5xx/rede), paginação e cursor."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlparse

import httpx

log = logging.getLogger(__name__)
BASE_URL = "https://api.pluggy.ai"
API_KEY_TTL = 110 * 60


class PluggyError(RuntimeError):
    def __init__(self, status: int, message: str, payload: Any = None):
        super().__init__(f"Pluggy {status}: {message}")
        self.status, self.payload = status, payload


class PluggyClient:
    def __init__(self, client_id: str, client_secret: str, timeout: float = 45):
        if not client_id or not client_secret:
            raise PluggyError(0, "PLUGGY_CLIENT_ID/SECRET ausentes no .env")
        self._cid, self._secret = client_id, client_secret
        self._http = httpx.Client(base_url=BASE_URL, timeout=timeout)
        self._key: str | None = None
        self._key_exp = 0.0
        self._lock = threading.Lock()

    def api_key(self, force: bool = False) -> str:
        with self._lock:
            if force or not self._key or time.time() >= self._key_exp:
                r = self._http.post("/auth", json={"clientId": self._cid, "clientSecret": self._secret})
                if r.status_code != 200:
                    raise PluggyError(r.status_code, _msg(r), _json(r))
                self._key, self._key_exp = r.json()["apiKey"], time.time() + API_KEY_TTL
            return self._key

    def request(self, method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        refreshed = False
        for attempt in range(6):
            try:
                r = self._http.request(method, path, params=params, json=json,
                                       headers={"X-API-KEY": self.api_key()})
            except httpx.HTTPError as exc:
                if attempt >= 3:
                    raise PluggyError(0, f"rede: {exc}") from exc
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (401, 403) and not refreshed and _code(r) in (None, "API_KEY_MISSING_OR_INVALID"):
                self.api_key(force=True)
                refreshed = True
                continue
            if r.status_code == 429:
                wait = _int(r.headers.get("RateLimit-Reset")) or _int(r.headers.get("Retry-After")) or 30
                time.sleep(min(wait, 65))
                continue
            if r.status_code >= 500 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:
                raise PluggyError(r.status_code, _msg(r), _json(r))
            return r.json() if r.content else None
        raise PluggyError(429, f"desisti após várias tentativas: {path}")

    def paginate(self, path: str, page_size: int = 500, **params) -> Iterator[dict]:
        page = 1
        while True:
            data = self.request("GET", path, params={**params, "page": page, "pageSize": page_size})
            yield from data.get("results", [])
            if page >= int(data.get("totalPages") or 1):
                return
            page += 1

    def cursor(self, path: str, **params) -> Iterator[dict]:
        while True:
            data = self.request("GET", path, params=params)
            yield from data.get("results", [])
            nxt = data.get("next")
            if not nxt:
                return
            if str(nxt).startswith("http"):
                u = urlparse(nxt)
                path, params = u.path, dict(parse_qsl(u.query))
            elif "=" in str(nxt):
                params = dict(parse_qsl(str(nxt).lstrip("?")))
            else:
                params = {**params, "after": nxt}

    # ---- endpoints -------------------------------------------------------
    def connect_token(self, client_user_id: str | None, item_id: str | None = None,
                      webhook_url: str | None = None) -> str:
        # sem avoidDuplicates: no MeuPluggy cada banco é um item do mesmo conector com a mesma autorização,
        # e a Pluggy recusaria o 2º banco como "item já existe". Duplicata real é barrada em POST /api/items.
        options: dict[str, Any] = {}
        if client_user_id:
            options["clientUserId"] = client_user_id
        if webhook_url:
            options["webhookUrl"] = webhook_url
        body: dict[str, Any] = {"options": options}
        if item_id:
            body["itemId"] = item_id
        return self.request("POST", "/connect_token", json=body)["accessToken"]

    def item(self, item_id: str) -> dict:
        return self.request("GET", f"/items/{item_id}")

    def delete_item(self, item_id: str) -> None:
        self.request("DELETE", f"/items/{item_id}")

    def accounts(self, item_id: str) -> list[dict]:
        return list(self.paginate("/accounts", itemId=item_id))

    def transactions(self, account_id: str, date_from: str | None = None) -> Iterator[dict]:
        return self.cursor("/v2/transactions", accountId=account_id, dateFrom=date_from)

    def transaction(self, tx_id: str) -> dict:
        return self.request("GET", f"/transactions/{tx_id}")

    def bills(self, account_id: str) -> list[dict]:
        return list(self.paginate("/bills", accountId=account_id))

    def investments(self, item_id: str) -> list[dict]:
        return list(self.paginate("/investments", itemId=item_id))

    def investment_transactions(self, investment_id: str) -> list[dict]:
        return list(self.paginate(f"/investments/{investment_id}/transactions"))

    def loans(self, item_id: str) -> list[dict]:
        return list(self.paginate("/loans", itemId=item_id))

    def identity(self, item_id: str) -> dict:
        return self.request("GET", "/identity", params={"itemId": item_id})

    def categories(self) -> list[dict]:
        return list(self.paginate("/categories"))


def _json(r: httpx.Response) -> Any:
    try:
        return r.json()
    except ValueError:
        return None


def _msg(r: httpx.Response) -> str:
    j = _json(r)
    return j.get("message", r.text[:300]) if isinstance(j, dict) else (r.text[:300] or str(r.status_code))


def _code(r: httpx.Response) -> str | None:
    j = _json(r)
    return j.get("codeDescription") if isinstance(j, dict) else None


def _int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None
