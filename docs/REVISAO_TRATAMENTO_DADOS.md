# Revisão do tratamento de dados (out/2026)

Leitura do fluxo **recebimento → tratamento/categorização → insights/automação**, camada por camada
(`ingestion`, `normalization`, `reconciliation`, `categorization`, `accounting`, `analytics`, `portfolio`, `tax`,
`alerts`, rotas e telas), procurando erros e números que divergem entre abas.

## Corrigido nesta revisão

| # | Camada | Problema | Efeito no usuário | Correção |
|---|---|---|---|---|
| 1 | Normalização | `local_date` convertia `AAAA-MM-DDT00:00:00Z` (data sem horário) para Brasília, recuando um dia | Lançamento do dia 1º caía no mês anterior; vencimentos de fatura/título um dia antes | Meia-noite UTC exata é tratada como data civil (`app/utils/time.py`) |
| 2 | Categorização | Mapa Pluggy com IDs de 9 dígitos (`200300000`…) para seguros | Plano de saúde nunca era reconhecido → **dedução de saúde do IRPF perdida**; seguros caíam no genérico | IDs corrigidos (`20010000`–`20040000`); bancos existentes recebem as chaves novas no próximo `seed_chart` |
| 3 | Categorização | Palavra-chave "rendimento" (juros) vinha antes de "rendimento fii" (dividendos) | Rendimento de FII classificado como juros em conta e fora dos isentos do IR | Ordem invertida |
| 4 | Categorização | Crédito em "Empréstimos e financiamentos" (Pluggy `02000000`) virava despesa financeira positiva | Empréstimo recebido **aumentava o resultado** da DRE | Entrada nessa categoria vira `LOAN_IN` (`pat.emprestimo_in`) |
| 5 | Conciliação | Pix/boleto ao CNPJ do emissor sem valor casado era sempre "cartão não conectado" (despesa) | Com o cartão daquele emissor conectado, as compras contavam **em dobro** (cartão + pagamento) | Emissores com cartão conectado são detectados pelo nome/apelido; o pagamento vira fatura a conferir |
| 6 | DFC | Usava data de competência e somava pendentes descartados (gêmeos/velhos) | Ajuste de competência mudava o caixa de mês; saldo reconstruído e "conferência" com erro | DFC por `cash_date`; eventos `pending:superseded/stale` fora de todas as somas de demonstrativo |
| 7 | Revisão | "Possível duplicidade" disparava para o pendente que o razão já tinha descartado | Falso alarme | Mesma exclusão do item 6 |
| 8 | Balanço | Histórico recuava o saldo usando fluxos de contas excluídas do patrimônio/removidas | Patrimônio histórico ≠ perímetro do saldo atual | Mesmo perímetro nos dois lados |
| 9 | Cartões | Chave de parcelamento inclui o valor; 1ª parcela com centavos diferentes virava outro plano | Parcelas futuras (Balanço, previsão, comprometimento) **contadas em dobro** | Planos da mesma compra com valores a até R$ 1/2% são unificados |
| 10 | Planejamento × DRE gerencial | Duas definições de reserva de emergência | "Meses de reserva" diferentes em cada aba | Função única `reserva_liquida`; Tesouro IPCA+/Prefixado (marcação a mercado) fora da reserva |
| 11 | Orçamento | DRE gerencial somava orçamento da mãe + filhas; Painel somava todos os padrões e ignorava os do mês | Teto em dobro / curva de orçamento errada | Regra única: orçamento próprio, senão soma das filhas; o do mês vence o padrão |
| 12 | Previsão de liquidez | Mês corrente projetado por fração de dias | Salário já recebido (e no saldo) era somado de novo | Projeta só "esperado − já realizado no mês" |
| 13 | Comerciantes | Categoria exibida = `max(category_id)` (ordem alfabética) | Categoria errada na lista | Categoria mais frequente |
| 14 | Categorias | Detalhe somava eventos de qualquer tipo (inclusive ignorados) | Valor ≠ DRE | Mesmo recorte da DRE (tipos de resultado) |
| 15 | Carteira/IR | Quantidade com custo cortada à posição atual sem cortar o custo | Preço médio inflado (Bens e Direitos, ganho de capital) | Corte proporcional |
| 16 | Carteira | `IMBB11` em ETF internacional e renda fixa; `ALUG11` (REITs EUA) como renda fixa | Alocação e risco errados | Classes corrigidas |
| 17 | IRPF | Poupança declarada como conta corrente (06-01) | Código errado | `SAVINGS_ACCOUNT` → 04-01 |
| 18 | Revisão → IRPF | Atalho "Empréstimo a amigo" gravava `pat.ignorar` | Empréstimo concedido nunca chegava a Bens e Direitos (05-01) | Usa `pat.emprestimo_concedido` |
| 19 | Categorias | API aceitava qualquer `dre_line` | Linha inválida sumia com a categoria da DRE sem aviso | Validação; tela mostra "Extraordinários" |

