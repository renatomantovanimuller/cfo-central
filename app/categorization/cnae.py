"""CNAE (Classificação Nacional de Atividades Econômicas, IBGE/Receita) → plano de contas.

O CNAE diz o ramo do estabelecimento registrado no CNPJ: é um sinal forte e barato para despesas (uma farmácia é
farmácia, venda o que vender no balcão). Vem da Pluggy (`merchant.cnae`) e, opcionalmente, da consulta pública do
CNPJ (app/categorization/cnpj.py).

Mapa por prefixo da subclasse (7 dígitos): o prefixo mais longo vence (subclasse > classe > grupo > divisão).
Só entram ramos de significado inequívoco. Instituições financeiras e meios de pagamento (64–66) ficam de fora:
um Pix para banco ou adquirente não diz o que foi comprado.
"""
from __future__ import annotations

import re

# prefixo → (categoria, confiança)
CNAE_MAP: dict[str, tuple[str, float]] = {
    # comércio varejista de alimentos
    "4711": ("alimentacao.mercado", 0.85), "4712": ("alimentacao.mercado", 0.8),
    "47211": ("alimentacao.padaria", 0.85), "4722": ("alimentacao.mercado", 0.8),
    "4723": ("alimentacao.mercado", 0.75), "47245": ("alimentacao.mercado", 0.85), "4729": ("alimentacao.mercado", 0.7),
    # alimentação fora de casa
    "5611201": ("alimentacao.restaurantes", 0.85), "5611203": ("alimentacao.restaurantes", 0.8),
    "5611204": ("alimentacao.restaurantes", 0.8), "5611205": ("alimentacao.restaurantes", 0.8),
    "5611": ("alimentacao.restaurantes", 0.8), "5612": ("alimentacao.restaurantes", 0.7),
    "5620": ("alimentacao.restaurantes", 0.6),
    # transporte
    "4731": ("transporte.combustivel", 0.9), "4732": ("transporte.combustivel", 0.8),
    "4520": ("transporte.manutencao", 0.85), "4530": ("transporte.manutencao", 0.8),
    "4543": ("transporte.manutencao", 0.7),
    "4921": ("transporte.publico", 0.85), "4922": ("transporte.publico", 0.8), "4912": ("transporte.publico", 0.85),
    "4923": ("transporte.apps", 0.85), "5223": ("transporte.estacionamento", 0.9),
    "5111": ("lazer.viagens", 0.85), "5112": ("lazer.viagens", 0.8), "4929": ("lazer.viagens", 0.6),
    # saúde
    "4771": ("saude.farmacia", 0.9), "4773": ("saude.farmacia", 0.75), "4774": ("saude.otica", 0.9),
    "8610": ("saude.consultas", 0.8), "8630504": ("saude.dentista", 0.9), "8630": ("saude.consultas", 0.85),
    "8640": ("saude.consultas", 0.85), "8650": ("saude.consultas", 0.85), "8690": ("saude.consultas", 0.75),
    "6550": ("saude.plano", 0.9), "9313": ("saude.academia", 0.9),
    # moradia e contas
    "3514": ("moradia.energia", 0.9), "3511": ("moradia.energia", 0.8), "3600": ("moradia.agua", 0.9),
    "3701": ("moradia.agua", 0.8), "3520": ("moradia.gas", 0.9), "8112": ("moradia.condominio", 0.9),
    "6822": ("moradia.aluguel", 0.7), "6821": ("moradia.aluguel", 0.6),
    "4744": ("moradia.manutencao", 0.8), "4742": ("moradia.manutencao", 0.75), "4741": ("moradia.manutencao", 0.75),
    "4743": ("moradia.manutencao", 0.75), "4754": ("moradia.eletro", 0.8), "4753": ("compras.eletronicos", 0.75),
    "4755": ("moradia.casa", 0.75), "4759": ("moradia.casa", 0.75), "4757": ("moradia.eletro", 0.7),
    "8121": ("moradia.manutencao", 0.7), "8122": ("moradia.manutencao", 0.7),
    # telecom
    "6120": ("servicos.celular", 0.8), "6110": ("moradia.internet", 0.8), "6141": ("moradia.internet", 0.8),
    "6142": ("moradia.internet", 0.8), "6143": ("moradia.internet", 0.8), "6190": ("moradia.internet", 0.65),
    # seguros (não-saúde)
    "6511": ("servicos.seguros", 0.85), "6512": ("servicos.seguros", 0.85),
    # educação
    "8511": ("educacao.faculdade", 0.85), "8512": ("educacao.faculdade", 0.85), "8513": ("educacao.faculdade", 0.85),
    "8520": ("educacao.faculdade", 0.85), "8531": ("educacao.faculdade", 0.85), "8532": ("educacao.faculdade", 0.85),
    "8533": ("educacao.faculdade", 0.85), "8541": ("educacao.faculdade", 0.8), "8542": ("educacao.faculdade", 0.8),
    "8591": ("educacao.cursos", 0.8), "8592": ("educacao.cursos", 0.8), "8593": ("educacao.cursos", 0.85),
    "8599": ("educacao.cursos", 0.8), "4761": ("educacao.livros", 0.85),
    # lazer e viagens
    "5510": ("lazer.viagens", 0.9), "5590": ("lazer.viagens", 0.8), "7911": ("lazer.viagens", 0.9),
    "7912": ("lazer.viagens", 0.85), "5914": ("lazer.eventos", 0.85), "9001": ("lazer.eventos", 0.85),
    "9003": ("lazer.eventos", 0.7), "9102": ("lazer.eventos", 0.75), "9321": ("lazer.eventos", 0.8),
    "9329": ("lazer.outros", 0.7), "9200": ("lazer.apostas", 0.9), "4763": ("lazer.hobbies", 0.75),
    "9311": ("lazer.hobbies", 0.7), "9319": ("lazer.hobbies", 0.65),
    # cuidados, compras, pets
    "9602": ("cuidados", 0.9), "4772": ("cuidados", 0.8),
    "4781": ("compras.vestuario", 0.85), "4782": ("compras.vestuario", 0.85), "4783": ("compras.vestuario", 0.7),
    "4751": ("compras.eletronicos", 0.8), "4752": ("compras.eletronicos", 0.8), "9511": ("compras.eletronicos", 0.7),
    "4713": ("compras.diversos", 0.6), "4762": ("lazer.hobbies", 0.6), "4789004": ("pets", 0.85),
    "7500": ("pets", 0.9),
    # assinaturas digitais e software
    "6311": ("assinaturas.software", 0.65), "6319": ("assinaturas.outros", 0.55),
    "6021": ("assinaturas.streaming", 0.55), "6022": ("assinaturas.streaming", 0.6),
    "6201": ("assinaturas.software", 0.6), "6202": ("assinaturas.software", 0.6),
    "6203": ("assinaturas.software", 0.65),
    # entidades e poder público
    "9491": ("doacoes", 0.75), "9430": ("doacoes", 0.65), "8411": ("impostos.outros", 0.6),
}

_DIGITS = re.compile(r"\D")


def norm_cnae(code: str | int | None) -> str | None:
    """'4711-3/02' ou 4711302 → '4711302' (subclasse com 7 dígitos)."""
    if code is None:
        return None
    d = _DIGITS.sub("", str(code))
    if not d:
        return None
    return d.zfill(7) if len(d) <= 7 else d[:7]


def cnae_category(code: str | int | None) -> tuple[str, float, str] | None:
    """(categoria, confiança, prefixo casado) pelo prefixo mais longo, ou None."""
    d = norm_cnae(code)
    if not d:
        return None
    for n in (7, 5, 4):
        hit = CNAE_MAP.get(d[:n])
        if hit:
            return hit[0], hit[1], d[:n]
    return None
