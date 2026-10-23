# Ideias de evolução — planejamento, controle de gastos e investimentos (out/2026)

Pesquisa em literatura acadêmica, padrões de mercado e regulação brasileira, traduzida em funcionalidades para o
CFO Central. Cada ideia traz **evidência**, **como implementar aqui** (com o ponto do código que já ajuda) e
**prioridade**. Princípio mantido da SPEC: o app mede, explica e sugere; não move dinheiro nem recomenda produto.

> Sobre a força da evidência: vários estudos citados são observacionais ou de um único grupo de autores.
> Isso está indicado em cada item. O desenho proposto prefere mecanismos com efeito replicado (pré-compromisso,
> comparação com o próprio passado, reserva mínima) a "nudges" genéricos, cujo efeito é inconsistente.

---

## 1. Diagnóstico: um índice de saúde financeira calculado dos dados

**Evidência.** O *FinHealth Score* (Financial Health Network) mede saúde financeira em 4 pilares e 8 indicadores:
**Gastar** (gasto relativo à renda; contas em dia), **Poupar** (reserva líquida; progresso em metas de longo prazo),
**Dever** (dívida administrável; score de crédito) e **Planejar e proteger** (seguros adequados; planejamento),
numa escala de 0–100 com sub-notas. O original é um questionário; aqui quase tudo pode vir dos dados.
A escala de bem-estar financeiro do CFPB (5 ou 10 itens) é a referência para o lado subjetivo.

**No CFO Central.** Novo `app/analytics/saude_financeira.py`, mensal, com sub-notas e tendência:

| Indicador | Fonte já existente |
|---|---|
| Gasto ÷ receita (12m) | `kpis_from_dre` (`despesas`, `receita_liquida`) |
| Contas em dia | proxy: juros/multa/rotativo/cheque especial (`findesp.juros`, `findesp.multas`) nos últimos 3 meses |
| Reserva líquida em meses | `management.reserva_liquida` ÷ essenciais |
| Progresso de metas | `financial_goals` + `plano.monte_carlo` (probabilidade de atingir) |
| Dívida administrável | parcelas do cartão + empréstimos ÷ renda (`future_installments`, `Loan.outstanding`) |
| Score de crédito | fora do Open Finance: campo manual (ou importação do Registrato, ver §10) |
| Seguros | existência de `saude.plano`/`servicos.seguros` recorrentes; checklist manual |
| Planejamento | meta de aporte, alocação-alvo e metas definidas no plano |

Opcional: aplicar o questionário CFPB de 5 itens a cada trimestre e mostrar ao lado do índice objetivo.
**Prioridade: alta** (reaproveita quase tudo; dá ao Painel uma "nota" com explicação).

## 2. Reserva de emergência em degraus

**Evidência.** Pesquisa da Vanguard (12,4 mil investidores, 2024; correlacional, base própria): ter pelo menos
US$ 2 mil de reserva foi o maior preditor de bem-estar (+21% no índice). Chegar a 3–6 meses de despesas
somou cerca de +13%. Quem não tinha reserva gastava 7,3 h/semana com dinheiro, contra 3,7 h de quem tinha.

**No CFO Central.** Hoje a reserva é binária: abaixo ou acima de N meses (`policy_report`). Proposta de
**degraus com marcos**:
1. colchão inicial = 1 mês de essenciais;
2. 3 meses;
3. meta do plano (6 meses).

Cada degrau atingido vira conquista; abaixo do 1º degrau, o "Quanto posso gastar" prioriza a reserva antes da
meta de aporte. **Prioridade: alta, esforço baixo.**

## 3. "Custos verdadeiros": provisão de despesas anuais e irregulares

**Evidência.** Regra 2 do método YNAB (*embrace your true expenses*): despesas grandes e infrequentes
(IPVA, IPTU, seguro anual, anuidade, matrícula, revisão do carro) devem ser divididas em parcelas mensais
para não virarem "surpresa" (os chamados *sinking funds*).

**No CFO Central.**
- `analytics/recurring.detect_recurring` só aceita intervalos de 24–38 dias. Proposta: estender para
  **anual** (330–400 dias) e **semestral**, com valor esperado e próxima data.
- Novo bloco "Provisões" em `plano.safe_to_spend`: soma de 1/12 de cada despesa anual prevista. Esse valor
  entra como "comprometido" no "Quanto posso gastar" e na `liquidity_forecast`, no mês certo.
- Alerta 60 dias antes de cada vencimento anual com o valor acumulado sugerido.

