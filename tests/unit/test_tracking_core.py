"""Núcleo de acompanhamento: série por investimento, fluxos inferidos, qualidade de cotação e performance."""
from datetime import date, timedelta

from app.portfolio import tracking_core as T

START = date(2026, 1, 1)
DAYS = T.day_range(START, date(2026, 6, 30))


def _cdi(rate=0.0005):
    return {d: rate for d in DAYS if d.weekday() < 5}


def test_rf_recua_ate_a_aplicacao_e_comeca_nela():
    m = T.Market(cdi=_cdi())
    buy = date(2026, 2, 2)
    h = T.Holding("cdb", "CDB", T.RF, "CDI", 120.0, trades=[T.Trade(buy, 10000.0)])
    # valor observado no fim, coerente com 120% do CDI desde a aplicação
    r = T.proxy_rates(h, DAYS, m)
    v = 10000.0
    for i in range((buy - START).days + 1, len(DAYS)):
        v *= 1 + r[i]
    h.obs = {DAYS[-1]: v}
    s = T.build_series(h, DAYS, m)
    assert DAYS[s.start] == buy
    assert abs(s.v[(buy - START).days] - 10000.0) < 0.01
    assert not s.inferred_flows
    V, F = T.aggregate([s], len(DAYS))
    st = T.period_stats(DAYS, V, F, 0, len(DAYS) - 1)
    assert st["inicio_efetivo_posterior"] and abs(st["aportes_liquidos"] - 10000.0) < 0.01
    assert abs(st["ganho"] - (v - 10000.0)) < 0.05


def test_variacao_sem_movimentacao_vira_fluxo_inferido_nao_perda():
    m = T.Market(cdi=_cdi())
    d1, d2 = date(2026, 3, 2), date(2026, 3, 9)
    h = T.Holding("cdb", "CDB", T.RF, "CDI", 100.0, obs={d1: 5000.0, d2: 3000.0})  # resgate de ~2 mil não informado
    s = T.build_series(h, DAYS, m)
    assert len(s.inferred_flows) == 1 and s.inferred_flows[0][0] == d2
    V, F = T.aggregate([s], len(DAYS))
    i1, i2 = (d1 - START).days, (d2 - START).days
    st = T.period_stats(DAYS, V, F, i1, i2)
    assert 0 < st["twr"] < 0.01  # rende o CDI da semana; a saída não é perda


def test_rv_quantidade_desfeita_pelas_negociacoes():
    px = {d: 100.0 + i * 0.1 for i, d in enumerate(DAYS) if d.weekday() < 5}
    m = T.Market(prices={"XPTO11.SA": px})
    buy = date(2026, 4, 1)
    snap = date(2026, 6, 1)
    h = T.Holding("etf", "XPTO11", T.RV, "PRICE", symbol="XPTO11.SA", qty_obs={snap: 30.0},
                  trades=[T.Trade(buy, 10 * px[buy], 10.0)])
    s = T.build_series(h, DAYS, m)
    i_before = (buy - START).days - 1
    assert abs(s.v[i_before] - 20 * T.dense_price(px, DAYS)[i_before]) < 1e-6  # 30 − 10 compradas
    assert "já existia no início da janela" in s.notes


def test_cotacao_congelada_e_salto_sao_descartados():
    px = {}
    v = 50.0
    for i, d in enumerate(DAYS):
        if d.weekday() >= 5:
            continue
        if date(2026, 2, 1) <= d < date(2026, 3, 1):
            px[d] = 50.0  # congelada
        elif d >= date(2026, 3, 1):
            px[d] = 80.0 + i * 0.01  # salto
        else:
            v += 0.05
            px[d] = v
    clean, issues = T.price_quality(px, START)
    assert clean is not None and clean > date(2026, 3, 1)
    assert any("congelada" in x for x in issues) and any("salto" in x for x in issues)


def test_rv_sem_cotacao_confiavel_recua_pelo_indexador_de_referencia():
    px = {d: 100.0 for d in DAYS if d.weekday() < 5}
    m = T.Market(prices={"ETFRF11.SA": px}, ipca={(2026, k): 0.004 for k in range(1, 7)},
                 clean_from={"ETFRF11.SA": date(2026, 5, 1)})
    h = T.Holding("e", "ETFRF11", T.RV, "PRICE", symbol="ETFRF11.SA", qty_obs={date(2026, 6, 1): 10.0},
                  fallback_index="IPCA", fallback_rate=6.0)
    s = T.build_series(h, DAYS, m)
    assert s.start == 0 and s.v[0] < 1000.0  # valor antes de maio recua pelo IPCA + 6%
    assert any("indexador de referência" in n for n in s.notes)


def test_multiplicador_do_cdi_recupera_taxa_contratada():
    cdi = _cdi(0.0005)
    days = T.day_range(date(2026, 1, 5), date(2026, 6, 30))
    v = 10000.0
    for d in days[1:]:
        v *= 1 + 1.2 * cdi.get(d, 0.0)
    k = T.cdi_multiplier([(days[0], 10000.0)], days[-1], v, cdi)
    assert abs(k - 1.2) < 1e-3


def test_saida_em_transito_continua_pelo_indexador():
    m = T.Market(selic=_cdi(0.0005))
    d1, d2 = date(2026, 5, 4), date(2026, 5, 6)
    h = T.Holding("t", "Tesouro", T.RF, "SELIC", obs={d1: 1000.0, d2: 0.0}, closed=True, transit_since=d2)
    s = T.build_series(h, DAYS, m)
    assert s.v[-1] > 1000.0 and not s.inferred_flows
