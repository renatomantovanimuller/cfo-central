# CFO Central — Especificação técnica

> Livro razão financeiro pessoal + camada de inteligência + centralizador patrimonial.
> Versão da spec: 1.0 (out/2026). Fonte primária: MeuPluggy (Open Finance). Execução 100% local.

## 0. Perguntas que o sistema responde → onde

| # | Pergunta | Tela / cálculo |
|---|---|---|
| 1 | Quanto dinheiro eu tenho? | **BP** e Painel → Patrimônio líquido com composição e premissas |
| 2 | Onde meu dinheiro está? | BP por conta/instituição/classe; Carteira por classe, indexador, emissor, liquidez |
| 3 | Quanto recebo e quanto gasto? | **DRE** mensal (competência) e **DFC** (caixa) |
| 4 | Com o que gasto? | Categorias (árvore) → subcategoria → comerciante → transação (drill-down) |
| 5 | Quanto está comprometido? | Cartões: fatura aberta + parcelas futuras; Planejamento: previsão de liquidez 6m |
| 6 | Quanto invisto? | DFC – fluxo de investimento; KPI "aporte líquido" e taxa de investimento |
| 7 | Como a carteira performa? | Carteira: retorno por ativo, TWR (snapshots), vs CDI/IPCA/IBOV |
| 8 | Quais meus riscos? | Carteira: vol, Sharpe, Sortino, VaR/CVaR, drawdown, beta, correlação, concentração (HHI), exposição FGC por emissor, ladder de vencimentos |
| 9 | Capacidade mensal de investimento? | Planejamento: resultado médio 3/6/12m − compromissos recorrentes |
| 10 | Que decisões analisar? | Revisão + Alertas: anomalias, assinaturas, FGC acima do limite, consentimento vencendo, gasto acima do orçamento |

## 1. Arquitetura

```
┌────────────── Docker (localhost) ───────────────────────────────────────────┐
│  db: PostgreSQL 16  (volume cfo_pgdata)                                      │
│  app: Python 3.12 · FastAPI · Uvicorn · APScheduler  → 127.0.0.1:8060        │
│        ├─ /api/*            REST (JSON)                                      │
│        ├─ /api/webhooks/pluggy  (sem auth; só dispara releitura)             │
│        └─ /*                SPA React (build estático servido pelo FastAPI)  │
└──────────────────────────────────────────────────────────────────────────────┘
         │ HTTPS                    │ HTTPS                 │ HTTPS
   api.pluggy.ai            api.bcb.gov.br (SGS)     query1.finance.yahoo.com
```

Pipeline (cada etapa isolada e reprocessável):

```
connectors/pluggy ─▶ ingestion ─▶ raw_payloads (append-only, hash)
                                     │
                         normalization ─▶ camada 2 (espelho Pluggy, soft-delete)
                                     │
            categorization + reconciliation ─▶ camada 4 financial_events (+ audit, reviews)
                                     │
             accounting / analytics / portfolio ─▶ camada 5 (snapshots + consultas)
                                     │
                                  api ─▶ frontend
```

* **Idempotência**: toda entidade tem chave natural (`pluggy id`). `raw_payloads` guarda uma linha por **versão** (`entity_type, external_id, payload_hash` único); recoleta igual só atualiza `last_seen_at`.
* **Nada é apagado**: transação que some da fonte recebe `removed_at` (ex.: pendente que virou definitiva com outro ID). Eventos de transações removidas saem dos relatórios mas ficam auditáveis.
* **Ledger determinístico**: `financial_events` é reconstruído a partir de camada 2 + cadastro (camada 3) + ajustes manuais. Mudanças de classificação entre reconstruções vão para `ledger_audit` (log financeiro).
* **Revisão não bloqueia**: a ingestão sempre conclui; incertezas viram itens em `review_items`.

## 2. Estrutura de diretórios

