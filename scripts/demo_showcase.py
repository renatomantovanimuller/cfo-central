"""Banco de vitrine para a demonstração pública (GitHub Pages): perfil fictício que poupa e investe.

    DATABASE_URL=sqlite:///showcase.db python -m scripts.demo_showcase
    DATABASE_URL=sqlite:///showcase.db python -m scripts.demo_snapshot frontend/dist-demo/demo-data.json

Parte do mesmo cliente falso dos testes, com salário maior e aplicações mensais, e aplica a curadoria que um
usuário faria na primeira semana (salário classificado, orçamentos, plano, alocação-alvo, meta). O app
reconstrói o caixa do passado a partir do saldo atual menos os lançamentos, então o saldo da conta é derivado
dos próprios lançamentos para nenhum mês histórico ficar negativo.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("PLUGGY_CLIENT_ID", "demo")
os.environ.setdefault("PLUGGY_CLIENT_SECRET", "demo")

from app.auth.security import COOKIE, issue_token  # noqa: E402
from app.database.migrate import migrate  # noqa: E402
from app.database.session import session_factory  # noqa: E402
from app.ingestion.pluggy_sync import sync_item  # noqa: E402
from app.services.pipeline import pipeline  # noqa: E402
from tests.fixtures.fake_pluggy import BANK_ID, ITEM_ID, FakePluggyClient  # noqa: E402

MIN_CASH = 6000.0  # menor saldo da conta corrente em qualquer data do histórico


class Showcase(FakePluggyClient):
    def _tx(self, acc, d, desc, amount, *a, **k):
        if "ACME" in desc:
            amount = round(amount * 1.6, 2)  # salário ~R$ 5,3 mil
        elif desc == "Aplicação RDB":
            amount = -2500.0  # a sobra do mês vai para investimentos
        return super()._tx(acc, d, desc, amount, *a, **k)

    def accounts(self, item_id):
        accs = super().accounts(item_id)
        running = low = 0.0
        for t in sorted(self._bank, key=lambda t: t["date"]):
            running += t["amount"]
            low = min(low, running)
        balance = round(MIN_CASH - low + running, 2)  # saldo inicial mínimo que mantém o caixa >= MIN_CASH
        for a in accs:
            if a["id"] == BANK_ID:
                a["balance"], a["bankData"] = balance, {"closingBalance": balance}
        return accs


def curate() -> None:
    """Decisões de um usuário real nos primeiros dias, pela própria API (mesmo caminho da interface)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        c.cookies.set(COOKIE, issue_token("demo"))

        def ok(r):
            r.raise_for_status()
            return r.json()

        for r in ok(c.get("/api/reviews")):
            if r["kind"] == "recurring_income":
                ok(c.post(f"/api/reviews/{r['id']}", json={"action": "resolve", "category_id": "rec.salario"}))
        for cat, v in [("alimentacao.mercado", 600), ("alimentacao.restaurantes", 350), ("alimentacao.delivery", 150),
                       ("lazer", 300), ("compras", 400)]:
            ok(c.put(f"/api/budgets/{cat}", json={"amount": v}))
        ok(c.put("/api/plan/settings", json={"meta_aporte_mensal": 1200, "reserva_meses_minima": 6}))
        ok(c.put("/api/plan/targets", json=[{"asset_class": k, "target_pct": v} for k, v in
                                             [("RF Pós", .35), ("ETF Internacional", .25), ("ETF Ações BR", .15),
                                              ("Tesouro IPCA+", .15), ("FIIs", .10)]]))
        goal = ok(c.post("/api/goals", json={"name": "Viagem ao Japão", "target_amount": 25000,
                                             "target_date": "2027-12-01", "priority": 1}))
        # parte do CDB separada para a viagem e a conta corrente como reserva parcial: bolsos com dinheiro na vitrine
        fontes = ok(c.get("/api/buckets"))
        cdb = next((f for f in fontes["fontes"] if f["classe"] == "RF Pós"), None)
        if cdb and goal.get("bucket_id"):
            ok(c.put(f"/api/buckets/{goal['bucket_id']}/allocations",
                     json=[{"source_type": cdb["type"], "source_id": cdb["id"], "pct": 0.6}]))
        reserva = next(b for b in fontes["bolsos"] if b["tipo"] == "reserva")
        conta = next((f for f in fontes["fontes"] if f["type"] == "account"), None)
        if conta:
            ok(c.put(f"/api/buckets/{reserva['id']}/allocations",
                     json=[{"source_type": "account", "source_id": conta["id"], "pct": 0.7},
                           *([{"source_type": cdb["type"], "source_id": cdb["id"], "pct": 0.3}] if cdb else [])]))
        ok(c.post("/api/goals", json={"name": "Independência financeira", "kind": "aposentadoria",
                                      "target_amount": 1500000, "target_date": "2050-01-01", "priority": 5}))
        item = ok(c.get("/api/connections"))["items"][0]
        ok(c.patch(f"/api/items/{item['id']}", json={"nickname": "Banco Roxinho"}))
        ok(c.post("/api/rebuild"))


if __name__ == "__main__":
    migrate()
    sync_item(session_factory(), Showcase(), ITEM_ID, full=True, trigger="demo")
    errors = pipeline.market("demo").get("errors")
    if errors:
        print("cotações com falha (a carteira mostra menos histórico):", errors)
    pipeline.post_process("demo")
    curate()
    print("vitrine pronta")
