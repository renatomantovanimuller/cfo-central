# Proposta — controle do patrimônio, visão por conta/agregada, aportes e objetivos (out/2026)

Análise de como o CFO Central agrega contas, instituições, investimentos, ativos manuais e metas hoje
(`accounting/balance.py`, `portfolio/service.py`, `analytics/plano.py`, rotas de planejamento e telas Painel,
Balanço, Carteira, Planejamento e Configurações), com correções e novas funcionalidades.

## Parte A — Correções (problemas encontrados)

| # | Problema | Onde | Efeito | Proposta |
|---|---|---|---|---|
| C1 | "Disponível em até 1 dia" usa `liquid_net_worth`. Esse total soma **todos** os investimentos, exceto previdência e COE: entram CDB com resgate só no vencimento, fundos D+30, ações D+2 e Tesouro IPCA+ | `balance.current_position`, Painel | Na vitrine: **R$ 69,3 mil "disponível em 1 dia"**, acima do patrimônio líquido (R$ 66,8 mil). A liquidez real é R$ 8,0 mil | Usar `reserva_liquida` (D0/D1 sem marcação a mercado) para "disponível em 1 dia". Renomear o total amplo para "patrimônio financeiro" |
| C2 | Metas medidas por "investimentos" ou "patrimônio" usam **o total inteiro** cada uma | `routes_reports.planning` | Três metas mostram 100% de progresso com o mesmo dinheiro | Atribuir dinheiro a cada objetivo ("bolsos", P2); progresso = só o que está separado para a meta |
| C3 | A simulação de **cada** meta usa a meta de aporte mensal **inteira** | idem | Probabilidade inflada. A soma dos "aportes necessários" nunca é comparada com o aporte disponível | Distribuir o aporte entre metas (P3) e simular cada uma com o aporte que de fato recebe |
| C4 | No histórico estimado, ativos/passivos manuais e empréstimos entram com o **valor de hoje em todos os meses passados**, inclusive antes de existirem. Editar um ativo manual sobrescreve valor e data, sem guardar histórico | `balance.history`, `PUT /manual-assets` | Patrimônio passado distorcido; um imóvel cadastrado hoje "existia" há 18 meses | Histórico de valores por item manual (P6); no passado, usar o valor vigente na data e zero antes da aquisição |
| C5 | Nome da instituição resolvido de **4 jeitos** diferentes | Balanço/Carteira (apelido da conexão), IRPF (ignora "pluggy" e cai no nome da conta), Saúde dos dados (1ª palavra da conta), Configurações | "MeuPluggy" numa tela e "Nubank" em outra para o mesmo dinheiro | Uma função única `institution_label` usada por todas as telas |
| C6 | "Finalidade" da conta (Dia a dia, Reserva, Cartão principal) é gravada e **não entra em nenhum cálculo** | `AccountSetting.purpose` | Configuração que não tem efeito | Ligar às finalidades/bolsos (P2): conta "Reserva" conta como reserva e fica fora do "quanto posso gastar" |
| C7 | ~~Evolução do Painel diferente da do Balanço~~ **não procedia**: o Painel já usa `/api/balance/history`; o campo `net_worth_series` da API não é lido por nenhuma tela | — | — | — |
| C8 | Metas não podem ser editadas (só criadas e excluídas) e não têm prioridade nem tipo | rotas de metas | Para mudar o prazo é preciso recriar a meta | `PATCH /goals`, prioridade e tipo (P5) |

## Parte B — Novas implementações

### P1. "Onde está meu patrimônio": visão consolidada por instituição, conta e classe
Uma tela (ou uma aba do Balanço) que responde em uma olhada *onde está cada real* (valores ilustrativos):

```
Instituição      Caixa     Investimentos   Cartão/dívidas   Líquido     Liquidez 1 dia   FGC usado
Nubank           4.210     18.450 (RF Pós) −1.380           21.280      22.660           7%
XP               —         38.000          —                38.000      3.000            12%
Itaú             3.666     9.800 (Tes.IPCA+) −2.100         11.366      3.666            —
Imóvel (manual)  —         —               —                350.000     —                —
Total            7.876     66.250          −3.480           420.646     29.326
```
- Alternar o agrupamento: **instituição · classe · liquidez (D0/D1, até 30 dias, vencimento, ilíquido) · finalidade/bolso**.
- Drill-down: instituição → conta/posição → lançamentos/movimentações.
- Selo de **conferência por conta**: saldo informado pelo banco × saldo reconstruído pelos lançamentos (a checagem já existe em Saúde dos dados; aqui fica visível ao lado de cada conta).
- Treemap opcional para ver a proporção do patrimônio.
- Base: `current_position` + `positions` já trazem tudo. Falta agrupar com o rótulo único de instituição (C5) e a liquidez por posição.