```
cfo-central/
├── app/
│   ├── main.py                 # app factory, SPA, scheduler
│   ├── config/                 # Settings (pydantic-settings, .env)
│   ├── database/               # engine, sessão, Base
│   ├── models/                 # source, finance, registry, ledger, analytics, auth
│   ├── auth/                   # hash argon2, sessão por cookie assinado
│   ├── connectors/pluggy|bcb|yahoo
│   ├── ingestion/              # sync de item, raw store, snapshots
│   ├── normalization/          # payload Pluggy → camada 2
│   ├── categorization/         # plano de contas, mapa Pluggy, motor de regras, comerciantes
│   ├── reconciliation/         # transferências internas, faturas, investimentos, parcelas
│   ├── accounting/             # ledger (eventos), DRE, DFC, BP
│   ├── portfolio/              # classificação, posições, retorno, risco, mercado
│   ├── analytics/              # resumos, orçamento, recorrências, previsão
│   ├── alerts/                 # geradores da fila de revisão
│   ├── api/                    # routers
│   └── utils/
├── frontend/                   # React + Vite + TS + Tailwind + ECharts + TanStack
├── migrations/                 # Alembic
├── tests/{unit,integration,fixtures}
├── scripts/                    # CLI: sync, rebuild, export, criar usuário
├── docs/
├── docker-compose.yml · Dockerfile · pyproject.toml · .env.example · INICIAR.bat
```

## 3. Modelo de dados (6 camadas)

Colunas de proveniência presentes nas tabelas tratadas: `source`, `item_id`, `external_id`, `raw_payload_id`, `first_seen_at`, `last_seen_at`, `source_updated_at`, `removed_at`.
Nos eventos: `rule_source`, `rule_id`, `confidence`, `is_inferred`, `needs_review`.

### Camada 1 — Fonte e integração
| Tabela | Conteúdo |
|---|---|
| `users` | usuário local (argon2) |
| `institutions` | conector Pluggy (nome, logo, cor, Open Finance) |
| `items` | conexão: status, executionStatus, consentimento, próximo auto-sync, produtos |
| `sync_runs` | execução (gatilho manual/agendado/webhook), status ok/parcial/erro, estatísticas |
| `sync_events` | **log técnico** por etapa (nível, mensagem, dados) |
| `webhook_events` | payload recebido, processamento |
| `raw_payloads` | JSON bruto versionado por hash |

### Camada 2 — Espelho normalizado da Pluggy
`accounts`, `account_balances` (snapshot diário), `transactions` (inclui metadados de cartão, paymentData, merchant), `credit_card_bills`, `investments`, `investment_balances` (snapshot diário), `investment_transactions`, `loans`, `identity_records`.
Views: `credit_card_transactions` (transações de contas CREDIT). `installment_plans` (compras parceladas agrupadas) é tabela derivada na reconciliação.

### Camada 3 — Cadastro próprio
| Tabela | Uso |
|---|---|
| `categories` | **plano de contas pessoal** (árvore) com `nature`, `dre_line`, `dfc_section`, `essential` |
| `pluggy_category_map` | categoria Pluggy → categoria própria + confiança base |
| `category_rules` | regras do usuário/aprendidas (campo, operador, padrão, faixa de valor, sentido, conta) → categoria/tipo |
| `merchants`, `merchant_aliases` | comerciante canônico (CNPJ ou nome normalizado) com categoria padrão aprendida |
| `assets` | ativo canônico: ticker/ISIN, classe, indexador, liquidez, símbolo Yahoo, proxy de risco |
| `asset_prices`, `market_series` | preços diários e séries (CDI, Selic, IPCA, IBOV, S&P, USD) |
| `budgets` | orçamento mensal por categoria |
| `recurring_rules` | recorrências detectadas/confirmadas |
| `financial_goals` | metas (valor, prazo, vínculo) |
| `manual_assets` | ativos/passivos fora do Open Finance (imóvel, veículo, conta não conectada, dívida informal) |
| `account_settings` | apelido, finalidade, incluir no patrimônio |

