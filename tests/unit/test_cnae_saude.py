"""CNAE do comerciante (mapa, motor, consulta pública do CNPJ) e índice de saúde financeira."""
from datetime import date

import httpx

from app.categorization.cnae import cnae_category, norm_cnae
from app.categorization.engine import TxView


def _tx(desc, flow, cat=None, doc=None, typ="BANK", cnae=None, **kw):
    base = dict(id="t", account_id="a1", item_id="i1", account_type=typ, date=date(2026, 5, 4), flow=flow,
                description=desc, description_raw=None, pluggy_cat=cat, merchant_name=None, merchant_cnpj=doc, mcc=None,
                payment_method="PIX", counterparty_name=None, counterparty_doc=doc, payer_doc=None, receiver_doc=doc,
                status="POSTED", installment_number=None, total_installments=None, removed=False, merchant_cnae=cnae)
    return TxView(**{**base, **kw})


def test_mapa_cnae_prefixo_mais_longo():
    assert norm_cnae("4771-7/01") == "4771701" and norm_cnae(3514000) == "3514000" and norm_cnae("") is None
    assert cnae_category("4771701")[:2] == ("saude.farmacia", 0.9)
    assert cnae_category("8630504")[0] == "saude.dentista"      # subclasse vence a classe 8630 (consultas)
    assert cnae_category("8630503")[0] == "saude.consultas"
    assert cnae_category("6422100") is None                     # banco: não diz o que foi comprado


def _decide(tx, m=None):
    from collections import Counter

    from app.accounting.ledger import _decide as D
    from app.categorization.chart import PLUGGY_MAP
    return D(tx, None, [], {}, m, PLUGGY_MAP, {}, Counter())


def test_pix_para_empresa_classificado_pelo_ramo():
    # Pluggy só diz "Transferência para PJ" (confiança baixa); o CNAE diz que é farmácia
    d = _decide(_tx("Pix enviado DROG SAO JOAO LTDA", -87.3, cat="05010000", doc="11222333000144", cnae="4771701"))
    assert (d.category_id, d.rule_id) == ("saude.farmacia", "cnae:4771")
    # palavra-chave de marca empata ou vence o CNAE (mais específica)
    d = _decide(_tx("Pix enviado Uber do Brasil", -20.0, cat="05010000", doc="17895646000187", cnae="6319400"))
    assert d.category_id == "transporte.apps"
    # entrada nunca vira despesa pelo CNAE
    d = _decide(_tx("Pix recebido Drogaria", 50.0, cat="05010000", doc="11222333000144", cnae="4771701"))
    assert d.category_id == "rec.pix_terceiros"


def test_cnae_do_cadastro_do_comerciante_vale_quando_a_transacao_nao_traz():
    from types import SimpleNamespace
    m = SimpleNamespace(id=9, cnae="5611201", default_category_id=None, category_origin=None)
    d = _decide(_tx("Pix enviado CANTINA DA ESQUINA", -64.0, cat="05010000", doc="11222333000144"), m=m)
    assert d.category_id == "alimentacao.restaurantes"