**Prioridade: alta.** É a principal causa de "mês ruim" que a previsão atual não enxerga.

## 4. Poupar mais amanhã: aporte que sobe com cada aumento

**Evidência.** *Save More Tomorrow* (Thaler & Benartzi, JPE 2004): participantes decidem antes que parte de
cada aumento futuro vai para a poupança. A taxa média subiu de 3,5% para 11,6% em 28 meses, e 80% ficaram
no programa por três aumentos. O mecanismo (pré-compromisso + inércia + sem perda nominal) é robusto. A
causalidade do estudo original é considerada fraca pelo Departamento do Trabalho dos EUA.

**No CFO Central.**
- Detectar **aumento de renda recorrente**: o valor de `rec.salario` em `RecurringRule` sobe X% por 2 meses.
- No plano, opção única "destinar __% de cada aumento ao aporte" (padrão 50%). Ao detectar o aumento,
  `meta_aporte_mensal` é ajustada automaticamente, com aviso e "desfazer".
- Na Revisão, item "Sua renda subiu R$ Y/mês: aplicar a regra?" enquanto o usuário não ativar a opção.

**Prioridade: alta**, esforço baixo.

## 5. Apresentação dos gastos: comparação com o próprio passado

**Evidência.**
- Levi (JFQA): num experimento randomizado com usuários de agregador, mostrar o patrimônio em termos de
  consumo, com comparação saliente ao gasto passado, **reduziu o gasto discricionário em ~15%**, efeito que
  durou os 8 meses do estudo.
- Levi & Benartzi (Journal of Finance): instalar o app de acompanhamento reduz o gasto discricionário.
- Em contrapartida, um experimento pré-registrado com 8,5 mil usuários não achou diferença entre formas de
  enquadrar mensagens de poupança, e push de varejo **aumenta** gasto.
- Conclusão: o que funciona é **contexto e comparação com o próprio histórico**, não mensagens genéricas.

**No CFO Central.**
- No Painel, ritmo do **gasto de estilo de vida** (linha `estilo_vida`) contra a faixa dos últimos 6 meses
  (p25–p75), dia a dia. `daily_spend` já tem a curva; falta a faixa histórica e o recorte discricionário.
- "Seu patrimônio equivale a N meses do seu padrão de vida" (enquadramento por consumo), ao lado do PL.
- Resumo semanal por e-mail (`alerts/notify.py` já envia diário e mensal) só com desvios relevantes
  (categoria acima do p75 do próprio histórico), nunca dicas genéricas.

**Prioridade: média-alta.**

## 6. Cartão e parcelamento: tornar o custo futuro visível

**Evidência.** Teoria da "dor de pagar" (Prelec & Loewenstein, 1998): separar o pagamento do consumo reduz
a percepção de custo. Em leilão, pagantes com cartão ofereceram quase o dobro (Prelec & Simester, 2001).
No Brasil o parcelamento sem juros amplia o descolamento: a compra de hoje consome renda de meses à frente.

**No CFO Central.**
- **"Posso parcelar?"**: simulador que injeta uma compra (valor × parcelas) na `liquidity_forecast` e mostra
  o efeito mês a mês no caixa e no "Quanto posso gastar" dos próximos meses.
- Indicador **renda futura já comprometida** (parcelas dos próximos 3/6 meses ÷ renda recorrente) com
  limite definido no plano; alerta quando uma compra nova cruza o limite. `future_installments` já tem a base.
- Na tela Cartões: "dos seus gastos do mês, X% foram parcelados", comparado com a própria média.

**Prioridade: média-alta.**

## 7. Dívidas: plano de quitação com as duas estratégias

**Evidência.** Avalanche (maior juro primeiro) é matematicamente ótima. Gal & McShane (JMR 2012; 6 mil
devedores, observacional) mostraram que quitar **saldos menores primeiro** aumentou a chance de quitar tudo,
pelo efeito psicológico de fechar contas. Os autores recomendam mostrar as duas opções.

**No CFO Central.**
- Módulo "Dívidas": empréstimos (`Loan`: saldo, CET, parcela), rotativo/cheque especial detectados por
  `findesp.juros` e passivos manuais.
- Simular **avalanche × bola de neve** com o mesmo valor mensal: data de quitação e juros totais de cada
  uma. O usuário escolhe; o app acompanha o progresso.
- Quando o CET passar de um limite, sugerir pesquisar **portabilidade de crédito**. O Open Finance passou
  a ter jornada digital de portabilidade, começando pelo crédito pessoal sem garantia.

