"""Motor de categorização: regras do usuário, comerciantes aprendidos, mapa Pluggy e heurísticas."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from app.categorization.text import counterparty_from_description, merchant_alias, norm
from app.models import CategoryRule


@dataclass
class TxView:
    id: str
    account_id: str
    item_id: str
    account_type: str
    date: object
    flow: float
    description: str
    description_raw: str | None
    pluggy_cat: str | None
    merchant_name: str | None
    merchant_cnpj: str | None
    mcc: int | None
    payment_method: str | None
    counterparty_name: str | None
    counterparty_doc: str | None
    payer_doc: str | None
    receiver_doc: str | None
    status: str | None
    installment_number: int | None
    total_installments: int | None
    removed: bool
    merchant_cnae: str | None = None  # subclasse CNAE (7 dígitos) do estabelecimento, quando informada

    @property
    def text(self) -> str:
        return norm(f"{self.description or ''} {self.description_raw or ''}")

    @property
    def party_doc(self) -> str | None:
        return self.merchant_cnpj or self.counterparty_doc

    @property
    def party_name(self) -> str | None:
        return self.merchant_name or self.counterparty_name


@dataclass
class Decision:
    category_id: str | None = None
    event_type: str | None = None
    rule_source: str = "default"
    rule_id: str | None = None
    confidence: float = 0.1
    review: list[str] = field(default_factory=list)
    transfer_id: int | None = None
    merchant_id: int | None = None


# ----------------------------------------------------------------- regras do usuário
@dataclass
class CompiledRule:
    rule: CategoryRule
    regex: re.Pattern | None


def compile_rules(rules: Iterable[CategoryRule]) -> list[CompiledRule]:
    out = []
    for r in sorted(rules, key=lambda r: (r.priority, -len(r.pattern or ""), r.id)):
        if not r.active:
            continue
        rx = None
        if r.operator == "regex":
            try:
                rx = re.compile(r.pattern, re.I)
            except re.error:
                continue
        out.append(CompiledRule(r, rx))
    return out


def _field_value(tx: TxView, fld: str, merchant_id: int | None = None) -> str:
    return {
        "merchant_id": str(merchant_id) if merchant_id is not None else "",
        "description": tx.text,
        "merchant": norm(tx.party_name),
        "cnpj": tx.party_doc or "",
        "counterparty_doc": tx.counterparty_doc or "",
        "pluggy_category": tx.pluggy_cat or "",
        "mcc": str(tx.mcc or ""),
        "account": tx.account_id,
    }.get(fld, tx.text)


EXACT_FIELDS = ("cnpj", "counterparty_doc", "account", "pluggy_category", "mcc", "merchant_id")


def match_rule(tx: TxView, rules: list[CompiledRule], merchant_id: int | None = None) -> CategoryRule | None:
    """`merchant_id`: comerciante já resolvido do lançamento (regras por comerciante, inclusive sem CNPJ)."""
    for cr in rules:
        r = cr.rule
        if r.direction == "in" and tx.flow <= 0 or r.direction == "out" and tx.flow >= 0:
            continue
        if r.account_id and r.account_id != tx.account_id:
            continue
        amt = abs(tx.flow)
        if r.amount_min is not None and amt < r.amount_min or r.amount_max is not None and amt > r.amount_max:
            continue
        val = _field_value(tx, r.field, merchant_id)
        pat = r.pattern.strip() if r.field in EXACT_FIELDS else norm(r.pattern)
        if r.field in ("cnpj", "counterparty_doc"):
            pat = re.sub(r"\D", "", pat)
        ok = (cr.regex.search(val) is not None if cr.regex else
              val == pat if r.operator == "equals" else
              val.startswith(pat) if r.operator == "starts" else
              pat in val)
        if ok:
            return r
    return None


# ----------------------------------------------------------------- heurísticas por palavra-chave
KEYWORDS: list[tuple[str, str, float, str | None]] = [
    # (regex sobre texto normalizado, categoria, confiança, sentido exigido)
    (r"barbearia|barber|\bbarbe?r? ?shop|salao de beleza|cabeleireir", "cuidados", .9, "out"),
    (r"brasilcap|capitalizacao", "rec.outras", .7, "in"),
    # intermediadores de pagamento usados por casas de aposta
    (r"pay4fun|we ?pay ?out|gowd instituicao|sol servicos de intermediacao|suitpay|paag instituicao", "lazer.apostas", .85, "out"),
    (r"uber ?eats|ifood|ifd\b|rappi|ze delivery|aiqfome|james delivery", "alimentacao.delivery", .9, "out"),
    (r"\buber\b|\b99 ?(app|pop|tecnologia)\b|cabify|indriver|\btaxi\b", "transporte.apps", .9, "out"),
    (r"netflix|disney|hbo|\bmax\b|prime video|globoplay|paramount|crunchyroll|apple tv", "assinaturas.streaming", .9, "out"),
    (r"spotify|deezer|apple music|youtube ?premium|tidal", "assinaturas.musica", .9, "out"),
    (r"openai|chatgpt|anthropic|claude|github|\baws\b|amazon web|google ?(cloud|one|storage)|microsoft|adobe|icloud|notion|dropbox|canva|cursor", "assinaturas.software", .9, "out"),
    (r"melimais|meli ?\+|meli mais|amazon prime|prime anual|clube ", "assinaturas.outros", .85, "out"),
    (r"nucel|plano (de )?celular|recarga", "servicos.celular", .9, "out"),
    (r"imoveis|imobiliaria|locacoes|quinto ?andar|aluguel", "moradia.aluguel", .85, "out"),
    (r"edificio|condominio|residencial", "moradia.condominio", .8, "out"),
    (r"shpp|shopee", "compras.online", .85, "out"),
    (r"amazon|mercado ?livre|mercadolivre|shopee|aliexpress|magalu|magazine luiza|shein|americanas|temu", "compras.online", .7, "out"),
    (r"savegnago|tonin|carrefour|assai|atacad|pao de acucar|supermerc|mercadinho|hortifruti|sams club|dia brasil|oba hort", "alimentacao.mercado", .8, "out"),
    (r"padaria|panific|confeitaria|starbucks|cafeteria|\bcafe\b|kopenhagen|cacau show", "alimentacao.padaria", .7, "out"),
    (r"restaurante|lanchonete|burger|pizza|sushi|churrasc|outback|mcdonald|bk |madero|bar e |boteco|choperia", "alimentacao.restaurantes", .7, "out"),
    (r"\bposto\b|shell|ipiranga|petrobras|br mania|combustiv|auto posto", "transporte.combustivel", .8, "out"),
    (r"estacion|\bpark\b|sem parar|conectcar|veloe|zul digital|pedagio", "transporte.estacionamento", .8, "out"),
    (r"drogasil|\braia\b|pacheco|pague menos|drogaria|farmac|droga ?sil|panvel|nissei", "saude.farmacia", .85, "out"),
    (r"smart ?fit|bluefit|academia|gympass|wellhub|totalpass|crossfit", "saude.academia", .85, "out"),
    (r"steam|playstation|psn|xbox|nintendo|epic games|riot|blizzard|ea games|hoyoverse", "lazer.jogos", .85, "out"),
    (r"ingresso|sympla|eventim|ticket|cinemark|cinepolis|kinoplex|uci ", "lazer.eventos", .8, "out"),
    (r"airbnb|booking|latam|\bgol\b|\bazul\b|decolar|123 ?milhas|hotel|pousada|buser|clickbus", "lazer.viagens", .75, "out"),
    (r"\bclaro\b|\bvivo\b|\btim\b|telefonica", "servicos.celular", .6, "out"),
    (r"cpfl|enel|cemig|copel|celesc|energisa|equatorial|neoenergia|eletropaulo|\blight\b", "moradia.energia", .85, "out"),
    (r"sabesp|saerp|daerp|sanasa|copasa|sanepar|embasa|cedae", "moradia.agua", .85, "out"),
    (r"petz|cobasi|pet ?shop|veterin", "pets", .85, "out"),
    (r"\biof\b", "findesp.iof", .9, "out"),
    (r"juros|encargo|mora\b|rotativo", "findesp.juros", .8, "out"),
    (r"tarifa|anuidade|cesta de servicos", "findesp.tarifas", .8, "out"),
    (r"darf|receita federal|imposto de renda|\birpf\b", "impostos.ir", .8, "out"),
    (r"\bipva\b|detran|licenciamento", "transporte.seguro_impostos", .85, "out"),
    (r"saque", "saques", .8, "out"),
    # dividendos antes de "rendimento": "rendimento fii" é provento (isento no IR), não juros em conta
    (r"dividendo|jcp|juros sobre capital|rendimento fii", "finrec.dividendos", .85, "in"),
    (r"salario|folha de pagamento|proventos|bolsa estagio|bolsa-auxilio|bolsa auxilio", "rec.salario", .8, "in"),
    (r"rendimento|remuneracao da conta|juros sobre saldo", "finrec.juros", .6, "in"),
    (r"cashback|recompensa", "finrec.cashback", .8, "in"),
]
_KW = [(re.compile(rx), cat, conf, d) for rx, cat, conf, d in KEYWORDS]


def keyword_category(tx: TxView, direction: str | None = None) -> tuple[str, float] | None:
    text = f"{tx.text} {norm(tx.party_name)}"
    direction = direction or ("in" if tx.flow > 0 else "out")
    for rx, cat, conf, d in _KW:
        if d and d != direction:
            continue
        if rx.search(text):
            return cat, conf
    return None


def merchant_key(tx: TxView) -> tuple[str, str] | None:
    """(tipo, chave): doc (CNPJ/CPF) quando houver, senão alias da descrição."""
    doc = tx.party_doc
    if doc and len(doc) in (11, 14):
        return "doc", doc
    alias = merchant_alias(tx.merchant_name or tx.counterparty_name
                           or counterparty_from_description(tx.description) or tx.description)
    return ("alias", alias) if alias else None
