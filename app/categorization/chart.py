"""Plano de contas pessoal (seed) e mapa de categorias Pluggy → plano próprio.

dre_line: receita_operacional | outras_receitas | impostos_renda | essenciais | estilo_vida | terceiros |
          receitas_financeiras | despesas_financeiras | nao_classificado | None (patrimonial)
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Category, PluggyCategoryMap

# (id, parent, nome, natureza, linha DRE, essencial, tipo de evento padrão, cor)
CHART: list[tuple] = [
    # Receitas
    ("rec", None, "Receitas", "receita", "receita_operacional", False, "INCOME", "#16a34a"),
    ("rec.salario", "rec", "Salário / bolsa", "receita", "receita_operacional", False, "INCOME", None),
    ("rec.bonus", "rec", "Bônus / PLR", "receita", "receita_operacional", False, "INCOME", None),
    ("rec.freela", "rec", "Freelance / serviços", "receita", "receita_operacional", False, "INCOME", None),
    ("rec.beneficios", "rec", "Benefícios e auxílios", "receita", "receita_operacional", False, "INCOME", None),
    ("rec.presentes", "rec", "Presentes recebidos", "receita", "outras_receitas", False, "INCOME", None),
    ("rec.vendas", "rec", "Venda de bens", "receita", "outras_receitas", False, "INCOME", None),
    ("rec.pix_terceiros", "rec", "Recebido de terceiros (a classificar)", "receita", "outras_receitas", False, "INCOME", None),
    ("rec.heranca", "rec", "Herança e doações recebidas", "receita", "extraordinarios", False, "INCOME", None),
    ("rec.outras", "rec", "Outras receitas", "receita", "outras_receitas", False, "INCOME", None),
    # Receitas financeiras
    ("finrec", None, "Receitas financeiras", "financeiro", "receitas_financeiras", False, "INVESTMENT_INCOME", "#0d9488"),
    ("finrec.dividendos", "finrec", "Dividendos e JCP", "financeiro", "receitas_financeiras", False, "INVESTMENT_INCOME", None),
    ("finrec.juros", "finrec", "Juros e rendimentos em conta", "financeiro", "receitas_financeiras", False, "INVESTMENT_INCOME", None),
    ("finrec.cashback", "finrec", "Cashback e recompensas", "financeiro", "receitas_financeiras", False, "INVESTMENT_INCOME", None),
    # Moradia
    ("moradia", None, "Moradia", "despesa", "essenciais", True, "EXPENSE", "#2563eb"),
    ("moradia.aluguel", "moradia", "Aluguel", "despesa", "essenciais", True, "EXPENSE", None),
    ("moradia.condominio", "moradia", "Condomínio", "despesa", "essenciais", True, "EXPENSE", None),
    ("moradia.energia", "moradia", "Energia", "despesa", "essenciais", True, "EXPENSE", None),
    ("moradia.agua", "moradia", "Água", "despesa", "essenciais", True, "EXPENSE", None),
    ("moradia.gas", "moradia", "Gás", "despesa", "essenciais", True, "EXPENSE", None),
    ("moradia.internet", "moradia", "Internet e TV", "despesa", "essenciais", True, "EXPENSE", None),
    ("moradia.manutencao", "moradia", "Manutenção e reparos", "despesa", "essenciais", True, "EXPENSE", None),
    ("moradia.casa", "moradia", "Utensílios e casa", "despesa", "essenciais", True, "EXPENSE", None),
    ("moradia.eletro", "moradia", "Eletrodomésticos e móveis", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("moradia.iptu", "moradia", "IPTU", "despesa", "essenciais", True, "EXPENSE", None),
    ("moradia.outros", "moradia", "Moradia – outros", "despesa", "essenciais", True, "EXPENSE", None),
    # Alimentação
    ("alimentacao", None, "Alimentação", "despesa", "essenciais", True, "EXPENSE", "#ea580c"),
    ("alimentacao.mercado", "alimentacao", "Supermercado", "despesa", "essenciais", True, "EXPENSE", None),
    ("alimentacao.restaurantes", "alimentacao", "Restaurantes e bares", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("alimentacao.delivery", "alimentacao", "Delivery", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("alimentacao.padaria", "alimentacao", "Padaria e café", "despesa", "estilo_vida", False, "EXPENSE", None),
    # Transporte
    ("transporte", None, "Transporte", "despesa", "essenciais", True, "EXPENSE", "#7c3aed"),
    ("transporte.apps", "transporte", "Apps e táxi", "despesa", "essenciais", True, "EXPENSE", None),
    ("transporte.publico", "transporte", "Transporte público", "despesa", "essenciais", True, "EXPENSE", None),
    ("transporte.combustivel", "transporte", "Combustível", "despesa", "essenciais", True, "EXPENSE", None),
    ("transporte.estacionamento", "transporte", "Estacionamento e pedágio", "despesa", "essenciais", True, "EXPENSE", None),
    ("transporte.manutencao", "transporte", "Manutenção do veículo", "despesa", "essenciais", True, "EXPENSE", None),
    ("transporte.seguro_impostos", "transporte", "Seguro, IPVA e taxas", "despesa", "essenciais", True, "EXPENSE", None),
    ("transporte.outros", "transporte", "Transporte – outros", "despesa", "essenciais", True, "EXPENSE", None),
    # Saúde
    ("saude", None, "Saúde", "despesa", "essenciais", True, "EXPENSE", "#dc2626"),
    ("saude.farmacia", "saude", "Farmácia", "despesa", "essenciais", True, "EXPENSE", None),
    ("saude.plano", "saude", "Plano de saúde", "despesa", "essenciais", True, "EXPENSE", None),
    ("saude.consultas", "saude", "Consultas e exames", "despesa", "essenciais", True, "EXPENSE", None),
    ("saude.dentista", "saude", "Dentista", "despesa", "essenciais", True, "EXPENSE", None),
    ("saude.otica", "saude", "Ótica", "despesa", "essenciais", True, "EXPENSE", None),
    ("saude.academia", "saude", "Academia e esportes", "despesa", "estilo_vida", False, "EXPENSE", None),
    # Educação
    ("educacao", None, "Educação", "despesa", "essenciais", True, "EXPENSE", "#0891b2"),
    ("educacao.faculdade", "educacao", "Faculdade e escola", "despesa", "essenciais", True, "EXPENSE", None),
    ("educacao.cursos", "educacao", "Cursos e certificações", "despesa", "essenciais", True, "EXPENSE", None),
    ("educacao.livros", "educacao", "Livros e material", "despesa", "essenciais", True, "EXPENSE", None),
    # Contas e serviços
    ("servicos", None, "Contas e serviços", "despesa", "essenciais", True, "EXPENSE", "#475569"),
    ("servicos.celular", "servicos", "Celular", "despesa", "essenciais", True, "EXPENSE", None),
    ("servicos.seguros", "servicos", "Seguros", "despesa", "essenciais", True, "EXPENSE", None),
    ("servicos.outros", "servicos", "Serviços – outros", "despesa", "essenciais", True, "EXPENSE", None),
    # Estilo de vida
    ("lazer", None, "Lazer", "despesa", "estilo_vida", False, "EXPENSE", "#db2777"),
    ("lazer.eventos", "lazer", "Eventos, cinema e shows", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("lazer.viagens", "lazer", "Viagens", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("lazer.hobbies", "lazer", "Hobbies e esportes", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("lazer.jogos", "lazer", "Jogos", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("lazer.apostas", "lazer", "Apostas", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("lazer.outros", "lazer", "Lazer – outros", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("compras", None, "Compras", "despesa", "estilo_vida", False, "EXPENSE", "#ca8a04"),
    ("compras.vestuario", "compras", "Vestuário", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("compras.eletronicos", "compras", "Eletrônicos", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("compras.online", "compras", "Compras online", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("compras.presentes", "compras", "Presentes", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("compras.diversos", "compras", "Compras diversas", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("assinaturas", None, "Assinaturas e digitais", "despesa", "estilo_vida", False, "EXPENSE", "#4f46e5"),
    ("assinaturas.streaming", "assinaturas", "Streaming de vídeo", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("assinaturas.musica", "assinaturas", "Música", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("assinaturas.software", "assinaturas", "Software e nuvem", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("assinaturas.outros", "assinaturas", "Serviços digitais – outros", "despesa", "estilo_vida", False, "EXPENSE", None),
    ("cuidados", None, "Cuidados pessoais", "despesa", "estilo_vida", False, "EXPENSE", "#be185d"),
    ("pets", None, "Pets", "despesa", "estilo_vida", False, "EXPENSE", "#65a30d"),
    ("doacoes", None, "Doações", "despesa", "estilo_vida", False, "EXPENSE", "#64748b"),
    ("saques", None, "Saques em dinheiro", "despesa", "estilo_vida", False, "EXPENSE", "#78716c"),
    # Terceiros
    ("terceiros", None, "Transferências a terceiros", "despesa", "terceiros", False, "EXPENSE", "#a855f7"),
    ("terceiros.pf", "terceiros", "Pix/TED para pessoa física", "despesa", "terceiros", False, "EXPENSE", None),
    ("terceiros.pj", "terceiros", "Pix/boleto para empresa", "despesa", "terceiros", False, "EXPENSE", None),
    ("terceiros.cartao_externo", "terceiros", "Fatura de cartão não conectado", "despesa", "terceiros", False, "EXPENSE", None),
    ("terceiros.racha", "terceiros", "Racha de contas (líquido)", "despesa", "terceiros", False, "EXPENSE", None),
    # Impostos
    ("impostos", None, "Impostos", "imposto", "impostos_renda", True, "TAX", "#991b1b"),
    ("impostos.ir", "impostos", "Imposto de renda", "imposto", "impostos_renda", True, "TAX", None),
    ("impostos.outros", "impostos", "Outros impostos e obrigações", "imposto", "impostos_renda", True, "TAX", None),
    # Despesas financeiras
    ("findesp", None, "Despesas financeiras", "financeiro", "despesas_financeiras", False, "FINANCIAL_EXPENSE", "#b91c1c"),
    ("findesp.juros", "findesp", "Juros e encargos", "financeiro", "despesas_financeiras", False, "FINANCIAL_EXPENSE", None),
    ("findesp.iof", "findesp", "IOF", "financeiro", "despesas_financeiras", False, "FINANCIAL_EXPENSE", None),
    ("findesp.tarifas", "findesp", "Tarifas bancárias", "financeiro", "despesas_financeiras", False, "FINANCIAL_EXPENSE", None),
    ("findesp.multas", "findesp", "Multas", "financeiro", "despesas_financeiras", False, "FINANCIAL_EXPENSE", None),
    # Patrimoniais (fora da DRE)
    ("pat", None, "Movimentos patrimoniais", "patrimonial", None, False, None, "#94a3b8"),
    ("pat.transferencia", "pat", "Transferência entre contas", "patrimonial", None, False, "INTERNAL_TRANSFER", None),
    ("pat.conta_externa", "pat", "Conta própria não conectada", "patrimonial", None, False, "EXTERNAL_OWN_TRANSFER", None),
    ("pat.fatura", "pat", "Pagamento de fatura", "patrimonial", None, False, "CARD_PAYMENT", None),
    ("pat.aporte", "pat", "Aporte em investimentos", "patrimonial", None, False, "INVESTMENT_CONTRIBUTION", None),
    ("pat.resgate", "pat", "Resgate de investimentos", "patrimonial", None, False, "INVESTMENT_REDEMPTION", None),
    ("pat.emprestimo_in", "pat", "Empréstimo recebido", "patrimonial", None, False, "LOAN_IN", None),
    ("pat.emprestimo_pg", "pat", "Pagamento de empréstimo", "patrimonial", None, False, "LOAN_PAYMENT", None),
    ("pat.emprestimo_concedido", "pat", "Empréstimo a terceiros (concedido/devolvido)", "patrimonial", None, False, "IGNORE", None),
    ("pat.ignorar", "pat", "Ignorar", "patrimonial", None, False, "IGNORE", None),
    ("nc", None, "A classificar", "despesa", "nao_classificado", False, "EXPENSE", "#9ca3af"),
]

# categoria Pluggy → (categoria própria, confiança)
PLUGGY_MAP: dict[str, tuple[str, float]] = {
    "01000000": ("rec.outras", .55), "01010000": ("rec.salario", .85), "01020000": ("rec.outras", .7),
    "01030000": ("rec.freela", .7), "01040000": ("rec.beneficios", .8), "01050000": ("rec.outras", .6),
    "02000000": ("findesp.juros", .6), "02010000": ("findesp.juros", .85), "02020000": ("findesp.juros", .85),
    "02030000": ("pat.emprestimo_pg", .6), "02030001": ("pat.emprestimo_pg", .75),
    "02030002": ("pat.emprestimo_pg", .75), "02030003": ("pat.emprestimo_pg", .75),
    "02040000": ("pat.emprestimo_pg", .55),
    "03000000": ("pat.aporte", .8), "03010000": ("pat.aporte", .85), "03020000": ("pat.aporte", .85),
    "03030000": ("pat.aporte", .85), "03040000": ("pat.aporte", .85), "03050000": ("pat.aporte", .7),
    "03060000": ("finrec.dividendos", .85), "03070000": ("pat.aporte", .75),
    "04000000": ("pat.transferencia", .8), "04010000": ("pat.transferencia", .8),
    "04020000": ("pat.transferencia", .8), "04030000": ("pat.transferencia", .8),
    "05000000": ("terceiros.pf", .35), "05010000": ("terceiros.pj", .45), "05020000": ("saques", .7),
    "05030000": ("terceiros.pf", .4), "05040000": ("terceiros.pf", .4), "05050000": ("compras.diversos", .4),
    "05060000": ("terceiros.pf", .4), "05070000": ("terceiros.pf", .4), "05080000": ("terceiros.pf", .4),
    "05090000": ("terceiros.pf", .4), "05090001": ("terceiros.pj", .5), "05090002": ("compras.diversos", .5),
    "05090003": ("terceiros.pf", .4), "05090004": ("terceiros.pf", .4), "05090005": ("terceiros.pf", .4),
    "05100000": ("pat.fatura", .8),
    "06000000": ("impostos.outros", .6), "06010000": ("pat.ignorar", .5), "06020000": ("servicos.outros", .7),
    "07000000": ("servicos.outros", .45), "07010000": ("servicos.celular", .75), "07010001": ("moradia.internet", .85),
    "07010002": ("servicos.celular", .85), "07010003": ("moradia.internet", .8), "07020000": ("educacao.cursos", .7),
    "07020001": ("educacao.cursos", .85), "07020002": ("educacao.faculdade", .9), "07020003": ("educacao.faculdade", .85),
    "07020004": ("educacao.faculdade", .85), "07030000": ("saude.academia", .7), "07030001": ("saude.academia", .9),
    "07030002": ("lazer.hobbies", .8), "07030003": ("cuidados", .7), "07040000": ("lazer.eventos", .8),
    "07040001": ("lazer.eventos", .85), "07040002": ("lazer.eventos", .85), "07040003": ("lazer.eventos", .85),
    "08000000": ("compras.diversos", .5), "08010000": ("compras.online", .75), "08020000": ("compras.eletronicos", .85),
    "08030000": ("pets", .9), "08040000": ("compras.vestuario", .9), "08050000": ("compras.diversos", .7),
    "08060000": ("educacao.livros", .8), "08070000": ("lazer.hobbies", .7), "08080000": ("compras.diversos", .7),
    "08090000": ("finrec.cashback", .9),
    "09000000": ("assinaturas.outros", .6), "09010000": ("lazer.jogos", .85), "09020000": ("assinaturas.streaming", .9),
    "09030000": ("assinaturas.musica", .9),
    "10000000": ("alimentacao.mercado", .85),
    "11000000": ("alimentacao.restaurantes", .6), "11010000": ("alimentacao.restaurantes", .85),
    "11020000": ("alimentacao.delivery", .9),
    "12000000": ("lazer.viagens", .8), "12010000": ("lazer.viagens", .85), "12020000": ("lazer.viagens", .85),
    "12030000": ("lazer.viagens", .75), "12040000": ("lazer.viagens", .75),
    "13000000": ("doacoes", .85),
    "14000000": ("lazer.apostas", .85), "14010000": ("lazer.apostas", .9), "14020000": ("lazer.apostas", .9),
    "15000000": ("impostos.outros", .7), "15010000": ("impostos.ir", .9), "15020000": ("impostos.ir", .8),
    "15030000": ("findesp.iof", .9),
    "16000000": ("findesp.tarifas", .9), "16010000": ("findesp.tarifas", .9), "16020000": ("findesp.tarifas", .9),
    "16030000": ("findesp.tarifas", .9),
    "17000000": ("moradia.outros", .55), "17010000": ("moradia.aluguel", .9), "17020000": ("moradia.energia", .5),
    "17020001": ("moradia.agua", .9), "17020002": ("moradia.energia", .9), "17020003": ("moradia.gas", .9),
    "17030000": ("moradia.casa", .8), "17040000": ("moradia.iptu", .9),
    "18000000": ("saude.consultas", .6), "18010000": ("saude.dentista", .9), "18020000": ("saude.farmacia", .9),
    "18030000": ("saude.otica", .9), "18040000": ("saude.consultas", .9),
    "19000000": ("transporte.outros", .55), "19010000": ("transporte.apps", .9), "19020000": ("transporte.publico", .9),
    "19030000": ("transporte.outros", .8), "19040000": ("transporte.outros", .8), "19050000": ("transporte.manutencao", .6),
    "19050001": ("transporte.combustivel", .85), "19050002": ("transporte.estacionamento", .9),
    "19050003": ("transporte.estacionamento", .9), "19050004": ("transporte.seguro_impostos", .9),
    "19050005": ("transporte.manutencao", .9), "19050006": ("findesp.multas", .9),
    "20000000": ("servicos.seguros", .85), "20010000": ("servicos.seguros", .9), "20020000": ("servicos.seguros", .9),
    "20030000": ("saude.plano", .9), "20040000": ("transporte.seguro_impostos", .9),
    "21000000": ("lazer.outros", .6),
    "99999999": ("nc", .2),
}

DRE_LINES = [
    ("receita_operacional", "Receita operacional", 1),
    ("outras_receitas", "Outras receitas", 1),
    ("impostos_renda", "Impostos sobre a renda", -1),
    ("essenciais", "Custo de vida essencial", -1),
    ("estilo_vida", "Estilo de vida", -1),
    ("terceiros", "Transferências a terceiros", -1),
    ("nao_classificado", "A classificar", -1),
    ("receitas_financeiras", "Receitas financeiras", 1),
    ("despesas_financeiras", "Despesas financeiras", -1),
    ("extraordinarios", "Itens extraordinários", 1),
]

# ajustes em categorias de sistema já gravadas (id, campo, valor antigo, valor novo): rodam uma vez, sem
# tocar no que o usuário tenha mudado para outro valor
CATEGORY_UPGRADES = [
    ("rec.heranca", "dre_line", "outras_receitas", "extraordinarios"),
]


def seed_chart(s: Session) -> None:
    """Idempotente: cria categorias do sistema que faltam e o mapa Pluggy, sem tocar no que o usuário editou."""
    existing = {c.id for c in s.query(Category.id)}
    for i, (cid, parent, name, nature, dre, essential, etype, color) in enumerate(CHART):
        if cid in existing:
            continue
        s.add(Category(id=cid, parent_id=parent, name=name, nature=nature, dre_line=dre, essential=essential,
                       default_event_type=etype, color=color, sort=i, is_system=True,
                       dfc_section=None if nature == "patrimonial" else "operacional"))
    s.flush()
    for cid, field, old, new in CATEGORY_UPGRADES:
        c = s.get(Category, cid)
        if c is not None and getattr(c, field) == old:
            setattr(c, field, new)
    mapped = {m.pluggy_category_id for m in s.query(PluggyCategoryMap.pluggy_category_id)}
    for pid, (cid, conf) in PLUGGY_MAP.items():
        if pid not in mapped:
            s.add(PluggyCategoryMap(pluggy_category_id=pid, category_id=cid, confidence=conf))
    s.flush()


# MCC (ISO 18245) → categoria, para compras no cartão. Só códigos de significado inequívoco.
def _mcc(codes, cat, conf):
    return {c: (cat, conf) for c in codes}


MCC_MAP: dict[int, tuple[str, float]] = {
    **_mcc([5411, 5422, 5441, 5451, 5921, 5300], "alimentacao.mercado", 0.85),
    **_mcc([5462], "alimentacao.padaria", 0.88),
    **_mcc([5812, 5813], "alimentacao.restaurantes", 0.85),
    **_mcc([5814], "alimentacao.restaurantes", 0.8),
    **_mcc([5541, 5542, 5983], "transporte.combustivel", 0.9),
    **_mcc([4121], "transporte.apps", 0.9),
    **_mcc([4111, 4131], "transporte.publico", 0.85),
    **_mcc([7523], "transporte.estacionamento", 0.9),
    **_mcc([5533, 7538, 7542, 7531], "transporte.manutencao", 0.85),
    **_mcc([5912], "saude.farmacia", 0.9),
    **_mcc([8011, 8031, 8041, 8042, 8049, 8050, 8062, 8071, 8099], "saude.consultas", 0.85),
    **_mcc([8021], "saude.dentista", 0.9),
    **_mcc([7997, 7941], "saude.academia", 0.8),
    **_mcc([7230, 7298, 5977], "cuidados", 0.88),
    **_mcc([5995, 742], "pets", 0.9),
    **_mcc([5732, 5045, 5946], "compras.eletronicos", 0.82),
    **_mcc([5722], "moradia.eletro", 0.85),
    **_mcc([5200, 5211, 5231, 5251, 5712, 5719, 5039], "moradia.casa", 0.8),
    **_mcc([5611, 5621, 5631, 5641, 5651, 5661, 5691, 5699], "compras.vestuario", 0.82),
    **_mcc([5942], "educacao.livros", 0.85),
    **_mcc([8220], "educacao.faculdade", 0.85),
    **_mcc([8211, 8241, 8244, 8249, 8299], "educacao.cursos", 0.8),
    **_mcc([7832, 7922, 7929, 7991], "lazer.eventos", 0.85),
    **_mcc([7994], "lazer.jogos", 0.85),
    **_mcc([7995, 7800, 7801, 7802], "lazer.apostas", 0.92),
    **_mcc([4511, 4722, 7011, 3501], "lazer.viagens", 0.82),
    **_mcc([4812, 4814], "servicos.celular", 0.75),
    **_mcc([4900], "moradia.energia", 0.75),
    **_mcc([6300], "servicos.seguros", 0.85),
}