Testes: `tests/unit/test_tratamento_dados.py`.

## Backlog recomendado (não alterado)

**Resolvidos na segunda rodada**

1. ~~Entradas não classificadas contam como receita~~ → linha **"Entradas a classificar"** fora da receita líquida
   e do resultado recorrente (entra só no resultado total), fora da renda do *Quanto posso gastar* e da previsão
   de liquidez; o Painel mostra o valor com atalho para a Revisão.
2. ~~Regra por comerciante sem CNPJ não casa~~ → campo de regra **`merchant_id`** (Revisão, API, MCP e tela de Regras).
3. ~~Pagamento ao CNPJ de banco que não é fatura~~ → só o CNPJ não basta: exige categoria/descrição de fatura ou
   valor casado com crédito/fatura do cartão; sem isso, categorização normal.

**Média — consistência entre abas e qualidade da categorização**

4. ~~"Despesas" do Painel × "gasto médio" da DRE gerencial~~ → conceito único `SPENDING_LINES` (linhas abaixo da
   receita líquida; imposto de renda já sai da receita).
5. Médias de 6 meses (DRE gerencial, reserva) contam meses anteriores ao primeiro dado como zero → custo
   subestimado e reserva superestimada nos primeiros meses de uso (a previsão de liquidez já corta).
6. Recorrências que pararam ficam "detectadas" para sempre (lista do Planejamento, premissas da previsão).
   Recorrência sem comerciante não pode ser classificada na Revisão (só dispensada).
7. Palavras-chave ambíguas: "proventos" → salário (proventos de ações), "recarga" → celular (bilhete de
   transporte), "park"/"estacion" → estacionamento (restaurante em shopping), "clube " → assinatura,
   "residencial" → condomínio. Exigir contexto ou baixar a confiança para cair na revisão.
8. Valorização da carteira mistura snapshot real e reconstrução por proxy no mesmo mês; aporte em investimento
   fora do Open Finance aparece como desvalorização.

**Baixa**

9. IRPF: isentos de LCI/LCA/poupança (12) e rendimentos de FII prometidos no cabeçalho não são calculados.
10. Previsão de liquidez ignora novas compras parceladas (só parcelas existentes + gasto à vista médio).
11. `normalization.transaction` escolhe a contraparte pelo sinal bruto (antes da convenção de sinal do cartão).
12. Contas que somem da Pluggy nunca recebem `removed_at` (investimentos recebem).
13. Sankey: receita negativa (estorno de salário) aparece como despesa.

## Próximos passos para "insights inteligentes"

Com os itens acima resolvidos, a base fica confiável para automações que hoje faltam:

- **Orçamento sugerido** por categoria a partir da mediana de 6 meses fechados (já calculada em `category_tree`),
  com alerta de ritmo no meio do mês (o *ritmo* já existe em `safe_to_spend`).
- **Assinaturas esquecidas**: recorrência de saída sem uso/variação + aumento de preço (o detector já mede
  `amount_std`; falta comparar o último valor com a média).
- **Meta de aporte automática** que acompanha o resultado recorrente real e avisa quando o mês fecha abaixo.
- **Resumo mensal explicado** (o fechamento por e-mail): variação por categoria vs. média, com os três
  lançamentos que mais explicam a diferença.
