"""Servidor MCP do CFO Central: dá a um assistente (Claude Desktop, Claude Code, sessões ligadas ao PC) acesso
estruturado ao razão, demonstrativos, carteira e fila de revisão, além de ações de curadoria auditadas.

Transporte stdio. Uso típico (o app já rodando no Docker):
    docker exec -i cfo-central-app-1 python -m app.assistant.mcp_server

Leituras vão direto ao banco. Escritas gravam ajuste/regra/cadastro com ator "assistente" na auditoria e pedem
ao app (HTTP interno) para reconstruir o razão, respeitando a trava de processamento do app. Nada aqui move
dinheiro, paga contas ou opera investimentos.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import sys
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator, Literal

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)  # stdout é do protocolo MCP

import httpx  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402
from sqlalchemy import inspect as sa_inspect, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.api import routes_ledger as L, routes_reports as R, routes_system as SY  # noqa: E402
from app.auth.security import INTERNAL_HEADER, internal_token  # noqa: E402
from app.database.session import Base, get_engine, session_factory  # noqa: E402
from app.models import (Account, AccountSetting, Category, EventType, FinancialEvent, ReviewItem,  # noqa: E402
                        Transaction)

ACTOR = "assistente"
APP_URL = os.environ.get("CFO_APP_URL", "http://127.0.0.1:8000")

INSTRUCTIONS = """CFO Central: livro razão financeiro pessoal do usuário (Brasil, BRL), alimentado pelo Open Finance.
Convenções:
- Valores: positivo = entrada de caixa/receita; negativo = saída/despesa. Datas ISO; meses 'AAAA-MM'.
- Cada transação bruta vira um evento econômico com event_type: INCOME, INVESTMENT_INCOME, EXPENSE,
  FINANCIAL_EXPENSE, TAX, REFUND (abate despesa da categoria), INTERNAL_TRANSFER, EXTERNAL_OWN_TRANSFER,
  CARD_PAYMENT (liquidação de fatura, fora da DRE), INVESTMENT_CONTRIBUTION/REDEMPTION (fora da DRE), LOAN_IN,
  LOAN_PAYMENT, IGNORE.