**Prioridade: média** (alta para quem tem rotativo).

## 8. Categorização: o estado da arte, adaptado ao Brasil

**Evidência.**
- Comparações recentes de abordagens:
  - repositório *Tranx*, sem revisão por pares, compara regras, embeddings, SLM few-shot e LLM;
  - estudo da QuickBooks (arXiv 2506.09234);
  - categorização de transações de PMEs com LLM (ICAIF).
- O que se repete nesses trabalhos: **embeddings + classificador** empatam ou vencem quando há dados
  rotulados e comerciantes conhecidos. **LLMs** ganham em comerciantes nunca vistos. Rótulos de LLM chegam
  a ~80% de concordância com especialistas, mas erram mais em categorias raras ou ambíguas.

**No CFO Central** (o motor já tem regras → comerciante aprendido → mapa Pluggy → palavras-chave → modelo
TF-IDF + LR com validação cruzada):
1. **Enriquecimento por CNPJ** (sinal brasileiro forte e barato): consultar a base pública de CNPJ da
   Receita Federal para obter o **CNAE** de cada comerciante com documento. Um mapa CNAE → categoria entra
   antes das palavras-chave, com confiança calibrada por subclasse. Cache em `Merchant`.
2. **LLM só para o que sobra**: comerciante novo + confiança < limiar → uma chamada estruturada (categoria do
   plano de contas + justificativa), feita **uma vez por comerciante** e cacheada como sugestão (`rule_source="llm"`).
   Nunca sobrepõe decisão do usuário. Entra na validação cruzada como qualquer outra fonte.
3. **Revisão por valor da informação**: ordenar a fila por *impacto × incerteza*. Uma decisão sobre um
   comerciante com 40 lançamentos e confiança 0,4 vale mais que 1 lançamento isolado. O agrupamento por
   comerciante já existe (`by_merchant`); falta a ordenação.
4. **Embeddings de descrição** (modelo local pequeno) como feature extra do classificador atual, para
   generalizar entre grafias ("UBER *TRIP", "UBER DO BRASIL").

**Prioridade: alta para 1 e 3** (baratos e decisivos); média para 2 e 4.

## 9. Previsão de caixa probabilística e por calendário

**Evidência.** A prática de mercado (ex.: módulo de cash flow da Meniga) e as patentes do setor convergem:
- detectar recorrências e projetar cada uma com valor e data esperados **e incerteza**;
- conciliar o previsto com o realizado;
- avisar risco de saldo negativo antes que aconteça.

Trabalho acadêmico com trabalhadores de baixa renda (arXiv 1806.05362) mostra ganho ao combinar médias
históricas com regressão e detecção de recorrência pela descrição.

**No CFO Central.** Hoje `liquidity_forecast` é mensal e determinística (medianas).
- **Bandas p10/p50/p90**: bootstrap dos resíduos mensais de receita e gasto e "probabilidade de o saldo
  ficar negativo" em cada mês.
- **Calendário diário**: salário no dia típico (`RecurringRule.day_of_month`), vencimentos de fatura
  (`Account.bill_due_date`) e contas fixas nas datas. Mostra o **menor saldo do mês**, não só o saldo final.
- Previsto × realizado por recorrência ("a conta de luz veio 30% acima do esperado").

**Prioridade: média.**

## 10. Automação com o que o sistema brasileiro já oferece

**Evidência e contexto.**
- O **Pix Automático** (Resolução BCB nº 402) entrou em operação em 16/06/2025: débitos recorrentes autorizados
  uma vez, com valor máximo definido pelo pagador; oferta obrigatória para pessoas físicas, sem tarifa.
- O Open Finance Brasil passou de 128 milhões de consentimentos ativos (jan/2026). Tem iniciação de pagamento
  com **Jornada Sem Redirecionamento** e portabilidade de crédito.

**No CFO Central** (respeitando "não mover dinheiro"):
- **Painel de autorizações recorrentes**: identificar lançamentos de Pix Automático e débito automático, com
  valor máximo autorizado (manual) e alerta quando a cobrança se aproxima do teto ou sobe de valor.
- **Assinaturas e reajustes**: comparar o último valor de cada recorrência com a média (`amount_std` já é
  gravado) e alertar aumento acima da inflação. Listar assinaturas sem uso aparente para cancelar.
- **"Dia do pagamento"**: quando o salário cair, sugerir a transferência para reserva/aporte do mês
  (valor da meta), que o usuário executa no banco. Mais tarde, opcionalmente, via iniciação de pagamento.
