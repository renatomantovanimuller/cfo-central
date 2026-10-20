import asyncio
import json

from sqlalchemy import select


def _call(name, **args):
    from app.assistant.mcp_server import mcp
    res = asyncio.run(mcp.call_tool(name, args))
    blocks = res[0] if isinstance(res, tuple) else res
    return json.loads(blocks[0].text)


def test_tools_listed_and_reads_work(synced):
    from app.assistant.mcp_server import mcp
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"visao_geral", "dre", "lancamentos", "consulta_sql", "classificar_lancamentos", "criar_regra"} <= names
    d = _call("dre", meses=3)
    assert d["rows"] and all("children" in r for r in d["rows"])
    ev = _call("lancamentos", tipo="EXPENSE", limite=5)
    assert ev["total"] > 0 and len(ev["items"]) == 5 and ev["items"][0]["amount"] < 0
    assert _call("balanco")["totals"]["net_worth"] is not None


def test_sql_is_read_only(synced):
    ok = _call("consulta_sql", sql="SELECT event_type, count(*) n FROM financial_events GROUP BY 1")
    assert ok["colunas"] == ["event_type", "n"] and ok["linhas"]
    for bad in ("DELETE FROM financial_events", "SELECT 1; DROP TABLE accounts", "SELECT * FROM users",
                "WITH x AS (SELECT 1) UPDATE accounts SET name='x'"):
        assert "erro" in _call("consulta_sql", sql=bad)


def test_write_tools_are_audited(synced):
    from app.models import FinancialEvent, LedgerAudit
    sf = synced["sf"]
    with sf() as s:
        e = s.scalars(select(FinancialEvent).where(FinancialEvent.event_type == "EXPENSE")).first()
        sid = e.source_id
    assert "erro" in _call("classificar_lancamentos", ids=[sid], categoria="nao.existe")
    out = _call("classificar_lancamentos", ids=[sid], categoria="lazer.apostas", nota="teste")
    assert out["ok"] and out["reconstrucao"]["ok"]
    with sf() as s:
        e = s.scalar(select(FinancialEvent).where(FinancialEvent.source_id == sid))
        assert e.category_id == "lazer.apostas" and e.rule_source == "manual"
        assert s.scalar(select(LedgerAudit).where(LedgerAudit.source_id == sid, LedgerAudit.actor == "assistente"))
    prev = _call("simular_regra", padrao="uber")
    assert prev["count"] >= 0
    assert _call("criar_regra", padrao="zzz-nunca", categoria="lazer.apostas")["ok"]
