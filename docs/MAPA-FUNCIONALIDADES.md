# CFO Central — Mapa de funcionalidades

> O CFO Central lido como um **CFO pessoal**: alguém que coleta os números, organiza, confere, reporta, orienta e
> avisa, sempre mostrando de onde veio cada valor. Este mapa descreve o que o código faz hoje (out/2026), onde
> está e que salvaguarda existe contra erro ou informação confusa. A especificação técnica está em [`SPEC.md`](SPEC.md).

## Sumário

1. [As funções de um CFO e onde estão no app](#1-as-funções-de-um-cfo-e-onde-estão-no-app)
2. [Coletar: conexões e sincronização](#2-coletar-conexões-e-sincronização)
3. [Organizar: razão, conciliação e categorização](#3-organizar-razão-conciliação-e-categorização)
4. [Conferir: saúde dos dados](#4-conferir-saúde-dos-dados)
5. [Decidir junto: fila de revisão](#5-decidir-junto-fila-de-revisão)
6. [Reportar: demonstrativos](#6-reportar-demonstrativos)
7. [Orientar: orçamento, planejamento e "quanto posso gastar"](#7-orientar-orçamento-planejamento-e-quanto-posso-gastar)
8. [Investimentos: carteira, retorno, risco e política](#8-investimentos-carteira-retorno-risco-e-política)
9. [Impostos: prévia do IRPF](#9-impostos-prévia-do-irpf)
10. [Guiar e avisar: Seu CFO hoje e alertas por e-mail](#10-guiar-e-avisar-seu-cfo-hoje-e-alertas-por-e-mail)
11. [Conversar: assistente MCP](#11-conversar-assistente-mcp)
12. [Operação, segurança e privacidade](#12-operação-segurança-e-privacidade)
13. [Salvaguardas contra erro e confusão (visão transversal)](#13-salvaguardas-contra-erro-e-confusão-visão-transversal)
14. [Lacunas e oportunidades observadas](#14-lacunas-e-oportunidades-observadas)

---

## 1. As funções de um CFO e onde estão no app

| Função do CFO | Pergunta que responde | Tela | Código principal |
|---|---|---|---|
| Coletar | "Os dados estão chegando?" | Conexões | `connectors/pluggy`, `ingestion/pluggy_sync.py`, `services/pipeline.py` |
| Organizar | "O que é cada lançamento?" | Lançamentos, Regras, Comerciantes | `accounting/ledger.py`, `categorization/*`, `reconciliation/matching.py` |
| Conferir | "Os números batem com o banco?" | Saúde dos dados | `health/checks.py`, `accounting/effective.py` |
| Decidir junto | "O que só eu posso decidir?" | Revisão | `alerts/reviews.py`, `routes_ledger.apply_review` |
| Reportar | "Quanto ganho, gasto e tenho?" | Painel, DRE, DRE gerencial, DFC, Balanço | `accounting/statements.py`, `management.py`, `balance.py`, `analytics/overview.py` |
| Orientar | "Quanto posso gastar? Vou bater a meta?" | Painel, Categorias, Planejamento | `analytics/plano.py`, `analytics/overview.py`, `analytics/recurring.py` |
| Investir | "Como a carteira rende e quanto arrisca?" | Carteira, Configurações → Ativos | `portfolio/*` |
| Tributar | "O que vai na declaração?" | Imposto de renda | `tax/irpf.py` |
| Guiar | "O que preciso saber e lembrar hoje?" | Painel → Seu CFO hoje | `analytics/guia.py`, `scripts/resumo_diario.*` |
| Avisar | "O que mudou e merece atenção?" | E-mail, badge "para decidir" | `alerts/notify.py`, `main._alerts_job` |
| Conversar | "Me explica / classifica isso pra mim" | Claude (MCP) | `assistant/mcp_server.py` |

Princípio que atravessa tudo: **o app mede e explica, não decide nem movimenta dinheiro**. Recomendação de
produto, ordens e pagamentos estão fora do escopo (`SPEC.md` §10); alvos e limites são definidos pelo usuário e o
app só mede o desvio (`analytics/plano.py`).

---

## 2. Coletar: conexões e sincronização

**O que faz**
- Conexão Open Finance via **MeuPluggy** (até 5 bancos). Connect token de 30 min para o navegador; o segredo fica
  só no backend (`routes_system.py: /connect-token, /items`).
- Coleta por item: contas, transações (janela de 90 dias ou completa), faturas, investimentos e movimentações,
  empréstimos e identidade do titular (`ingestion/pluggy_sync.py`).
- Dado bruto **versionado e imutável** em `raw_payloads` (uma linha por hash); espelho normalizado na camada 2.
- Agenda: Pluggy a cada 4 h, mercado (BCB/SGS: CDI, Selic, IPCA; Yahoo: ativos, IBOV, S&P, dólar) às 19h45,
  alertas diários; botão **Sincronizar**; webhook com *debounce* que só dispara releitura (`main.py`, `pipeline.py`).
- Pós-sync automático: cotações de ativos novos, reconstrução do razão, revisões, recorrências, saúde dos dados
  e foto diária do patrimônio (`Pipeline._post_process`).
- Tela **Conexões**: apelido do banco, status, consentimento, histórico de execuções e log técnico por etapa.

**Salvaguardas**
- Idempotência: reprocessar não duplica; transação que some da fonte ganha `removed_at`, nunca é apagada.
- Falha numa etapa marca o run como `partial` e segue as demais; o erro aparece em `sync_events` e na saúde.
- Uma execução por vez: trava de thread + `pg_advisory_lock` entre processos (`database/advisory.py`).
- O app nunca pede refresh à Pluggy (`PATCH /items`), só lê.

---

## 3. Organizar: razão, conciliação e categorização

### 3.1 Livro razão determinístico (`accounting/ledger.py`)
Cada transação vira um **evento econômico** (`financial_events`) com tipo, categoria, data de competência, data de
caixa, valor, origem da decisão (`rule_source`), confiança e motivo de revisão. O razão é **reconstruído do zero**
a partir do bruto + cadastro + ajustes; ajustes manuais (`event_overrides`) nunca são sobrescritos. Toda mudança de
tipo/categoria/valor entre reconstruções vai para `ledger_audit` com ator e motivo.

Tipos de evento e efeito nos demonstrativos: ver `SPEC.md` §3 (INCOME, EXPENSE, REFUND, CARD_PAYMENT,
INTERNAL_TRANSFER, INVESTMENT_CONTRIBUTION/REDEMPTION etc.).

### 3.2 Transações efetivas (`accounting/effective.py`)
Fonte única do que "conta": pendente com efetivado equivalente (±3 dias) é descartado como duplicata; pendente
velho sem efetivação (10 dias na conta, 40 no cartão) é ignorado e sinalizado.

### 3.3 Conciliação estrutural (`reconciliation/matching.py`)
- **Pagamento de fatura** ↔ cartão conectado (valor e data compatíveis; raízes de CNPJ de emissores; gateways de
  pagamento excluídos). Sem cartão conectado → despesa "cartão não conectado" + revisão.
- **Transferência própria** por CPF do titular ou nome; com par em conta conectada → `INTERNAL_TRANSFER`; sem par →
  `EXTERNAL_OWN_TRANSFER` (financiamento na DFC).
- **Aporte/resgate** de investimento fora do resultado.
- **Parcelas** agrupadas por `installment_key` (base de "parcelas futuras").
- **Reembolso espelho**: Pix de pessoa física com o mesmo valor quebrado de uma despesa sua dos 45 dias anteriores
  vira REFUND daquela categoria (`_mirror_refunds`).

### 3.4 Motor de categorização (ordem de prioridade)
1. Ajuste manual (1.00) → 2. Regra do usuário (0.95) → 3. Conciliação estrutural → 4. Comerciante aprendido
(0.85 usuário / 0.75) → 5. Mapa Pluggy → plano de contas (0.5–0.8) → 6. Palavras-chave/MCC (~40 padrões de
marcas brasileiras) → 7. "A classificar" (0.10).

Regras de bom senso embutidas em `_decide`: compra no cartão nunca é Pix a pessoa física; categoria patrimonial
da Pluggy no cartão é ruído; estorno no cartão nunca é receita; tag de pedágio é transporte; recebido de terceiro
vira "a classificar" e não receita.

### 3.5 Classificador treinado (`categorization/model.py`)
TF-IDF + regressão logística treinado nas suas decisões. Só atua onde a classificação é fraca, só é usado se
acertar ≥ 90 % em validação cruzada acima do limiar 0.80, nunca mexe em ajuste/regra/conciliação/Pix para pessoa
física e respeita o sentido do dinheiro. Cada troca registra probabilidade e termos que pesaram.

### 3.6 Cadastro e curadoria
- **Plano de contas** pessoal em árvore com linha da DRE, natureza e "essencial" (`categorization/chart.py`).
- **Regras** com pré-visualização de impacto antes de salvar (`/rules/preview`), contador de acertos.
- **Comerciantes** canônicos (CNPJ ou alias) com categoria padrão aprendida, ranking, frequência e ticket médio.
- **Lançamentos**: filtros, edição inline, seleção em massa, desfazer, "criar regra a partir deste lançamento" e
  gaveta com proveniência (payload bruto, regra, confiança, histórico de mudanças).
- **Curadoria versionada** (`curadoria/curadoria.json`, `services/curation.py`): decisões em Git, reaplicáveis
  após recriar o banco.

---

## 4. Conferir: saúde dos dados

`health/checks.py` roda **12 conferências** a cada reconstrução e guarda o histórico (`health_runs`, últimas 300).
Status: OK, Atenção, Falha, Informativo. Atenção/Falha viram itens graves na fila de revisão e entram no e-mail.

| Grupo | Conferência | Identidade verificada |
|---|---|---|
| Coleta | Sincronização | última leitura < 26 h (atenção) / 72 h (falha); status de login; erro por etapa; consentimento vencendo |
| Coleta | Cotações e índices | CDI e preço dos ativos em carteira com ≤ 6 dias |
| Conciliação | Faturas × lançamentos | total(n) = total(n−1) + Σ lançamentos da fatura n (±R$ 1) |
| Conciliação | Saldo devedor do cartão | saldo informado = última fatura + lançamentos após o fechamento |
| Conciliação | Pagamentos de fatura | todo pagamento ligado a um cartão conectado |
| Conciliação | Saldos bancários | saldo reconstruído para trás nunca abaixo do cheque especial; variação entre fotos fecha com os lançamentos |
| Conciliação | Banco × corretora | aplicações/resgates no banco ≈ compras/vendas na corretora (D+1, IR no resgate) |
| Razão | Razão completo | todo lançamento tem evento; Σ eventos por conta = Σ fluxos |
| Razão | Transferências | toda transferência interna tem a outra ponta |
| Razão | Pendentes e duplicidades | pendente antigo, gêmeo pendente→efetivado, efetivado com data futura |
| Razão | Cobertura da classificação | ≤ 5 % do gasto sem categoria; ≤ 15 % do volume com confiança baixa |
| Razão | Fila de revisão | contagem por severidade |

É a peça que mais diretamente cumpre "minimizar erros": prova, com identidades contábeis, que o que o app mostra
bate com o que o banco informa, e diz onde não bate.

---

## 5. Decidir junto: fila de revisão

Gerada a cada reconstrução; itens resolvidos/dispensados não reabrem; itens que deixam de existir fecham sozinhos
(`alerts/reviews.py: sync_reviews`). Tela **Revisão** separa *decisões rápidas*, *avisos* e *informativos*; o
badge "N para decidir" fica no topo de todas as telas.

| Origem | Itens |
|---|---|
| Classificação | sem categoria; confiança < 0.6 com valor ≥ R$ 50; Pix enviado a pessoa física; recebido de terceiro; ajuste manual superado por conciliação; pendente antigo ignorado |
| Agrupamento | itens do mesmo comerciante/contraparte viram **uma** decisão que vale para todos os lançamentos |
| Recorrência | receita recorrente ("é salário?") |
| Sistema | conexão com erro; consentimento vencendo (≤ 30/7 dias); sync falhou; **mesma conta em duas conexões** (duplicaria tudo); gasto atípico (> 3× mediana da categoria); possível duplicidade |
| Carteira | emissor acima do FGC; ativo sem cotação; **saída de investimento sem contrapartida** ("valores em trânsito", com 4 resoluções) |
| Política | classe fora da banda; reserva de emergência abaixo do mínimo |
| Saúde | cada conferência em Atenção/Falha |

Resolver um item aplica a decisão no lugar certo (comerciante, regra ou ajuste do lançamento) e reconstrói o razão.

---

## 6. Reportar: demonstrativos

| Tela | Conteúdo | Destaques anti-confusão |
|---|---|---|
| **Painel** | patrimônio e composição, resultado do mês, taxa de poupança, ritmo de gastos diário vs mês anterior e orçamento, top categorias/comerciantes, evolução do PL, compromissos de cartão 3 m, "quanto posso gastar", checklist de primeiros passos | aviso de **números provisórios** enquanto muita receita está "a classificar" |
| **DRE** (competência) | matriz mês × linha até subcategoria, AV/AH, clique → razão filtrado | cartão na data da compra; fatura, aporte, resgate e transferência fora; resultado recorrente separado de extraordinários |
| **DRE gerencial** | mês × média 6 m × média 12 m, Δ, % da receita, orçamento e execução, acumulado do ano; indicadores (poupança, reserva em meses, peso dos essenciais, comprometimento com parcelas) | mês corrente marcado como parcial |
| **DFC** (caixa, direto) | operacional/investimento/financiamento + Sankey | **conferência** contra Δ saldo das contas |
| **Balanço** | ativo (caixa, investimentos, manuais, valores em trânsito), passivo (fatura aberta, parcelas futuras, empréstimos, manuais), PL e histórico | premissas visíveis; meses antes da 1ª foto marcados como **estimados** |
| **Cartões** | limite e uso, faturas, parcelas por mês, gasto mensal | — |
| **Categorias** | árvore com realizado, média 3 m, mediana 6 m, orçamento; detalhe por subcategoria e comerciante | — |
| Exportação | Excel/CSV (`/export.xlsx`, `/export.csv`, CLI `export`) e acesso ao Postgres em `127.0.0.1:5433` (Power BI, Excel) | — |

---

## 7. Orientar: orçamento, planejamento e "quanto posso gastar"

- **Quanto posso gastar** (`plano.safe_to_spend`): renda prevista (mediana recorrente de 3 meses sem bônus, ou o já
  recebido) − meta de aporte − gasto do mês − recorrências que ainda vencem; valor por dia e projeção do mês.
  Sem meta definida usa 20 % da renda, **limitado à sobra real** (não sugere aporte a quem fecha no vermelho).
  As premissas vêm junto da resposta.
- **Orçamento** mensal por categoria (padrão ou por mês), somado nas categorias-mãe, com execução na DRE gerencial.
- **Recorrências** (`analytics/recurring.py`): assinaturas, contas fixas e salário detectados; o usuário confirma
  ou ignora.
- **Previsão de caixa 6 meses** (`overview.liquidity_forecast`): só receita recorrente; despesas pela mediana de
  meses completos; cartão = fatura atual, depois parcelas contratadas + gasto médio à vista; mínimo de caixa.
- **Metas com Monte Carlo** (4.000 cenários log-normais, risco da carteira atual ou premissa de 8 % a.a.):
  probabilidade de atingir, faixas p10/p50/p90 e trajetória.
- **Capacidade de investimento**: resultado médio/mediano 6 m menos compromissos de cartão.

---

## 8. Investimentos: carteira, retorno, risco e política

- **Classificação** automática em 16 classes (RF Pós/Pré/IPCA+, Tesouro, ETFs por tipo, Ações, FIIs, Fundos,
  Previdência, Cripto, COE…), indexador, liquidez, emissor e proxy de risco; ajuste manual de classe/ticker em
  Configurações → Ativos (`portfolio/classification.py`).
- **Posições, alocação, FGC por emissor** (limite R$ 250 mil configurável) e **escada de vencimentos**.
- **Retorno realizado por título** (`portfolio/realized.py`): aplicado, resgatado, IR/IOF, resultado, **TIR** e
  **% do CDI** com os mesmos fluxos; títulos fora do histórico marcados como parciais.
- **Custo de renda variável** só com evidência (negociação da Pluggy, débito bancário compatível ou estimativa
  marcada); quantidade anterior ao primeiro snapshot fica **sem custo**, nunca inventado.
- **Performance**: TWR encadeado a partir das fotos diárias, comparado a CDI, IPCA, IBOV e S&P (`metrics.py`).
- **Risco ex-ante** (pesos atuais × 2 anos): volatilidade, Sharpe, Sortino, VaR/CVaR 95 %, drawdown, beta,
  correlação entre classes, contribuição ao risco, HHI/posições efetivas. Proxies sempre identificados.
- **Valores em trânsito** (`portfolio/transit.py`): queda de saldo sem venda nem crédito compatível fica no
  patrimônio até aparecer a contrapartida ou o usuário escolher entre conta não conectada, custódia transferida,
  erro do provedor ou perda.
- **Política de investimentos**: alocação-alvo por classe com banda (±5 p.p. padrão), reserva mínima em meses de
  custo essencial (liquidez D0/D1, Tesouro Selic e RF com liquidez diária comprovada), alerta de FGC. Mostra o
  valor para voltar ao alvo, sem recomendar produto.
- **Ativos e passivos manuais** (imóvel, veículo, dívida informal) entram no balanço.

---

## 9. Impostos: prévia do IRPF

`tax/irpf.py` monta a prévia do ano-base, com a origem de cada número, e exporta para Excel (`/ir.xlsx`):
- **Bens e direitos** em 31/12 com grupo/código da Receita (contas, RF/Tesouro, isentos, ações, ETFs, FIIs,
  fundos, cripto, empréstimos concedidos);
- **Tributação exclusiva** (cód. 06) com IR retido; estimativa pela tabela regressiva quando falta histórico;
- **Isentos** (heranças/doações, dividendos, LCI/LCA, vendas de ações até R$ 20 mil/mês);
- **Renda variável**: resultado mensal, compensação de prejuízo e DARF 6015;
- **Pagamentos dedutíveis** (saúde sem teto; instrução até R$ 3.561,50) com CPF/CNPJ do prestador quando o Pix informa;
- **Tributáveis** (líquidos) só para conferência com o informe;
- **Pendências**: lista explícita do que os dados não cobrem (situação no ano anterior, informes, dívidas).

Sempre rotulado como **prévia para conferência**: os informes das instituições prevalecem.

---

## 10. Guiar e avisar: Seu CFO hoje e alertas por e-mail

**Seu CFO hoje** (topo do Painel, `analytics/guia.py`, `components/Guide.tsx`):
- **Manchete**: quanto ainda dá para gastar no mês (por dia), ou quanto o mês já passou do previsto.
- **O que importa agora**, por prioridade (importante → atenção → para saber → boa notícia), cada um com uma ação e
  um "Entendi" que esconde o aviso até a situação mudar: conferência com falha, conexão caída ou autorização
  vencendo, saldo que não cobre as faturas dos próximos dias, ritmo de gastos acima do previsto, orçamento estourado
  ou perto do limite, caixa negativo na previsão, reserva abaixo do mínimo, alertas graves da revisão, decisões
  rápidas pendentes, gasto fora do padrão, números provisórios, fechamento do mês anterior e prévia do IR na época.
- **Próximos dias**: faturas, recorrências (entradas e saídas) e autorizações que vencem em até 10 dias.
- **Resumo do Claude** (opcional, plano Pro/Max via Claude Code, sem API): `AGENDAR-RESUMO.bat` agenda
  `scripts/resumo_diario.ps1` às 7h30. O Claude lê `guia` pelo MCP e publica 2 a 4 frases com `publicar_briefing`,
  escolhendo a ordem e reescrevendo os avisos. Salvaguardas: só ids existentes, só valores em R$ que aparecem nos
  fatos (senão recusa e diz o que corrigir), acesso só a quatro ferramentas, validade de 36 h.

**Alertas por e-mail**

`alerts/notify.py` (SMTP/Gmail com senha de app, configurável na tela):
- **Resumo diário**: itens novos graves/atenção (cada um avisado uma vez só), estado da saúde dos dados e
  "quanto posso gastar".
- **Fechamento mensal** (dias 1–3, uma vez): DRE gerencial do mês anterior e indicadores de poupança e reserva.
- Botão de teste e histórico dos últimos envios em Configurações.

---

## 11. Conversar: assistente MCP

`assistant/mcp_server.py` expõe o CFO Central ao Claude (Desktop/Code) via stdio; `INSTALAR-MCP.bat` registra.
As instruções do servidor ensinam as convenções (sinal dos valores, tipos de evento, prioridade de classificação).

| Grupo | Ferramentas |
|---|---|
| Leitura | `guia`, `visao_geral`, `dre`, `dre_gerencial`, `dfc`, `balanco`, `cartoes`, `carteira` (com risco opcional), `planejamento`, `quanto_posso_gastar`, `politica_investimentos`, `retornos_realizados`, `saude_dados`, `classificador`, `imposto_de_renda`, `lancamentos`, `lancamento`, `categorias`, `gastos_por_categoria`, `comerciantes`, `contas`, `revisoes`, `regras`, `esquema`, `consulta_sql` |
| Simulação | `simular_regra`, `simular_meta` |
| Curadoria | `publicar_briefing`, `classificar_lancamentos`, `remover_ajuste`, `classificar_comerciante`, `criar_regra`, `desativar_regra`, `resolver_revisao`, `configurar_conta`, `definir_orcamento`, `definir_plano`, `definir_alocacao_alvo` |
| Operação | `sincronizar`, `reconstruir_razao` |

Salvaguardas: SQL só `SELECT/WITH` em transação somente leitura (timeout 15 s, tabela `users` bloqueada);
validação de categoria e tipo antes de escrever; toda escrita auditada com ator `assistente`; reconstrução pedida
ao app respeitando a trava; nada move dinheiro.

---

## 12. Operação, segurança e privacidade

- **Local-first**: Docker (Postgres 16) ou sem Docker (SQLite); portas só em `127.0.0.1`.
- Login de usuário único (argon2, cookie assinado HttpOnly de 12 h); webhook sem auth só enfileira releitura.
- Credenciais da Pluggy e do e-mail configuráveis pela tela, valendo por cima do `.env` (`config/integrations.py`).
- **Modo privacidade** (olho no topo) mascara valores na tela (`frontend/src/privacy.ts`).
- **Glossário** contextual (`components/Term.tsx`, ~26 termos: DRE, competência, VaR, Sharpe, TIR, TWR, FGC…).
- Funciona no celular (menu lateral recolhível).
- Backup diário (`pg_dump`, 30 dias) e `BACKUP.bat`; migrações Alembic.
- **Vitrine** estática com dados fictícios no GitHub Pages (`scripts/demo_*`, workflow `demo-pages.yml`).
- CLI: `sync`, `rebuild`, `market`, `summary`, `export`, `curate`.
- Testes: 77 (unitários e de integração, Pluggy simulada em `tests/fixtures/fake_pluggy.py`).

---

## 13. Salvaguardas contra erro e confusão (visão transversal)

| Risco | Como o app trata |
|---|---|
| Contar a mesma coisa duas vezes | pendente→efetivado descartado; transferência própria anulada; pagamento de fatura fora da DRE; conta repetida em duas conexões vira alerta grave; possível duplicidade sinalizada |
| Confundir patrimônio com resultado | aporte/resgate e transferências fora da DRE; valorização da carteira em linha separada; extraordinários (herança, bônus) separados do recorrente |
| Número sem origem | `rule_source`, confiança, `is_inferred`, payload bruto e histórico em cada lançamento; premissas listadas em previsões, balanço, "quanto posso gastar" e Monte Carlo |
| Estimativa apresentada como fato | rótulos "estimado", "proxy", "parcial", "provisório"; custo de RV nunca inventado |
| Dado desatualizado ou faltando | saúde dos dados (sync, cotações, saldos, faturas, banco × corretora); valores em trânsito em vez de sumir com patrimônio |
| Classificação automática errada | prioridade explícita; classificador só com precisão ≥ 90 % comprovada; decisões sensíveis (Pix a pessoa física, recebidos de terceiros) sempre vão para o usuário; auditoria de cada troca |
| Decisão do usuário perdida | ajustes nunca sobrescritos; curadoria versionada em JSON; aviso quando um ajuste antigo foi superado pela conciliação |
| Sobrecarga de decisões | revisões agrupadas por contraparte (um clique vale para todas); auto-fechamento do que deixou de existir; separação decisões/avisos/informativos |
| Jargão | glossário em hover/toque; nomes de tela em linguagem comum ("Resultado do mês" em vez de "DRE") |

---

## 14. Lacunas e oportunidades observadas

Encontradas durante a leitura do código; nenhuma foi corrigida neste documento.

**Inconsistências concretas**
1. **MCP não resolve "valores em trânsito".** `resolver_revisao` não aceita o parâmetro `resolution`, e
   `apply_review` exige esse campo para itens `exit_no_counterpart` (lança `HTTPException 422`). Pelo assistente,
   esse item, que é de severidade grave, só pode ser dispensado (`app/assistant/mcp_server.py`,
   `app/api/routes_ledger.py: apply_review`).
2. **README desatualizado**: a contagem de testes foi corrigida, mas a tabela de ferramentas MCP ainda omite dez
   delas (`dre_gerencial`, `quanto_posso_gastar`, `politica_investimentos`, `definir_plano`, `definir_alocacao_alvo`,
   `simular_meta`, `retornos_realizados`, `saude_dados`, `classificador`, `imposto_de_renda`).
3. **CNPJ de instituições no IR** cobre só Nubank e Inter (`tax/irpf.py: INSTITUTION_CNPJ`); outros bancos ficam
   sem CNPJ em Bens e Direitos.

**Lacunas de cobertura do assistente (MCP)**
- Sem ferramentas para metas (criar/excluir), recorrências (confirmar/ignorar), ativos manuais e classe/ticker de
  ativos, embora a API REST tenha esses endpoints.

**Oportunidades no papel de "parceiro"**
- **Guia também no e-mail**: o "Seu CFO hoje" existe na tela; o e-mail diário ainda só sai quando há alerta novo.
- **Explicação de variação**: a DRE gerencial mostra o Δ contra a média, mas não diz *quais* lançamentos explicam
  a diferença (top contribuições por categoria/comerciante).
- **Score único de confiabilidade** no Painel combinando saúde dos dados, cobertura de classificação e revisões
  graves, para o usuário saber de relance se pode confiar nos números do mês.
- **Itens do roadmap ainda abertos** (`SPEC.md` §11): split de transação, notas de corretagem/extrato B3 para preço
  médio, tags, orçamento base-zero, Telegram, análise de fronteira eficiente.