- **Registrato (BCB)**: importação manual do relatório de dívidas (SCR) para completar o pilar "Dever" (§1).

**Prioridade: média.**

## 11. Investimentos: política, rebalanceamento e impostos

**Evidência.**
- Vanguard (2010): para carteiras diversificadas, monitorar 1–2× por ano e rebalancear com **banda de 5%**
  equilibra controle de risco e custo. Bandas menores multiplicam operações sem ganho relevante.
- Para classes pequenas, bandas **relativas** (ex.: ±20% do peso-alvo) funcionam melhor que absolutas.
- Investimento por objetivos (Das, Markowitz, Scheid & Statman, JFQA 2010): risco é a **probabilidade de não
  atingir cada objetivo**. Carteiras por "conta mental" somam uma carteira eficiente.

**No CFO Central** (`plano.policy_report` já mede desvio com banda de ±5 p.p.):
- **Banda relativa para classes < 10%** do alvo e verificação semestral (não alarme a cada oscilação).
- **Rebalancear pelo aporte**: "para onde vai o aporte deste mês". Distribuir o aporte entre as classes
  abaixo do alvo evita vender (e pagar IR). É a sugestão mais útil e não recomenda produto, só classe.
- **Calendário fiscal**:
  - IR regressivo de renda fixa (22,5% → 20% → 17,5% → 15% em 180/360/720 dias): avisar quando um resgate
    planejado está a poucos dias de cair de faixa;
  - come-cotas de fundos em maio e novembro;
  - comparação CDB × LCI/LCA pela taxa equivalente líquida.
- **PGBL**: para quem faz declaração completa e contribui ao INSS, a dedução vai até 12% da renda bruta
  tributável. A prévia do IRPF (`tax/irpf.py`) pode estimar o espaço restante no ano e o IR adiado
  (deixando claro que o imposto incide no resgate).
- **Metas como "envelopes"**: cada meta (`financial_goals`) com horizonte próprio, alocação compatível
  (prazo < 2 anos → pós-fixado/Tesouro Selic) e probabilidade de sucesso pelo `monte_carlo` já existente.
  Soman & Cheema mostraram que separar o dinheiro por objetivo, com um lembrete visual, aumenta a poupança;
  um nome e uma imagem por meta reproduzem o "envelope".

**Prioridade: alta** para aporte direcionado e calendário fiscal; média para o resto.

## 12. Independência financeira

**Evidência.** A Morningstar (2025) estima 3,9% como taxa inicial de retirada segura para 30 anos (90% de
sucesso, EUA). Estratégias flexíveis (*guardrails*) elevam esse valor. Para o Brasil, o equivalente deve
usar juro real local e IPCA, não a regra de 4% importada.

**No CFO Central.** "Número de IF" = gasto anual recorrente ÷ taxa de retirada, com premissa editável e
juro real do Tesouro IPCA+ como referência. "Anos até IF" a partir da taxa de poupança atual, com
Monte Carlo (`plano.monte_carlo`) e bandas. A tela fica no Planejamento, ao lado das metas.
**Prioridade: média-baixa.**

---

## Roteiro sugerido

| Fase | Itens | Por quê |
|---|---|---|
| **1 — já com os dados atuais** | §3 custos verdadeiros · §2 reserva em degraus · §4 aporte que sobe com aumento · §11 aporte direcionado + IR regressivo · §8.3 revisão por valor da informação | Alto impacto, baixo esforço, sem fonte nova |
| **2 — qualidade e previsão** | §1 índice de saúde · §8.1 CNAE por CNPJ · §6 "posso parcelar?" · §9 previsão com bandas e calendário · §5 faixa histórica de gasto | Melhora a confiança nos números e a antecipação |
| **3 — expansão** | §7 dívidas · §10 Pix Automático/assinaturas · §8.2 LLM para comerciantes novos · §12 IF · questionário CFPB | Novas fontes ou mais desenho |

## Fontes