### P2. Finalidades ("bolsos"): reserva, objetivos, aposentadoria e livre
Cada conta e cada investimento (ou uma parte dele, em R$ ou %) é atribuído a um bolso:
**Reserva de emergência · Objetivo X · Aposentadoria/IF · Livre**.
- Resolve C2 e C6: o progresso de cada meta é o que está no seu bolso, sem contar o mesmo dinheiro duas vezes.
  A reserva passa a ser o bolso Reserva, ou o cálculo automático por liquidez quando não houver bolso.
- Sugestão automática na primeira vez: liquidez diária → Reserva até a meta de meses; o resto → Livre.
- Evidência: separar o dinheiro por objetivo, com um rótulo visível, aumenta a poupança (Soman & Cheema). O
  investimento por objetivos trata risco como a chance de não atingir cada objetivo (Das, Markowitz et al.).
- Modelo: tabela `allocations(bucket_id, source_type [account|investment], source_id, amount|pct)` e
  `buckets(id, nome, tipo, meta_id)`.

### P3. Planejador de aportes (planejado × realizado)
Um "plano do mês" que distribui a meta de aporte e acompanha o que aconteceu:
- **Distribuição**:
  1. reserva (regra atual de degraus);
  2. metas por prioridade e prazo, com o aporte necessário de cada uma;
  3. sobra para a carteira, nas classes abaixo do alvo (regra atual).

  Mostra se a meta de aporte cobre a soma dos aportes necessários. Se não cobre, indica qual meta atrasa e quanto.
- **Realizado**: aportes líquidos do mês (eventos `INVESTMENT_CONTRIBUTION/REDEMPTION`), com o destino
  identificado pela movimentação do investimento. Gráfico de 12 meses planejado × realizado e sequência de meses
  cumpridos.
- **Alerta** no fechamento do mês quando o aporte ficou abaixo do planejado (e-mail mensal já existe).

### P4. Ponte do patrimônio (de onde veio a variação)
Waterfall mensal: **PL inicial + poupança do mês (resultado recorrente) + extraordinários + valorização dos
investimentos + variação de ativos manuais − novas dívidas = PL final**, com uma linha **"não explicado"** que
mostra lacunas de dados (conta não conectada, lançamento faltando).
- Base pronta: `dre` (resultado e extraordinários), `portfolio_valuation` (valorização) e `DailyNetWorth`.
- Responde "fiquei mais rico porque poupei ou porque o mercado subiu?", que é a pergunta central do controle
  patrimonial.

### P5. Metas 2.0
- Editar, priorizar e escolher o tipo: **prazo fixo** (viagem, entrada do imóvel), **reserva**,
  **aposentadoria/independência financeira** (valor = gasto anual ÷ taxa de retirada, com premissa editável) e
  **acúmulo livre**.
- Aporte necessário × aporte alocado (P3); semáforo (no ritmo / atrasada / em risco).
- Monte Carlo com o aporte que a meta de fato recebe (corrige C3).
- Alocação compatível com o horizonte: menos de 2 anos → pós-fixado/Tesouro Selic. O app avisa quando o dinheiro
  da meta está em renda variável e o prazo é curto.

### P6. Ativos e passivos manuais com histórico e atualização
- Histórico de valores (`manual_asset_values`): cada atualização vira um ponto, e o gráfico de patrimônio
  usa o valor vigente em cada data (corrige C4).
- **Regra de atualização** opcional: imóvel por índice (% ao ano ou IPCA); veículo com depreciação (% ao ano);
  dívida informal com parcelas.
- Data de aquisição: antes dela o item não entra no patrimônio.

### P7. Evolução por classe e por instituição
Área empilhada dos investimentos por classe e por instituição ao longo do tempo. As fotos diárias por investimento
(`investment_balances`) e a composição de `daily_net_worth` já existem; falta a série agregada e o gráfico.

### P8. Projeção do patrimônio
PL projetado em 1, 5 e 10 anos com o aporte do plano e o retorno esperado (real) da carteira, com bandas p10–p90.
O Monte Carlo já existe em `plano.monte_carlo`. Responde "quando chego a R$ X?" e alimenta a meta de independência
financeira.

## Status (out/2026)

Implementado: C1, C2, C3, C4, C5, C6, C8 e P1–P8, mais a tela **Hoje** (início do dia gamificado: missões
com XP, inventário, novidades, ontem, próximos 7 dias, conquistas e sequência de dias). C7 não procedia.
Testes em `tests/unit/test_patrimonio.py` e `tests/unit/test_hoje.py`; migrações `0005` (bolsos e metas) e
`0006` (histórico dos itens manuais).

## Prioridade sugerida

| Lote | Itens | Por quê |
|---|---|---|
| **1 — correções rápidas** | C1, C5, C7, C8 | Números errados ou inconsistentes que o usuário já vê; esforço baixo |
| **2 — visão e bolsos** | P1, P2 (resolve C2 e C6), P5 | O núcleo do pedido: ver tudo agregado e separar o dinheiro por objetivo |
| **3 — aportes e explicação** | P3 (resolve C3), P4 | Planejado × realizado e "de onde veio" a variação do patrimônio |
| **4 — complementos** | P6 (resolve C4), P7, P8 | Histórico de ativos manuais, evolução por classe e projeção |