def test_consulta_publica_do_cnpj(db_reset, monkeypatch):
    from app.categorization import cnpj
    from app.models import Merchant
    monkeypatch.setattr(cnpj, "PAUSE", 0)
    s = db_reset()
    s.add_all([Merchant(canonical_name="11222333000144", cnpj="11222333000144"),
               Merchant(canonical_name="Loja X", cnpj="99888777000166"),
               Merchant(canonical_name="Fulano", cnpj="12345678901"),        # CPF: nunca consultado
               Merchant(canonical_name="Já tem", cnpj="55444333000122", cnae="4711302")])
    s.flush()
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        doc = req.url.path.rsplit("/", 1)[-1]
        seen.append(doc)
        if doc == "11222333000144":
            return httpx.Response(200, json={"cnae_fiscal": 4771701, "cnae_fiscal_descricao": "Comércio varejista de "
                                             "produtos farmacêuticos", "nome_fantasia": "DROGARIA BOA SAUDE"})
        return httpx.Response(404, json={"message": "CNPJ não encontrado"})

    out = cnpj.enrich_merchants(s, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert sorted(seen) == ["11222333000144", "99888777000166"]
    assert out == {"consultados": 2, "com_cnae": 1, "nao_encontrados": 1, "erro": None}
    m = s.query(Merchant).filter_by(cnpj="11222333000144").one()
    assert (m.cnae, m.cnae_source, m.canonical_name) == ("4771701", "receita", "Drogaria Boa Saude")
    # não encontrado não é consultado de novo na próxima rodada
    seen.clear()
    cnpj.enrich_merchants(s, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert seen == []


def test_limite_de_taxa_interrompe_sem_marcar(db_reset, monkeypatch):
    from app.categorization import cnpj
    from app.models import Merchant
    monkeypatch.setattr(cnpj, "PAUSE", 0)
    s = db_reset()
    s.add(Merchant(canonical_name="X", cnpj="11222333000144"))
    s.flush()
    out = cnpj.enrich_merchants(s, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))))
    assert out["consultados"] == 0 and out["erro"]
    assert s.query(Merchant).one().enriched_at is None   # tenta de novo na próxima sincronização


def test_saude_financeira_na_massa_ficticia(synced):
    from app.analytics.plano import put_setting
    from app.analytics.saude_financeira import financial_health, snapshot_health, tier
    from app.models import Merchant
    with synced["sf"]() as s:
        # CNAE vindo da Pluggy fica no cadastro do comerciante
        energia = s.query(Merchant).filter_by(cnpj="22222222000191").one()
        assert (energia.cnae, energia.cnae_source) == ("3514000", "pluggy")
        # salário ainda não classificado: renda zero, os indicadores que dependem dela ficam "sem dado"
        sem_renda = {i["chave"]: i for i in financial_health(s)["indicadores"]}
        assert len(sem_renda) == 8 and sem_renda["gasto_renda"]["nota"] is None
    # o usuário confirma o salário na Revisão (regra por comerciante), como na vida real
    from app.api.routes_ledger import RuleBody, add_rule
    from app.services.pipeline import pipeline
    with synced["sf"]() as s:
        add_rule(s, RuleBody(field="description", operator="contains", pattern="acme consultoria", direction="in",
                             category_id="rec.salario"))
        s.commit()
    pipeline.rebuild_now("test")
    with synced["sf"]() as s:
        h = financial_health(s)
        assert 0 <= h["nota"] <= 100 and h["faixa"] == tier(h["nota"])
        ind = {i["chave"]: i for i in h["indicadores"]}
        assert len(ind) == 8 and [p["chave"] for p in h["pilares"]] == ["gastar", "poupar", "dever", "planejar"]
        assert ind["score_credito"]["nota"] is None                 # sem dado: fora da média, não zero
        assert h["medidos"] == 7
        assert ind["protecao"]["nota"] == 0                         # massa fictícia não tem seguro
        put_setting(s, "plano", {"score_credito": 720})
        h2 = financial_health(s)
        assert h2["medidos"] == 8
        assert {i["chave"]: i for i in h2["indicadores"]}["score_credito"]["nota"] == 91
        assert snapshot_health(s) == h2["nota"] and financial_health(s)["historico"][-1]["nota"] == h2["nota"]


def test_faixas_e_interpolacao():
    from app.analytics.saude_financeira import _interp, tier
    assert tier(85) == "saudavel" and tier(40) == "equilibrando" and tier(39) == "vulneravel" and tier(None) is None
    pts = [(0, 0), (1, 40), (3, 75), (6, 100)]
    assert _interp(-1, pts) == 0 and _interp(2, pts) == 57.5 and _interp(9, pts) == 100