- Financial Health Network — [FinHealth Score Toolkit](https://finhealthnetwork.org/wp-content/uploads/2021/11/FinHealthScoreToolkit-2021.pdf) · [From Insight to Impact (2026)](https://finhealthnetwork.org/research/from-insight-to-impact-the-next-phase-of-financial-health-measurement/)
- CFPB — [Financial Well-Being Scale](https://www.consumerfinance.gov/data-research/research-reports/financial-well-being-scale/) · [Heck, Ratcliffe & Tibbitts (Cambridge)](https://www.cambridge.org/core/product/19B02EF4573599FDE02794F3327B66B3)
- Vanguard — [Emergency savings may hold key to financial well-being](https://corporate.vanguard.com/content/corporatesite/us/en/corp/articles/emergency-savings-may-hold-key-financial-well-being) · [Best practices for portfolio rebalancing (2010)](https://indexacapital.com/bundles/unaiadvisor/docs/papers/2010-Vanguard-Best-practices-for-portfolio-rebalancing.pdf?v=241)
- Thaler & Benartzi — [Save More Tomorrow](https://www.anderson.ucla.edu/faculty/shlomo.benartzi/savemore.htm) · [revisão DOL CLEAR](https://clear.dol.gov/study/save-more-tomorrow%E2%84%A2-using-behavioral-economics-increase-employee-saving-thaler-benartzi-2004)
- Levi — [Personal Financial Information Presentation and Consumer Spending (JFQA)](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/personal-financial-information-presentation-and-consumer-spending/FB3B05430DC8FFCEC2707C4161E83086) · [Mind the App (Journal of Finance)](https://onlinelibrary.wiley.com/doi/10.1111/jofi.70087) · [Barrafrem et al., saving nudges (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7272436) · [Bies et al., push messaging](https://business.okstate.edu/behlab/assets/bies_bronnenberg_gijsbrechts_2021.pdf)
- Dor de pagar — [Pain of paying](https://en.wikipedia.org/wiki/Pain_of_paying) · [Collins, Payments](https://cfdm.jasoncollins.blog/payments)
- Gal & McShane — [Kellogg: the snowball approach to debt](https://www.kellogg.northwestern.edu/news_articles/2012/snowball-approach.aspx)
- Soman & Cheema — [Earmarking and Partitioning](https://www.russellsage.org/sites/default/files/u137/jmr-C-s014-s021-online.pdf) · [World Bank: fewer goals, higher savings](https://blogs.worldbank.org/en/impactevaluations/marketing-saving-fewer-goals-can-lead-to-higher-savings)
- YNAB — [The rules](https://www.ynab.com/the-new-rules) · [Wikipedia](https://en.wikipedia.org/wiki/YNAB)
- Categorização — [Tranx](https://github.com/aeoxyz-jpg/tranx-transaction-standardization) · [QuickBooks relational DL](https://arxiv.org/pdf/2506.09234) · [LLMs para transações de PMEs](https://www.sea.dev/assets/ICAIF_workshop_paper-llms.pdf) · [LLM sentence embeddings](https://arxiv.org/html/2601.05271) · [LATTE](https://arxiv.org/html/2508.10021)
- Previsão de caixa — [arXiv 1806.05362](https://arxiv.org/abs/1806.05362v1) · [Meniga cashflow](https://www.meniga.com/products/cashflow-forecasting/)
- Investimento por objetivos — [Das, Markowitz, Scheid & Statman (JFQA 2010)](https://ideas.repec.org/a/cup/jfinqa/v45y2010i02p311-334_00.html) · [Das et al., GBWM (JOIM)](https://webpages.scu.edu/ftp/dostrov/publications/JOIM.pdf) · [Bandas de rebalanceamento](https://www.fa-mag.com/news/optimal-rebalancing-with-tolerance-bands-29623.html?page=2)
- Morningstar — [State of Retirement Income 2025](https://www.morningstar.com/lp/the-state-of-retirement-income?refid=vbdo) · [Safe spending rate 2025](https://www.morningstar.com/retirement/whats-safe-retirement-spending-rate-2025)
- Brasil — [Pix Automático em 16/06/2025 (InfoMoney)](https://www.infomoney.com.br/minhas-financas/bc-faz-ajustes-em-seguranca-e-estabelece-junho-de-2025-para-lancar-pix-automatico/) · [Canaltech](https://canaltech.com.br/mercado/bc-confirma-lancamento-do-pix-automatico-em-junho-de-2025-296277/) · [Open Finance: 128 mi de consentimentos](https://contadores.cnt.br/projetos/54/noticias/empresariais/2026/01/28/open-finance-brasil-lidera-ranking-global-com-128-milhoes-de-consentimentos-ativos.html) · [JSR e portabilidade (Finsiders)](https://finsidersbrasil.com.br/entrevistas/a-instituicao-que-nao-aderir-ao-open-finance-estara-em-desvantagem/) · [PGBL 12% (CRC-SP)](https://online.crcsp.org.br/portal/noticias/noticia.asp?c=10892)
