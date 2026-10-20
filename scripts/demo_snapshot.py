"""Grava as respostas da API para a vitrine estática (frontend em modo demo, sem servidor).

    DATABASE_URL=sqlite:///demo.db python -m scripts.demo_snapshot frontend/dist-demo/demo-data.json

Use só com banco de dados fictícios (ex.: python -m scripts.demo_seed): o arquivo gerado contém tudo o que
as telas mostram, inclusive o detalhe de cada lançamento.
"""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["SCHEDULER_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.auth.security import COOKIE, issue_token  # noqa: E402
from app.main import app  # noqa: E402
from app.utils.time import month_add, month_key, today_brt  # noqa: E402

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MONTHS_BACK = 14  # meses navegáveis no seletor (o seed gera 13)
WINDOWS = (6, 12, 24)


def key(path: str, **params) -> str:
    """Mesma chave do front (src/demo.ts → routeKey): caminho + parâmetros em ordem alfabética."""
    return path + (f"?{urlencode(sorted((k, str(v)) for k, v in params.items()))}" if params else "")


def label(ym: str) -> str:
    y, m = ym.split("-")
    return f"{MESES[int(m) - 1]}/{y[2:]}"


def main(out: str) -> None:
    with TestClient(app) as c:
        c.cookies.set(COOKIE, issue_token("demo"))
        routes: dict[str, object] = {}

        def get(path: str, **params):
            r = c.get(path, params=params)
            r.raise_for_status()
            routes[key(path, **params)] = r.json()
            return routes[key(path, **params)]

        for p in ("/api/sync/status", "/api/onboarding", "/api/integrations", "/api/reviews", "/api/categories/flat",
                  "/api/balance", "/api/cards", "/api/portfolio", "/api/portfolio/realized", "/api/planning",
                  "/api/rules", "/api/data-health", "/api/assets", "/api/manual-assets", "/api/alerts/status"):
            get(p)
        conns = get("/api/connections")
        for run in conns["runs"]:
            get(f"/api/runs/{run['id']}/events")
        for status in ("open", "resolved", "dismissed"):
            get("/api/reviews", status=status)
        for n in (12, 18):
            get("/api/balance/history", months=n)
        for y in (1, 2, 3):
            get("/api/portfolio/risk", years=y)
        for m in (3, 12, 24):
            get("/api/merchants", months=m)
        year = today_brt().year
        for ano in (year, year - 1, year - 2):
            get("/api/ir", ano=ano)

        cur = month_key(today_brt())
        months = [month_add(cur, -k) for k in range(MONTHS_BACK)]
        for m in months:
            get("/api/overview", month=m)
            get("/api/dre/gerencial", month=m)
            get("/api/sankey", month=m)
            get("/api/categories", month=m)
            for n in WINDOWS:
                get("/api/dre", end=m, months=n)
                get("/api/dfc", end=m, months=n)
        for cat in routes[key("/api/categories/flat")]:
            get(f"/api/categories/{cat['id']}/detail")

        events = c.get("/api/events", params={"page_size": 100000, "include_removed": True}).json()["items"]
        for e in events:
            get(f"/api/events/{e['id']}")
        cats = [{"id": x["id"], "parent_id": x["parent_id"]} for x in routes[key("/api/categories/flat")]]

    snap = {"routes": routes, "events": events, "categories": cats, "period": f"{label(months[-1])} a {label(months[0])}",
            "today": today_brt().isoformat()}
    Path(out).write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(routes)} respostas, {len(events)} lançamentos → {out} ({Path(out).stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "frontend/dist-demo/demo-data.json")
