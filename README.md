# CFO Central

Livro razão financeiro pessoal, local e auditável, alimentado pelo Open Finance (MeuPluggy). Converte transações em
eventos econômicos e entrega **DRE, DFC e Balanço** mensais com drill-down, categorização automática que aprende com
você, fila de revisão, previsão de caixa e **métricas de carteira** (retorno, risco, concentração, FGC).

Especificação completa: [`docs/SPEC.md`](docs/SPEC.md).

**Demonstração:** o workflow `.github/workflows/demo-pages.yml` publica no GitHub Pages uma vitrine do app com
dados fictícios (sem servidor; alterações não são salvas). Para ativar, uma vez: *Settings → Pages → Source:
GitHub Actions*. Localmente: `python -m scripts.demo_showcase`, `cd frontend && npm run build:demo`,
`python -m scripts.demo_snapshot frontend/dist-demo/demo-data.json`.

## Como rodar

**Com Docker (recomendado — PostgreSQL):** dois cliques em `INICIAR.bat`.
Na primeira vez ele cria o `.env` (gera senhas locais), sobe o Postgres e o app e abre `http://127.0.0.1:8060`.
Crie seu usuário no primeiro acesso: o Painel vira um passo a passo (chave da Pluggy → conectar banco → importar),
sem editar arquivo nenhum. A chave da Pluggy e o e-mail de alertas ficam em **Configurações** e valem por cima do `.env`.

| Arquivo | Faz |
|---|---|
| `INICIAR.bat` | sobe banco + app (Docker Desktop) e abre o navegador |
| `PARAR.bat` | desliga os containers (dados ficam no volume `cfo_pgdata`) |
| `BACKUP.bat` | `pg_dump` para `backups\` |
| `INICIAR-SEM-DOCKER.bat` | alternativa sem Docker: venv + SQLite em `data\cfo-central.db` |

Para conectar bancos: **Conexões → Conectar → MeuPluggy**.

O Postgres fica exposto só em `127.0.0.1:5433` (usuário `cfo`, senha no `.env`) para Power BI, DBeaver ou Excel.

## O que acontece por baixo

```
Pluggy (MeuPluggy) ──▶ raw_payloads (bruto versionado, nunca alterado)
                     ──▶ espelho normalizado (contas, transações, faturas, investimentos, empréstimos, identidade)
                     ──▶ conciliação (faturas, transferências próprias, aportes/resgates, parcelas)
                     ──▶ categorização (ajuste manual > sua regra > conciliação > comerciante aprendido > Pluggy > palavras-chave)
                     ──▶ financial_events (+ auditoria + fila de revisão)
                     ──▶ DRE · DFC · Balanço · carteira · previsões