### Camada 4 — Contabilidade pessoal
| Tabela | Uso |
|---|---|
| `financial_events` | 1 evento econômico por transação (ou N com split): tipo, categoria, competência, caixa, valor, regra, confiança |
| `event_overrides` | ajustes manuais (categoria, tipo, data de competência, nota, tags, excluir) — nunca sobrescritos |
| `internal_transfers` | pares saída/entrada entre contas próprias (método, confiança) |
| `card_payment_links` | pagamento de fatura ↔ cartão/fatura (método, diferença) |
| `review_items` | fila de revisão (tipo, severidade, entidade, status, resolução) |
| `ledger_audit` | **log financeiro**: mudança de tipo/categoria/valor por evento, ator, motivo |

Tipos de evento (`event_type`):

| Tipo | Exemplo | DRE | DFC |
|---|---|---|---|
| `INCOME` | salário, bolsa, freela | Receita operacional | Operacional |
| `INVESTMENT_INCOME` | dividendos, juros pagos em conta, cashback | Receita financeira | Operacional |
| `EXPENSE` | compra no cartão (na data da compra), boleto, Pix p/ comerciante | Despesa (categoria) | Operacional (no pagamento) |
| `FINANCIAL_EXPENSE` | juros, IOF, multa, tarifa | Despesa financeira | Operacional |
| `TAX` | IR, IPTU, IPVA | Impostos | Operacional |
| `REFUND` | estorno no cartão, reembolso de amigo | reduz a despesa da categoria | Operacional |
| `INTERNAL_TRANSFER` | entre contas próprias conectadas | — | — (anula) |
| `EXTERNAL_OWN_TRANSFER` | de/para conta própria **não conectada** | — | Financiamento ("contas não conectadas") |
| `CARD_PAYMENT` | pagamento de fatura de cartão conectado | — (liquidação de obrigação) | Operacional (saída de caixa) |
| `INVESTMENT_CONTRIBUTION` | aplicação, compra de ETF | — | Investimento (−) |
| `INVESTMENT_REDEMPTION` | resgate | — (não é receita) | Investimento (+) |
| `LOAN_IN` / `LOAN_PAYMENT` | empréstimo tomado / parcela | — / juros → desp. financeira | Financiamento |
| `IGNORE` | manual | — | — |

### Camada 5 — Analítica
Tabelas: `daily_net_worth` (com composição JSON e premissas), `investment_balances`, `account_balances`.
Consultas (Python/SQL, sob demanda): `monthly_cash_flow`, `monthly_expense_summary`, `monthly_income_summary`, `budget_execution`, `portfolio_returns`, `portfolio_risk_metrics`, `recurring_payment_summary`, `liquidity_forecast`, `card_commitment_forecast`.

## 4. Sincronização

| Rotina | Quando | O que faz |
|---|---|---|
| `pluggy_sync` | ao iniciar, a cada 4h, botão, webhook | lê item → contas → transações (janela 90d, ou completa) → faturas → investimentos (+mov.) → empréstimos → identidade; grava bruto e normaliza; snapshots do dia |
| `ledger_rebuild` | após cada sync, ao alterar regra/ajuste | eventos, reconciliação, fila de revisão, auditoria |
| `market_sync` | ao iniciar e diariamente 19h45 | SGS (CDI 12, Selic 11, IPCA 433), Yahoo (ativos com ticker, ^BVSP, ^GSPC, BRL=X, proxies) |
| `net_worth_snapshot` | após sync | grava `daily_net_worth` |

MeuPluggy atualiza cada banco ~1x/24h e não aceita refresh manual — o app só **lê** (nunca `PATCH /items`). Falha numa etapa marca o run como `partial`, registra em `sync_events` e segue para as demais.

## 5. Categorização automática (motor)

Ordem de decisão por transação; a primeira que decidir vence e grava `rule_source` + `confidence`:

1. **Ajuste manual** (`event_overrides`) — 1.00
2. **Regras do usuário** (`category_rules`, por prioridade) — 0.95
3. **Estrutural** (reconciliação):
   * pagamento de fatura: categoria Pluggy 05100000 ou descrição ("pagamento de fatura") **e** existe cartão conectado com pagamento recebido / fatura de valor compatível (±R$1 ou ±2%, ±7 dias) → `CARD_PAYMENT` 0.95. Sem cartão correspondente → `EXPENSE` "Cartão não conectado" + revisão.
   * transferência própria: categoria 04*, ou CPF do pagador e do recebedor = CPF do titular, ou nome do titular na descrição; par encontrado em outra conta conectada (mesmo valor, ±3 dias) → `INTERNAL_TRANSFER`; sem par → `EXTERNAL_OWN_TRANSFER`.
   * investimento: categoria 03*, "Aplicação/Resgate RDB", "Valor recebido de Investimentos" → contribuição/resgate.
4. **Comerciante** (CNPJ ou alias normalizado) com categoria aprendida — 0.85
5. **Mapa Pluggy → plano de contas** — 0.50 a 0.80 (categorias genéricas como "Transfers", "Shopping" têm confiança baixa)
6. **Heurísticas** (MCC, CNAE, palavras-chave) — 0.40
7. Sem decisão → "A classificar" 0.10

**Aprendizado:** ao recategorizar manualmente uma transação com comerciante identificável, o sistema grava a categoria padrão do comerciante (e propõe aplicar às demais do mesmo comerciante). Regras podem ser criadas a partir de uma transação com pré-visualização do impacto.

**Fila de revisão** (`review_items`): sem categoria; confiança < 0.6 com |valor| ≥ R$ 50; Pix enviado a pessoa física (despesa? empréstimo? reembolso?); Pix recebido de pessoa física (receita ou reembolso?); pagamento de cartão sem cartão conectado; transferência própria sem par; despesa > 3× a mediana da categoria; possível duplicidade; item com erro; consentimento vencendo em < 30 dias; ativo sem preço; emissor acima do limite FGC.

## 6. Plano de contas e demonstrativos

### DRE pessoal (competência)
```
  Receita operacional (salário, bolsa, freela, outras do trabalho)
+ Outras receitas (presentes, vendas, prêmios)
− Impostos sobre a renda
= RECEITA LÍQUIDA
− Custo de vida essencial    (moradia, mercado, transporte, saúde, educação, utilidades)
= MARGEM APÓS ESSENCIAIS
− Despesas de estilo de vida (restaurantes, delivery, lazer, compras, assinaturas, viagens…)
− Transferências a terceiros não classificadas
= RESULTADO OPERACIONAL
+ Receitas financeiras (dividendos, juros em conta, cashback)
− Despesas financeiras (juros, IOF, multas, tarifas)
= RESULTADO LÍQUIDO (poupança do período)       → taxa de poupança = RL / Receita líquida
± Valorização da carteira (Δ valor investido − aportes líquidos; só com snapshots)
= RESULTADO ECONÔMICO
```
Compras no cartão entram na data da compra (competência). Parcelado: cada parcela na data do lançamento da parcela (padrão da fonte). Reembolsos reduzem a categoria da despesa original.

### DFC (método direto, caixa)
* **Operacional**: receitas recebidas − despesas pagas em conta − **pagamentos de fatura** (o cartão vira caixa no pagamento).
* **Investimento**: − aportes + resgates.
* **Financiamento**: + empréstimos − amortizações ± transferências com contas próprias não conectadas.
* **Variação de caixa** = soma; **conferência** contra Δ saldo das contas (diferença exibida).

### Balanço patrimonial (data de corte)
* **Ativo**: caixa (contas), investimentos por classe, ativos manuais.
* **Passivo**: cartão – fatura aberta, cartão – parcelas futuras, empréstimos, passivos manuais.
* **PL** = Ativo − Passivo. Premissas visíveis: fonte do saldo, data, se é inferido.
* Histórico: snapshots diários; antes do 1º snapshot, saldo de conta é **reconstruído** (saldo atual − fluxos posteriores) e marcado como inferido.

## 7. Carteira