- Compra no cartão é despesa na data da compra; pagamento de fatura não é despesa. Aporte/resgate não é despesa/receita.
- Prioridade de classificação: ajuste manual > regra > conciliação estrutural > comerciante aprendido > Pluggy > palavras-chave.
- rule_source/confidence/is_inferred mostram de onde veio cada decisão; nada é sobrescrito no dado bruto.
Boas práticas: consulte `categorias` antes de classificar; use `simular_regra` antes de `criar_regra`;
prefira classificar o comerciante (vale para o histórico e o futuro) a ajustar lançamento por lançamento;
para perguntas analíticas livres use `consulta_sql` (somente leitura) após ver `esquema`."""

mcp = FastMCP("cfo-central", instructions=INSTRUCTIONS)


# ------------------------------------------------------------------ infraestrutura
def _plain(v: Any) -> Any:
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else round(v, 6)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_plain(x) for x in v]
    if hasattr(v, "item") and callable(v.item):  # numpy
        try:
            return _plain(v.item())
        except (TypeError, ValueError):
            pass
    if v is None or isinstance(v, (str, int, bool)):
        return v
    return str(v)


@contextmanager
def _db() -> Iterator[Session]:
    s = session_factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def _call_app(method: str, path: str, **kw) -> dict | None:
    """Pede ao app em execução (processa com a trava dele). None se o app não estiver acessível."""
    try:
        r = httpx.request(method, f"{APP_URL}{path}", headers={INTERNAL_HEADER: internal_token()},
                          timeout=kw.pop("timeout", 120), **kw)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError:
        return None


def _rebuild() -> dict:
    res = _call_app("POST", "/api/rebuild")
    if res is None:  # app fora do ar (ex.: testes): processa aqui mesmo
        from app.services.pipeline import pipeline
        out = pipeline.rebuild_now(ACTOR)
        res = {"ok": True, "counts": out.get("counts"), "reviews": out.get("reviews"), "via": "local"}
    return res


def _err(msg: str) -> dict:
    return {"erro": msg}


def _check_category(db: Session, cid: str | None) -> str | None:
    if cid and not db.get(Category, cid):
        return f"categoria inexistente: {cid}. Use a ferramenta `categorias`."
    return None


def _check_type(et: str | None) -> str | None:
    if et and et not in EventType.ALL:
        return f"tipo inválido: {et}. Válidos: {', '.join(EventType.ALL)}"
    return None


# ------------------------------------------------------------------ leitura: visão e demonstrativos
@mcp.tool()
def visao_geral(mes: str | None = None) -> dict:
    """KPIs do mês (receitas, despesas, resultado, taxa de poupança, patrimônio, comparação com a média)."""
    with _db() as db:
        return _plain(R.overview(month=mes, db=db))


@mcp.tool()
def dre(meses: int = 12, ate: str | None = None, detalhar: bool = False) -> dict:
    """DRE pessoal por competência, mês a mês, até `ate` (AAAA-MM; padrão: mês atual).
    detalhar=True inclui categorias e subcategorias de cada linha."""
    with _db() as db:
        d = _plain(R.dre(end=ate, months=meses, db=db))
    if not detalhar:
        for row in d.get("rows", []):
            row["children"] = [{"id": c["id"], "label": c["label"], "total": c["total"]} for c in row.get("children", [])]
    return d


@mcp.tool()
def dre_gerencial(mes: str | None = None, so_linhas_principais: bool = False) -> dict:
    """DRE gerencial do mês: valor, média dos 6 meses anteriores, Δ, orçamento e execução, % da receita, acumulado
    do ano; resultado recorrente separado dos extraordinários (herança/doações) e indicadores (poupança, reserva
    em meses, comprometimento com parcelas)."""
    from app.accounting.management import dre_gerencial as G
    with _db() as db:
        d = _plain(G(db, mes))
    if so_linhas_principais:
        d["rows"] = [r for r in d["rows"] if r["level"] == 0]
    return d


@mcp.tool()
def quanto_posso_gastar() -> dict:
    """Quanto ainda dá para gastar no mês corrente sem furar a meta de aporte, com as premissas do cálculo."""
    from app.analytics.plano import safe_to_spend
    with _db() as db:
        return _plain(safe_to_spend(db))


@mcp.tool()
def politica_investimentos() -> dict:
    """Alocação atual × alvos definidos pelo usuário (com bandas), reserva de emergência em meses de custo
    essencial e exposição ao FGC. Não recomenda produtos; só mede contra as regras do usuário."""
    from app.analytics.plano import plan, policy_report
    with _db() as db:
        return _plain({"plano": plan(db), "politica": policy_report(db)})


@mcp.tool()
def definir_plano(meta_aporte_mensal: float | None = None, reserva_meses_minima: float | None = None,
                  limite_fgc: float | None = None, retorno_esperado_aa: float | None = None) -> dict:
    """Atualiza o plano (só os campos informados). retorno_esperado_aa em fração (0.10 = 10% a.a.)."""
    from app.analytics.plano import put_setting
    changes = {k: v for k, v in {"meta_aporte_mensal": meta_aporte_mensal, "reserva_meses_minima": reserva_meses_minima,
                                 "limite_fgc": limite_fgc, "retorno_esperado_aa": retorno_esperado_aa}.items()
               if v is not None}
    with _db() as db:
        return _plain(put_setting(db, "plano", changes))


@mcp.tool()
def definir_alocacao_alvo(alvos: list[dict]) -> dict:
    """Substitui a alocação-alvo. Cada item: {"asset_class": "...", "target_pct": 0.3, "min_pct"?, "max_pct"?}
    (frações; soma ≤ 1). Use os nomes de classe que aparecem em `politica_investimentos`. Só faça a pedido do usuário."""
    from app.analytics.plano import policy_report, set_targets
    if sum(float(a.get("target_pct", 0)) for a in alvos) > 1.0001:
        return _err("a soma dos alvos passa de 100%")
    with _db() as db:
        set_targets(db, alvos)
        db.commit()
        return _plain(policy_report(db))


@mcp.tool()
def simular_meta(valor_alvo: float, meses: int, aporte_mensal: float, valor_atual: float | None = None,
                 retorno_aa: float | None = None, vol_aa: float | None = None) -> dict:
    """Monte Carlo (4.000 cenários): probabilidade de atingir `valor_alvo` em `meses` com `aporte_mensal`.
    Sem retorno/vol informados, usa o histórico ex-ante da carteira atual; sem valor_atual, usa os investimentos."""
    from app.accounting.balance import current_position
    from app.analytics.plano import monte_carlo, portfolio_mu_sigma
    with _db() as db:
        if valor_atual is None:
            valor_atual = current_position(db)["totals"]["investments"]
        mu, sig, fonte = portfolio_mu_sigma(db, 0.10)
    mu = retorno_aa if retorno_aa is not None else mu
    sig = vol_aa if vol_aa is not None else sig
    out = monte_carlo(valor_atual, valor_alvo, meses, aporte_mensal, mu, sig)
    out["trajetoria"] = out["trajetoria"][:: max(1, len(out["trajetoria"]) // 12)]
    return _plain({**out, "valor_atual": valor_atual, "fonte_risco": fonte if retorno_aa is None else "informado"})


@mcp.tool()
def retornos_realizados(incluir_lotes: bool = False) -> dict:
    """Renda fixa/Tesouro por título (inclusive resgatados): aplicado, resgatado, IR/IOF, resultado, TIR, % CDI.
    Renda variável: custo e preço médio só onde há evidência (Pluggy, débito bancário ou estimativa marcada)."""
    from app.portfolio.realized import equity_lots, fixed_income_titles
    with _db() as db:
        out = {"renda_fixa": fixed_income_titles(db), "renda_variavel": equity_lots(db)}
    if not incluir_lotes:
        for a in out["renda_variavel"]["ativos"]:
            a.pop("lotes", None)
    return _plain(out)


@mcp.tool()
def saude_dados(rodar_agora: bool = False) -> dict:
    """Saúde dos dados: conferências automáticas (faturas × lançamentos, saldo do cartão, saldos bancários
    reconstruídos, banco × corretora, razão completo, transferências pareadas, pendentes/duplicidades, sincronização,
    cotações e cobertura da classificação). Status por verificação: ok | atencao | falha | info, com detalhes.
    Roda sozinho a cada reconstrução; `rodar_agora` executa já (sem reconstruir o razão)."""
    from app.health.checks import latest, run_checks, save_run
    with _db() as db:
        if rodar_agora:
            save_run(db, run_checks(db), "assistente")
            db.commit()
        out = latest(db) or {"status": "sem execução ainda"}
    out.pop("historico", None)
    return _plain(out)


@mcp.tool()
def classificador() -> dict:
    """Classificador treinado nas decisões do usuário (TF-IDF + regressão logística): amostras, validação cruzada
    (acurácia e precisão acima do limiar), se está habilitado, quantos lançamentos reclassificou/confirmou e exemplos
    com os termos que mais pesaram. Lançamentos reclassificados têm rule_source='modelo'."""
    from app.analytics.plano import get_setting
    with _db() as db:
        return _plain(get_setting(db, "classificador") or {"habilitado": False, "motivo": "ainda não treinado"})


@mcp.tool()
def imposto_de_renda(ano_base: int | None = None, secao: Literal["tudo", "bens", "exclusiva", "isentos",
                                                                    "renda_variavel", "pagamentos", "pendencias"] = "tudo") -> dict:
    """Prévia do IRPF do ano-base (padrão: o ano corrente a partir de março): bens e direitos com grupo/código e
    situação em 31/12, rendimentos de aplicações (código 06, IR retido), isentos (herança/doação 14, dividendos 09,
    ações até 20 mil 20), renda variável mês a mês com DARF 6015, pagamentos dedutíveis (saúde/instrução, com
    CPF/CNPJ do prestador e reembolsos) e pendências a completar. Prévia: os informes oficiais prevalecem."""
    from app.tax.irpf import irpf_report
    with _db() as db:
        r = irpf_report(db, ano_base)
    keys = {"bens": "bens_e_direitos", "exclusiva": "tributacao_exclusiva", "isentos": "isentos",
            "renda_variavel": "renda_variavel", "pagamentos": "pagamentos", "pendencias": "pendencias"}
    if secao != "tudo":
        r = {"ano_base": r["ano_base"], "parcial": r["parcial"], keys[secao]: r[keys[secao]], "aviso": r["aviso"]}
    return _plain(r)


@mcp.tool()
def dfc(meses: int = 6, ate: str | None = None) -> dict:
    """Demonstração de fluxo de caixa (método direto, contas bancárias) com conferência contra saldos."""
    with _db() as db:
        return _plain(R.dfc(end=ate, months=meses, db=db))


@mcp.tool()
def balanco(historico_meses: int = 0) -> dict:
    """Balanço patrimonial atual (caixa, investimentos, cartões, parcelas a vencer, empréstimos, PL) com premissas.
    historico_meses>0 inclui a evolução mensal (reconstruída/estimada antes do 1º snapshot)."""
    with _db() as db:
        out = _plain(R.balance(db=db))
        if historico_meses > 0:
            out["historico"] = _plain(R.balance_history(months=historico_meses, db=db))
        return out


@mcp.tool()
def cartoes() -> dict:
    """Cartões: fatura atual, limite usado/efetivo, faturas fechadas, parcelas futuras e gasto mensal."""
    with _db() as db:
        d = _plain(R.cards(db=db))
    for c in d.get("cards", []):
        c["bills"] = c.get("bills", [])[:6]
    return d


@mcp.tool()
def carteira(incluir_risco: bool = False, anos_risco: int = 2) -> dict:
    """Carteira de investimentos: posições, alocação, exposição FGC por emissor, vencimentos, desempenho.
    incluir_risco=True adiciona volatilidade, Sharpe/Sortino vs CDI, drawdown, VaR/CVaR, beta e contribuições."""
    with _db() as db:
        out = _plain(R.portfolio(db=db))
        out.pop("movements", None)
        if incluir_risco:
            out["risco"] = _plain(R.portfolio_risk(years=anos_risco, db=db))
        return out


@mcp.tool()
def planejamento() -> dict:
    """Previsão de caixa (6 meses), capacidade de investimento, recorrências, orçamento do mês e metas."""
    with _db() as db:
        return _plain(R.planning(db=db))


# ------------------------------------------------------------------ leitura: razão e cadastros
@mcp.tool()
def lancamentos(mes: str | None = None, de: str | None = None, ate: str | None = None, busca: str | None = None,
                categoria: str | None = None, tipo: str | None = None, conta: str | None = None,
                comerciante_id: int | None = None, sentido: Literal["in", "out"] | None = None,
                valor_min: float | None = None, valor_max: float | None = None,
                so_pendentes_de_revisao: bool = False, ordenar: str = "-date", limite: int = 50,
                pagina: int = 1) -> dict:
    """Busca no razão. `categoria` inclui subcategorias; `tipo` aceita lista separada por vírgula
    (ex.: 'EXPENSE,REFUND'); `busca` procura em descrição, contraparte e nota. ordenar: date|amount|confidence
    com '-' para decrescente. Retorna totais de entradas/saídas do filtro inteiro."""
    with _db() as db:
        d = L.list_events(month=mes, start=date.fromisoformat(de) if de else None,
                          end=date.fromisoformat(ate) if ate else None, account=conta, category=categoria,
                          event_type=tipo, merchant=comerciante_id, q=busca,
                          review=True if so_pendentes_de_revisao else None, min_amount=valor_min,
                          max_amount=valor_max, direction=sentido, include_removed=False, page=pagina,
                          page_size=max(1, min(limite, 200)), sort=ordenar, db=db)
    keep = ("id", "date", "description", "counterparty", "amount", "event_type", "category_id", "category",
            "account", "merchant_id", "rule_source", "confidence", "needs_review", "note", "installment")
    d["items"] = [{k: i.get(k) for k in keep} for i in d["items"]]
    return _plain(d)


@mcp.tool()
def lancamento(id: str, incluir_payload_bruto: bool = False) -> dict:
    """Detalhe de um lançamento: evento, transação normalizada, regra aplicada, comerciante, vínculos
    (transferência/fatura), ajuste manual e histórico de auditoria."""
    with _db() as db:
        try:
            d = _plain(L.event_detail(source_id=id, db=db))
        except Exception:  # noqa: BLE001 - 404 da rota
            return _err("lançamento não encontrado")
    if not incluir_payload_bruto:
        d.pop("raw", None)
    return d


@mcp.tool()
def categorias() -> list[dict]:
    """Plano de contas: id, nome, categoria-mãe, natureza (receita/despesa/patrimonial/...), linha da DRE."""
    with _db() as db:
        return _plain(L.categories_flat(db=db))


@mcp.tool()
def gastos_por_categoria(mes: str | None = None) -> list[dict]:
    """Árvore de categorias com valores do mês, média e orçamento."""
    with _db() as db:
        return _plain(L.categories(month=mes, db=db))


@mcp.tool()
def comerciantes(meses: int = 12, limite: int = 40, busca: str | None = None) -> list[dict]:
    """Ranking de comerciantes/contrapartes por valor no período, com categoria padrão aprendida."""
    with _db() as db:
        rows = _plain(L.merchants(months=meses, db=db))
    if busca:
        b = busca.lower()
        rows = [r for r in rows if b in json.dumps(r, ensure_ascii=False).lower()]
    return rows[: max(1, min(limite, 300))]


@mcp.tool()
def contas() -> dict:
    """Conexões e contas (id, apelido, tipo, saldo, limite) e estado da última sincronização."""
    with _db() as db:
        return _plain({"conexoes": SY.connections(db=db), "sincronizacao": SY.sync_status(db=db)})


@mcp.tool()
def revisoes(status: Literal["open", "resolved", "dismissed"] = "open", tipo: str | None = None,
             limite: int = 50) -> list[dict]:
    """Fila de revisão (itens que o sistema não decidiu com segurança), mais relevantes primeiro."""
    with _db() as db:
        rows = _plain(L.reviews(status=status, kind=tipo, db=db))
    return rows[: max(1, min(limite, 300))]


@mcp.tool()
def regras() -> list[dict]:
    """Regras de categorização ativas e inativas, com quantos lançamentos cada uma pegou."""
    with _db() as db:
        return _plain(L.list_rules(db=db))


# ------------------------------------------------------------------ leitura livre (SQL somente leitura)
_SQL_OK = re.compile(r"^\s*(with|select)\b", re.I)
_SQL_BLOCK = re.compile(r"\b(users|insert|update|delete|drop|alter|create|grant|truncate|copy|pg_read|pg_sleep)\b", re.I)


@mcp.tool()
def esquema(tabela: str | None = None) -> dict:
    """Tabelas e colunas do banco (para montar `consulta_sql`). Principais: financial_events (razão),
    transactions (espelho normalizado), accounts, categories, merchants, category_rules, review_items,
    investments, investment_balances, assets, market_series, daily_net_worth."""
    insp = sa_inspect(get_engine())
    names = [t for t in Base.metadata.sorted_tables if t.name != "users"]
    if tabela:
        names = [t for t in names if t.name == tabela]
        if not names:
            return _err(f"tabela {tabela} não existe")
    return {t.name: {c.name: str(c.type) for c in t.columns} for t in names if insp.has_table(t.name)}


@mcp.tool()
def consulta_sql(sql: str, limite: int = 200) -> dict:
    """Executa um SELECT/WITH em transação somente leitura (timeout 15 s, até `limite` linhas).
    Ex.: SELECT category_id, sum(amount) FROM financial_events WHERE event_type='EXPENSE' AND is_removed=false
    AND competence_date >= '2026-01-01' GROUP BY 1 ORDER BY 2."""
    body = sql.strip().rstrip(";")
    if not _SQL_OK.match(body) or ";" in body or _SQL_BLOCK.search(body):
        return _err("somente uma consulta SELECT/WITH, sem comandos de escrita e sem a tabela users")
    limite = max(1, min(limite, 2000))
    eng = get_engine()
    with eng.connect() as conn:
        trans = conn.begin()
        try:
            if eng.dialect.name == "postgresql":
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text("SET LOCAL statement_timeout = '15s'"))
            else:
                conn.exec_driver_sql("PRAGMA query_only = ON")
            res = conn.execute(text(body))
            cols = list(res.keys())
            rows = res.fetchmany(limite + 1)
        except Exception as e:  # noqa: BLE001
            return _err(f"consulta falhou: {str(e).splitlines()[0][:300]}")
        finally:
            trans.rollback()
            if eng.dialect.name != "postgresql":
                conn.exec_driver_sql("PRAGMA query_only = OFF")
    return {"colunas": cols, "linhas": _plain([list(r) for r in rows[:limite]]), "truncado": len(rows) > limite}


# ------------------------------------------------------------------ escrita (curadoria auditada)
@mcp.tool()
def classificar_lancamentos(ids: list[str], categoria: str | None = None, tipo: str | None = None,
                            nota: str | None = None, ensinar_comerciante: bool = False) -> dict:
    """Ajuste manual em um ou mais lançamentos (vence qualquer regra). `tipo` só quando a categoria não basta
    (ex.: REFUND, IGNORE). ensinar_comerciante=True faz a categoria virar o padrão do comerciante."""
    with _db() as db:
        if e := _check_category(db, categoria) or _check_type(tipo):
            return _err(e)
        missing = [i for i in ids if not db.get(Transaction, i)]
        if missing:
            return _err(f"lançamentos não encontrados: {missing[:5]}")
        body = L.EventPatch(**{k: v for k, v in {"category_id": categoria, "event_type": tipo, "note": nota}.items()
                               if v is not None}, learn=ensinar_comerciante)
        for i in ids:
            L._apply_override(db, i, body, actor=ACTOR)
    return {"ok": True, "ajustados": len(ids), "reconstrucao": _rebuild()}


@mcp.tool()
def remover_ajuste(id: str) -> dict:
    """Remove o ajuste manual de um lançamento (volta à classificação automática)."""
    with _db() as db:
        L._apply_override(db, id, L.EventPatch(clear=True), actor=ACTOR)
    return {"ok": True, "reconstrucao": _rebuild()}


@mcp.tool()
def classificar_comerciante(comerciante_id: int, categoria: str, nome: str | None = None) -> dict:
    """Define a categoria padrão de um comerciante/contraparte (vale para o histórico e para o futuro)."""
    with _db() as db:
        if e := _check_category(db, categoria):
            return _err(e)
        try:
            L.update_merchant(db, comerciante_id, L.MerchantPatch(default_category_id=categoria, canonical_name=nome))
        except Exception:  # noqa: BLE001 - 404
            return _err("comerciante não encontrado")
    return {"ok": True, "reconstrucao": _rebuild()}


def _rule_body(padrao: str, campo: str, operador: str, categoria: str | None, tipo: str | None,
               sentido: str | None, valor_min: float | None, valor_max: float | None, nome: str | None,
               prioridade: int) -> "L.RuleBody":
    return L.RuleBody(name=nome, priority=prioridade, field=campo, operator=operador, pattern=padrao,
                      amount_min=valor_min, amount_max=valor_max, direction=sentido, category_id=categoria,
                      event_type=tipo)


@mcp.tool()
def simular_regra(padrao: str, campo: Literal["description", "merchant", "cnpj", "pluggy_category", "mcc", "account"] = "description",
                  operador: Literal["contains", "equals", "starts", "regex"] = "contains",
                  sentido: Literal["in", "out"] | None = None, valor_min: float | None = None,
                  valor_max: float | None = None) -> dict:
    """Mostra quais lançamentos uma regra pegaria, sem gravar nada."""
    with _db() as db:
        body = _rule_body(padrao, campo, operador, None, "EXPENSE", sentido, valor_min, valor_max, None, 100)
        return _plain(L.preview_rule(body=body, db=db))


@mcp.tool()
def criar_regra(padrao: str, categoria: str | None = None, tipo: str | None = None,
                campo: Literal["description", "merchant", "cnpj", "pluggy_category", "mcc", "account"] = "description",
                operador: Literal["contains", "equals", "starts", "regex"] = "contains",
                sentido: Literal["in", "out"] | None = None, valor_min: float | None = None,
                valor_max: float | None = None, nome: str | None = None, prioridade: int = 100) -> dict:
    """Cria regra de categorização (prioridade menor roda antes). Rode `simular_regra` antes."""
    with _db() as db:
        if e := _check_category(db, categoria) or _check_type(tipo):
            return _err(e)
        if not (categoria or tipo):
            return _err("informe categoria e/ou tipo")
        try:
            r = L.add_rule(db, _rule_body(padrao, campo, operador, categoria, tipo, sentido, valor_min, valor_max,
                                          nome or f"Assistente: {padrao}", prioridade))
        except Exception as ex:  # noqa: BLE001 - validação da rota
            return _err(getattr(ex, "detail", str(ex)))
        rid = r.id
    return _plain({"ok": True, "regra_id": rid, "reconstrucao": _rebuild()})


@mcp.tool()
def desativar_regra(regra_id: int) -> dict:
    """Desativa (não apaga) uma regra."""
    with _db() as db:
        from app.models import CategoryRule
        r = db.get(CategoryRule, regra_id)
        if not r:
            return _err("regra não encontrada")
        r.active = False
    return {"ok": True, "reconstrucao": _rebuild()}


@mcp.tool()
def resolver_revisao(revisao_id: int, acao: Literal["resolve", "dismiss"], categoria: str | None = None,
                     tipo: str | None = None) -> dict:
    """Resolve (aplicando categoria/tipo ao lançamento ou ao comerciante do item) ou dispensa um item da revisão."""
    with _db() as db:
        if e := _check_category(db, categoria) or _check_type(tipo):
            return _err(e)
        if not db.get(ReviewItem, revisao_id):
            return _err("item de revisão não encontrado")
        L.apply_review(db, revisao_id, L.ReviewAction(action=acao, category_id=categoria, event_type=tipo), actor=ACTOR)
    return {"ok": True, "reconstrucao": _rebuild()}


@mcp.tool()
def configurar_conta(conta_id: str, apelido: str | None = None, finalidade: str | None = None,
                     incluir_no_patrimonio: bool | None = None) -> dict:
    """Apelido, finalidade (corrente, reserva, cartao_principal...) e inclusão no patrimônio de uma conta."""
    with _db() as db:
        if not db.get(Account, conta_id):
            return _err("conta não encontrada")
        changes = {k: v for k, v in {"nickname": apelido, "purpose": finalidade,
                                     "include_in_net_worth": incluir_no_patrimonio}.items() if v is not None}
        R.patch_account(account_id=conta_id, body=R.AccountSettingBody(**changes), db=db)
        st = db.get(AccountSetting, conta_id)
        return _plain({"ok": True, "apelido": st.nickname if st else None})


@mcp.tool()
def definir_orcamento(categoria: str, valor: float | None, mes: str | None = None) -> dict:
    """Orçamento mensal da categoria (mes=None vale para todos os meses; valor=None remove)."""
    with _db() as db:
        if e := _check_category(db, categoria):
            return _err(e)
        return _plain(L.set_budget(category_id=categoria, body=L.BudgetBody(amount=valor, month=mes), db=db))


@mcp.tool()
def sincronizar(completo: bool = False) -> dict:
    """Pede ao app uma sincronização com a Pluggy (roda em segundo plano no app; acompanhe com `contas`)."""
    res = _call_app("POST", "/api/sync", json={"full": completo})
    return res or _err("o app não respondeu em " + APP_URL)


@mcp.tool()
def reconstruir_razao() -> dict:
    """Reprocessa conciliação, categorização, revisões e snapshots (sem chamar a Pluggy)."""
    return _rebuild()


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