BCB/SGS (CDI, Selic, IPCA) + Yahoo (ETFs, ações, Ibovespa, S&P, dólar) ──▶ métricas de carteira
```

- **Agenda:** Pluggy a cada 4 h (o MeuPluggy atualiza cada banco ~1×/dia) e mercado diariamente às 19h45; botão **Sincronizar** a qualquer momento.
- **Idempotente:** reprocessar não duplica nada. Transação que some da fonte (pendente → efetivada) é marcada como removida, não apagada.
- **Contabilidade:** compra no cartão é despesa na data da compra; pagamento de fatura é liquidação (fora da DRE); aporte e resgate não são despesa/receita; transferência entre contas próprias não entra no resultado.
- **Tudo explicável:** cada lançamento mostra regra aplicada, confiança, se é inferido, payload bruto e histórico de mudanças.

## Primeiros 15 minutos (recomendado)

O Painel mostra um checklist de **Primeiros passos** até tudo estar feito (e um aviso de *números provisórios*
enquanto a maior parte da renda estiver "a classificar"):

1. **Revisão** → as *decisões rápidas* vêm primeiro (um clique vale para todos os lançamentos da contraparte). Ex.: o Pix mensal do seu empregador → *Salário/bolsa*. Avisos do sistema ficam numa seção separada.
2. **Conexões** → dê o nome de cada banco (no lugar de "MeuPluggy"); ele aparece na carteira e no IR.
3. **Categorias** → defina orçamentos mensais nas categorias que importam.
4. **Configurações → Ativos** → confira classe e ticker dos investimentos (ex.: um ETF classificado errado).
5. **Planejamento** → defina a meta de aporte, confirme as recorrências e crie metas.

Termos técnicos (DRE, competência, VaR, Sharpe, TIR…) têm explicação ao passar o mouse ou tocar. Funciona no celular.

## Gestão e planejamento

- **DRE gerencial** (`/dre-gerencial`): mês × média 6m, Δ, % da receita, orçamento e acumulado do ano; resultado
  recorrente separado de itens extraordinários (herança/doações) e indicadores (poupança, reserva em meses, parcelas).
- **Quanto posso gastar** (Painel): renda prevista (sem bônus) − meta de aporte − gasto do mês − recorrências a vencer.
  Sem meta definida, a sugestão é 20% da renda limitada à sobra mediana dos 3 meses anteriores.
- **Política de investimentos** (Planejamento): alocação-alvo por classe com banda ±5 p.p., reserva mínima em meses;
  desvios viram itens de revisão. Metas com **Monte Carlo** (4.000 cenários, risco da carteira).
- **Retorno por título** (Carteira): aplicado, resgatado, IR/IOF, resultado, TIR e % CDI, inclusive títulos resgatados.
  Custo de renda variável só com evidência (negociação da Pluggy, débito no banco ou estimativa marcada).
- **Alertas por e-mail**: resumo diário de alertas novos e fechamento no dia 1 (em **Configurações**, com uma senha
  de app do Gmail; também aceita `SMTP_USER`/`SMTP_PASSWORD` no `.env`).
- **Backup automático**: serviço `backup` faz `pg_dump` diário em `backups/` e mantém 30 dias.

## Guia do CFO ("Seu CFO hoje")

O Painel abre com um guia curto: quanto ainda dá para gastar no mês, o que pede atenção agora (conexão caída,
fatura que o saldo não cobre, orçamento estourado, caixa negativo à frente, reserva abaixo do mínimo, decisões
pendentes, fechamento do mês) e os vencimentos dos próximos 10 dias. Cada aviso tem uma ação e um "Entendi", que o
esconde até a situação mudar. Os avisos são calculados pelo app (`app/analytics/guia.py`) a partir do razão já
conferido.

**Resumo diário com o Claude (opcional, usa o seu plano Pro/Max, sem chave de API):** dois cliques em
**`AGENDAR-RESUMO.bat`** criam uma tarefa no Agendador do Windows que, todo dia às 7h30, roda o Claude Code
(`claude -p --model sonnet`) com acesso só às ferramentas `guia`, `publicar_briefing`, `revisoes` e `lancamentos`.
Ele escreve 2 a 4 frases e escolhe a ordem dos avisos. O app recusa o texto se ele citar um valor em R$ que não
esteja nos fatos ou um aviso que não existe; sem resumo recente (36 h), o Painel mostra só os avisos calculados.
Pré-requisitos: Claude Code instalado e logado uma vez (`claude`), app rodando. Log em `logs\resumo-diario.log`.

## Assistente integrado (MCP)

O CFO Central expõe um servidor MCP (`app/assistant/mcp_server.py`) para o Claude consultar e curar os dados
direto do banco local. Instale uma vez com dois cliques em **`INSTALAR-MCP.bat`** (registra no Claude Desktop e,
se existir, no Claude Code) e reabra o Claude Desktop. Sessões do Claude ligadas a este PC também enxergam o servidor.

```
Claude ──stdio──▶ docker exec -i cfo-central-app-1 python -m app.assistant.mcp_server
                    ├─ leitura: Postgres direto (DRE, DFC, balanço, razão, carteira, revisões, SQL somente leitura)
                    └─ escrita: ajuste/regra/comerciante/revisão (auditado como "assistente")
                                → reconstrução pedida ao app em 127.0.0.1:8000 (token interno, só dentro do container)
```

| Ferramentas | |
|---|---|
| Leitura | `guia`, `visao_geral`, `dre`, `dfc`, `balanco`, `cartoes`, `carteira`, `planejamento`, `lancamentos`, `lancamento`, `categorias`, `gastos_por_categoria`, `comerciantes`, `contas`, `revisoes`, `regras`, `esquema`, `consulta_sql` |
| Curadoria | `publicar_briefing`, `classificar_lancamentos`, `remover_ajuste`, `classificar_comerciante`, `simular_regra`, `criar_regra`, `desativar_regra`, `resolver_revisao`, `configurar_conta`, `definir_orcamento` |
| Operação | `sincronizar`, `reconstruir_razao` |

Nada no servidor move dinheiro ou opera investimentos. `consulta_sql` roda em transação somente leitura
(timeout 15 s, tabela `users` bloqueada). Toda escrita fica no histórico do lançamento (Razão → detalhe).

## Curadoria versionada

`curadoria/curadoria.json` guarda decisões revisadas (apelidos de contas, categorias de comerciantes, regras e
ajustes). Reaplique a qualquer momento: `docker compose exec app python -m scripts.cli curate curadoria/curadoria.json`.

## Desenvolvimento

```bash
pip install -r requirements.txt pytest
pytest                                   # 77 testes (SQLite); TEST_DATABASE_URL=postgresql+psycopg://... para Postgres
python -m scripts.demo_seed              # banco de demonstração com dados fictícios
python -m scripts.demo_snapshot frontend/dist-demo/demo-data.json   # vitrine estática (após cd frontend && npm run build:demo)
python -m scripts.cli sync|rebuild|market|summary|export arquivo.xlsx
uvicorn app.main:app --reload --port 8060
cd frontend && npm install && npm run dev   # front em :5173 com proxy para :8060
alembic revision --autogenerate -m "..."    # nova migração após mudar modelos
```

Estrutura: `app/` (connectors, ingestion, normalization, categorization, reconciliation, accounting, portfolio,
analytics, alerts, api), `frontend/` (React + Vite + ECharts), `migrations/` (Alembic), `tests/`.

## Limites conhecidos

- A Pluggy não informa custo médio de ETFs/ações do Nubank: resultado por ativo aparece só quando há custo (v1.1: notas de corretagem/B3).
- Retorno realizado (TWR) começa a contar do primeiro snapshot diário; antes disso, a carteira usa histórico com pesos atuais (ex-ante, marcado como proxy).
- Meses anteriores ao primeiro snapshot no Balanço são reconstruídos a partir dos lançamentos (marcados como estimados).