* **Classificação**: `assets` por regra (tipo/subtipo/indexador Pluggy + ticker conhecido) → classe (`RF Pós`, `RF Pré`, `RF IPCA+`, `Tesouro Selic`, `Tesouro IPCA+`, `Ações BR`, `FIIs`, `ETF BR`, `ETF Internacional`, `ETF Renda Fixa`, `Fundos`, `Previdência`, `Cripto`, `COE`, `Outros`), indexador, liquidez, emissor (FGC).
* **Posição**: saldo bruto, custo (amountOriginal), resultado, % do total, taxa contratada, vencimento.
* **Retorno**:
  * por ativo desde a compra (saldo/custo − 1) e anualizado quando há data;
  * **TWR** diário encadeado a partir de `investment_balances` com fluxos do dia (aportes/resgates) — `r_t = (V_t − F_t)/V_{t−1} − 1`;
  * comparação com CDI, IPCA, IBOV, S&P (BRL) no mesmo período.
* **Risco ex-ante** (pesos atuais × histórico 1–2 anos de retornos diários): vol anualizada, Sharpe e Sortino (excesso sobre CDI), VaR/CVaR 95% (histórico, 1d e 21d), drawdown máximo da carteira hipotética, beta vs IBOV, matriz de correlação, contribuição marginal ao risco. RF pós-fixada usa CDI × %contratado; Tesouro IPCA+ usa proxy IMAB11; tudo identificado como **proxy/inferido**.
* **Concentração**: HHI, top-5, exposição por emissor vs limite FGC (R$ 250 mil por CPF por instituição), por indexador e por liquidez; ladder de vencimentos.

## 8. Telas (frontend)

| Rota | Conteúdo |
|---|---|
| `/` Painel | PL e composição, resultado do mês (DRE resumida), taxa de poupança, capacidade de investimento, compromissos 3m, alertas, top categorias, evolução do PL |
| `/razao` | todas as transações/eventos: filtros, edição inline (categoria/tipo), seleção em massa, criar regra, gaveta com proveniência (payload bruto, regra, confiança, histórico) |
| `/dre` | matriz mês × linha (expansível até subcategoria), AV/AH, clique → razão filtrado |
| `/dfc` | matriz + Sankey do mês + conferência de caixa |
| `/balanco` | BP na data, evolução empilhada, premissas |
| `/categorias` | árvore com orçamento × realizado, tendência; página da categoria (histórico, comerciantes, transações) |
| `/comerciantes` | ranking, frequência, ticket médio, categoria padrão |
| `/cartoes` | limite, faturas, parcelas, compromissos por mês |
| `/carteira` | posições, alocação, FGC, vencimentos, performance, risco, correlação |
| `/planejamento` | previsão de liquidez 6m, recorrências/assinaturas, metas, capacidade de investimento |
| `/revisao` | fila com ações rápidas |
| `/regras` | CRUD com pré-visualização |
| `/conexoes` | itens, consentimento, runs, log técnico, webhooks, sync manual |
| `/config` | contas (apelido, finalidade), ativos manuais, ativos/tickers, exportação CSV/Excel |

## 9. Segurança
* Login local (usuário único) com argon2; sessão em cookie `HttpOnly` assinado (12h). Primeiro acesso cria a senha.
* `PLUGGY_CLIENT_SECRET` só no backend (.env). Navegador recebe apenas o connect token (30 min, sem acesso a dados).
* Porta publicada só em `127.0.0.1`. Webhook não autenticado apenas enfileira releitura do item (nunca grava dados do payload).
* Backup: `scripts/backup.ps1` → `pg_dump` para `backups/`.

## 10. Fora do escopo (v1)
Movimentar dinheiro, pagamentos, recomendações automáticas de investimento, ordens de compra/venda, multiusuário, otimização automática de carteira.

## 11. Roadmap
* **v1 (esta entrega)**: tudo acima.
* **v1.1**: splits de transação; importação de notas de corretagem (produto BROKERAGE_NOTE) e extrato B3 para preço médio; reconstrução histórica de RF pós por acúmulo de CDI; tags.
* **v1.2**: metas com simulação (Monte Carlo), orçamento base-zero, alertas por e-mail/Telegram, troca de categorização por modelo ML (TF-IDF + regressão logística treinada nos seus ajustes).
* **v2**: otimização de carteira (fronteira eficiente, risk parity) apenas como análise, IR (ganho de capital, come-cotas, DARF).
