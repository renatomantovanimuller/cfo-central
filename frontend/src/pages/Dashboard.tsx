import { QueryState } from "../components/QueryState";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Chart, colorFor, cssVar, kTick } from "../components/Chart";
import { signTone } from "../components/MoneyText";
import { useMonth } from "../components/Layout";
import { Delta, Empty, Money, Panel } from "../components/ui";
import { ProvisionalBanner, SetupChecklist, Welcome } from "../components/Onboarding";
import { reviewSummary } from "../components/reviewBadge";
import { Term } from "../components/Term";
import { useOnboarding } from "../hooks/useOnboarding";
import { brl, compact, date, isPartialMonth, monthAxisLabel, monthLabel, monthLong, PARTIAL_OPACITY, pct, prettyName, today } from "../format";

export default function Dashboard() {
  const { month } = useMonth();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["overview", month], queryFn: () => api<any>(`/api/overview?month=${month}`) });
  const hist = useQuery({ queryKey: ["bp-history"], queryFn: () => api<any[]>("/api/balance/history?months=12") });
  const reviews = useQuery({ queryKey: ["reviews-count"], queryFn: () => api<any[]>("/api/reviews") });
  const sp = useQuery({ queryKey: ["spending", month, 1, ""], queryFn: () => api<any>(`/api/spending?end=${month}&months=1`) });
  const perf = useQuery({ queryKey: ["portfolio-performance"], queryFn: () => api<any>("/api/portfolio/performance") });
  const ob = useOnboarding();
  const d = q.data;
  if (ob.data && ob.data.events === 0) return <Welcome />;
  if (!d) return <QueryState q={q} what="o painel">{() => null}</QueryState>;
  const t = d.position.totals;
  const k = d.kpis;
  const assets = t.cash + t.investments + (t.in_transit ?? 0) + t.manual_assets;
  const maxBar = Math.max(assets, t.card_current + t.card_future + t.loans, 1);
  const classes = Object.entries(d.position.investments_by_class as Record<string, number>).sort((a, b) => b[1] - a[1]);
  const series = d.series as any[];
  const hasData = series.some((s) => s.receita_liquida || s.despesas);
  const rv = reviewSummary(reviews.data);
  const spCats: any[] = (sp.data?.categories ?? []).filter((c: any) => c.value > 0);
  const catColor = colorFor(spCats.slice(0, 8).map((c) => c.name));
  const nwPrev = hist.data && hist.data.length > 1 ? hist.data[hist.data.length - 2].net_worth : null;
  const nwDelta = nwPrev !== null ? t.net_worth - nwPrev : null;

  return (
    <>
      <ProvisionalBanner />
      <SetupChecklist />
      <section className="panel networth">
        <div className="figure">
          <div className="lbl"><Term k="patrimonio">Patrimônio líquido hoje</Term></div>
          <div className={`big ${t.net_worth < 0 ? "neg" : ""}`}>{brl(t.net_worth)}</div>
          {nwDelta !== null && Math.abs(nwDelta) >= 1 && <div className="small" style={{ marginTop: -4, marginBottom: 6 }}>
            <Money v={nwDelta} digits={0} tone={signTone(nwDelta)} /> <span className="soft">desde o fechamento anterior{nwPrev ? ` (${nwDelta > 0 ? "+" : ""}${pct(nwDelta / Math.abs(nwPrev), 1)})` : ""}</span></div>}
          <div className="soft small"><Term k="liquidez">Disponível em até 1 dia</Term>: {brl(t.liquid_net_worth)}</div>
          {hist.data && hist.data.length > 1 && (
            <Chart height={120} option={{
              legend: false, grid: { left: 0, right: 0, top: 10, bottom: 0, containLabel: false },
              tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v) },
              xAxis: { type: "category", data: hist.data.map((h) => h.date), show: false },
              yAxis: { type: "value", show: false, scale: true },
              series: [{ type: "line", data: hist.data.map((h) => Math.round(h.net_worth)), smooth: true, symbol: "none",
                lineStyle: { width: 2, color: cssVar("--ledger") }, areaStyle: { color: cssVar("--ledger-soft") } }],
            }} />
          )}
          {!hist.data && hist.isError && <p className="note">Não foi possível carregar o histórico do patrimônio.</p>}
          {hist.data?.some((h) => h.inferred) && <p className="note">Histórico antes do primeiro snapshot é reconstruído a partir dos lançamentos (estimado).</p>}
        </div>
        <div className="compo">
          <Bar label="Caixa em conta" v={t.cash} max={maxBar} />
          {classes.map(([c, v]) => <Bar key={c} label={c} v={v} max={maxBar} soft />)}
          {(t.in_transit ?? 0) > 0 && (
            <div title={(d.position.in_transit ?? []).map((x: any) => `${x.name}: ${brl(x.amount)} (saída em ${date(x.date)})`).join(", ")}>
              <Bar label="Valores em trânsito" v={t.in_transit} max={maxBar} soft />
              <div className="note"><button className="btn sm ghost" onClick={() => nav("/revisao")}>Revisar saídas sem contrapartida</button></div>
            </div>
          )}
          {t.manual_assets > 0 && <Bar label="Ativos manuais" v={t.manual_assets} max={maxBar} soft />}
          <Bar label="Cartão – fatura atual" v={-t.card_current} max={maxBar} debit />
          <Bar label="Cartão – a faturar" v={-t.card_future} max={maxBar} debit />
          {t.loans > 0 && <Bar label="Empréstimos" v={-t.loans} max={maxBar} debit />}
          <details style={{ marginTop: 6 }}><summary className="note">Premissas deste número</summary>
            <ul className="assumptions">{d.position.assumptions.map((a: string, i: number) => <li key={i}>{a}</li>)}</ul></details>
        </div>
      </section>

      <section className="panel strip" aria-label={`Resultado de ${monthLong(month)}`}>
        <div><div className="lbl"><Term k="receita_liquida">Receita recorrente</Term></div><div className="val num" style={{ textAlign: "left" }}>{brl(k.current.receita_liquida)}</div>
          <div className="sub"><Delta cur={k.current.receita_liquida} ref_={k.previous.receita_liquida} /> sobre {monthLabel(series[series.length - 2]?.month ?? month)}
            {k.current.eventuais ? <> · + {compact(k.current.eventuais)} eventual</> : null}</div></div>
        <div><div className="lbl">Despesas</div><div className="val num" style={{ textAlign: "left" }}>{brl(k.current.despesas)}</div>
          <div className="sub"><Delta cur={k.current.despesas} ref_={k.previous.despesas} invert /> · média 6m {compact(k.avg6.despesas)}</div></div>
        <div><div className="lbl"><Term k="resultado_recorrente">Sobra do mês</Term></div><div className={`val num ${k.current.resultado < 0 ? "neg" : "pos"}`} style={{ textAlign: "left" }}>{brl(k.current.resultado)}</div>
          <div className="sub">média 6m {compact(k.avg6.resultado)}{k.current.eventuais ? ` · + ${compact(k.current.eventuais)} eventual` : ""}{k.current.extraordinarios ? ` · + ${compact(k.current.extraordinarios)} extraordinário` : ""}</div></div>
        <div><div className="lbl"><Term k="poupanca">Taxa de poupança</Term></div><div className="val" >{pct(k.current.taxa_poupanca, 0)}</div>
          <div className="sub">média 6m {pct(k.avg6.taxa_poupanca, 0)}</div></div>
        <div><div className="lbl"><Term k="aporte">Investido no mês</Term></div><div className="val num" style={{ textAlign: "left" }}>{brl(k.invested_net)}</div>
          <div className="sub">aplicações menos resgates</div></div>
        <div><div className="lbl"><Term k="capacidade">Capacidade de investir</Term></div><div className={`val num ${d.capacity.median_result_6m < 0 ? "neg" : ""}`} style={{ textAlign: "left" }}>{compact(d.capacity.median_result_6m)}</div>
          <div className="sub">mediana mensal 6m; {compact(d.capacity.card_commitments_3m)} em parcelas nos próximos 3m</div></div>
      </section>

      {d.safe_to_spend && <SafeToSpend s={d.safe_to_spend} onPlan={() => nav("/planejamento")} />}

      {!hasData && <Panel><Empty title={`Sem lançamentos em ${monthLong(month)}`}>Escolha outro mês no seletor acima ou sincronize para buscar novidades.</Empty></Panel>}

      {hasData && <div className="grid g-wide">
        <Panel title="Receitas, despesas e resultado" hint={<>13 meses, <Term k="competencia">por competência</Term></>}>
          <Chart height={280} onClick={(p) => p.name && nav(`/dre`)} option={{
            tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v) },
            xAxis: { type: "category", data: series.map((s) => monthAxisLabel(s.month)) },
            yAxis: { type: "value", axisLabel: { formatter: kTick } },
            series: [
              { name: "Receita recorrente", type: "bar", stack: "rec", data: series.map((s) => ({ value: Math.round(s.receita_liquida), ...(isPartialMonth(s.month) && { itemStyle: { opacity: PARTIAL_OPACITY } }) })), itemStyle: { color: cssVar("--ledger") }, barGap: "8%" },
              ...(series.some((s) => s.eventuais) ? [{ name: "Bônus, PLR e outras eventuais", type: "bar", stack: "rec", data: series.map((s) => Math.round(s.eventuais ?? 0)),
                itemStyle: { color: cssVar("--ledger"), opacity: 0.45, borderRadius: [2, 2, 0, 0] } }] : []),
              { name: "Despesas", type: "bar", data: series.map((s) => ({ value: Math.round(s.despesas), ...(isPartialMonth(s.month) && { itemStyle: { opacity: PARTIAL_OPACITY * .8 } }) })), itemStyle: { color: cssVar("--debit"), opacity: .82, borderRadius: [2, 2, 0, 0] } },
              { name: "Resultado", type: "line", data: series.map((s) => Math.round(s.resultado)), symbolSize: 5, lineStyle: { width: 2, color: cssVar("--ink") }, itemStyle: { color: cssVar("--ink") } },
            ],
          }} />
        </Panel>
        <Panel title="Para onde foi o dinheiro" hint={`${monthLong(month)}, contra o mês anterior`}
          tools={<button className="btn sm ghost" onClick={() => nav("/gastos")}>Abrir Gastos →</button>}>
          {!sp.data ? <QueryState q={sp} what="as categorias" layout="panel">{() => null}</QueryState>
            : spCats.length === 0 ? <p className="muted">Sem despesas neste mês.</p> : <>
            <div className="stack-bar" role="img" aria-label="Divisão do gasto do mês por categoria">
              {spCats.map((c) => <i key={c.id} title={`${c.name}: ${brl(c.value, 0)}`} style={{ flexGrow: c.value, background: catColor(c.name) }} />)}</div>
            {spCats.slice(0, 7).map((c) => (
              <button key={c.id} className="cat-row dash" onClick={() => nav(`/razao?category=${c.id}&month=${month}`)}>
                <i className="sw" style={{ background: catColor(c.name) }} />
                <span className="nm" title={c.name}>{c.name}</span>
                <span className="num">{brl(c.value, 0)}</span>
                <span className="num soft small">{pct(c.value / sp.data.totals.value, 0)}</span>
                <DeltaSpend cur={c.value} prev={c.prev} />
              </button>))}
            {spCats.length > 7 && <p className="note">+ {spCats.length - 7} categorias somando {brl(spCats.slice(7).reduce((a, c) => a + c.value, 0), 0)}.</p>}
          </>}
        </Panel>
      </div>}

      {hasData && <div className="grid g3">
        <Panel title="Ritmo de gastos" hint="acumulado no mês contra o mês anterior">
          <Chart height={240} option={{
            tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v) },
            xAxis: { type: "category", data: Array.from({ length: 31 }, (_, i) => i + 1) },
            yAxis: { type: "value", axisLabel: { formatter: kTick } },
            series: [
              { name: monthLabel(month), type: "line", data: trimFuture(d.daily.current, month), symbol: "none", lineStyle: { width: 2.5, color: cssVar("--ledger") } },
              { name: "Mês anterior", type: "line", data: d.daily.previous, symbol: "none", lineStyle: { width: 1.5, type: "dashed", color: cssVar("--slate") } },
              ...(d.daily.budget ? [{ name: "Orçamento", type: "line", data: Array(31).fill(d.daily.budget), symbol: "none", lineStyle: { width: 1, color: cssVar("--ochre") } }] : []),
            ],
          }} />
        </Panel>
        <PortfolioCard perf={perf.data} onOpen={() => nav("/carteira")} />
        <Panel title="Maiores comerciantes" hint={monthLong(month)}>
          {d.top_merchants.length === 0 ? <p className="muted">Sem gastos identificados.</p> : d.top_merchants.map((m: any) => (
            <div key={m.id} className="list-row" style={{ cursor: "pointer" }} onClick={() => nav(`/razao?merchant=${m.id}&month=${month}`)}>
              <div className="grow"><div className="t" title={m.name}>{prettyName(m.name)}</div></div><Money v={m.value} colored={false} />
            </div>
          ))}
          {rv.pending > 0 && (
            <p className="note" style={{ marginTop: 10 }}>
              {rv.pending} {rv.pending === 1 ? "decisão pendente" : "decisões pendentes"}{rv.notices ? ` e ${rv.notices} ${rv.notices === 1 ? "aviso" : "avisos"}` : ""} na revisão.{" "}
              <a href="/revisao" onClick={(e) => { e.preventDefault(); nav("/revisao"); }}>Abrir revisão</a>
            </p>
          )}
        </Panel>
      </div>}
    </>
  );
}

function SafeToSpend({ s, onPlan }: { s: any; onPlan: () => void }) {
  const used = s.renda_prevista > 0 ? (s.gasto_ate_hoje + s.comprometido + s.meta_aporte) / s.renda_prevista : 0;
  return (
    <section className="panel safe">
      <div className="safe-main">
        <div className="lbl">Quanto ainda posso gastar em {monthLong(s.mes).split(" ")[0]}</div>
        <div className={`big ${s.disponivel < 0 ? "neg" : ""}`}>{brl(s.disponivel, 0)}</div>
        <div className="soft small">{s.disponivel < 0
          ? `O mês já passou do previsto em ${brl(-s.disponivel, 0)}. Segure gastos não essenciais até o próximo salário.`
          : s.por_dia !== null ? `${brl(s.por_dia, 0)} por dia nos próximos ${s.dias_restantes} dias` : ""}</div>
      </div>
      <div className="safe-calc">
        <div className="bar" style={{ height: 12 }}><i style={{ width: `${Math.min(100, used * 100)}%`, background: used > 1 ? "var(--debit)" : undefined }} /></div>
        <dl className="kv" style={{ marginTop: 10 }}>
          <dt>Renda prevista</dt><dd className="num">{brl(s.renda_prevista)}</dd>
          <dt>− Meta de aporte</dt><dd className="num">{brl(s.meta_aporte)} <button className="btn sm ghost" onClick={onPlan}>{s.meta_aporte_origem === "plano" ? "ajustar" : "definir"}</button>
            {s.meta_aporte_origem === "padrao_limitado" && <div className="note" style={{ whiteSpace: "normal" }}>sugestão limitada ao que sobrou nos últimos meses</div>}</dd>
          <dt>− Gasto até hoje</dt><dd className="num">{brl(s.gasto_ate_hoje)}</dd>
          <dt>− Recorrências a vencer</dt><dd className="num">{brl(s.comprometido)}{s.recorrencias_pendentes.length ? ` (${s.recorrencias_pendentes.length})` : ""}</dd>
        </dl>
        <details><summary className="note">Premissas</summary><ul className="assumptions">{s.premissas.map((p: string, i: number) => <li key={i}>{p}</li>)}</ul></details>
      </div>
    </section>
  );
}

function trimFuture(arr: number[], month: string) {
  const now = today();
  const cur = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  return month === cur ? arr.map((v, i) => (i + 1 > now.getDate() ? null : v)) : arr;
}

function Bar({ label, v, max, soft, debit }: { label: string; v: number; max: number; soft?: boolean; debit?: boolean }) {
  return (
    <div className="bar-row">
      <span className={soft ? "soft" : ""} title={label} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", paddingLeft: soft ? 10 : 0 }}>{label}</span>
      <div className={`bar ${debit ? "debit" : ""}`}><i style={{ width: `${Math.min(100, (Math.abs(v) / max) * 100)}%`, opacity: soft ? .7 : 1 }} /></div>
      <Money v={v} />
    </div>
  );
}

function DeltaSpend({ cur, prev }: { cur: number; prev: number }) {
  if (!prev || Math.abs(prev) < 1) return <span className="muted small">novo</span>;
  const d = (cur - prev) / Math.abs(prev);
  return <span className={`small ${d > 0.005 ? "neg" : d < -0.005 ? "pos" : "muted"}`}>{d > 0 ? "+" : d < 0 ? "−" : ""}{Math.abs(d * 100).toFixed(0)}%</span>;
}

/** Resumo da carteira no painel: valor, retorno de 12 meses contra o CDI e evolução desde o início. */
function PortfolioCard({ perf, onOpen }: { perf: any; onOpen: () => void }) {
  if (!perf?.available) return (
    <Panel title="Carteira"><p className="muted">{perf ? perf.reason : "Carregando…"}</p></Panel>);
  const y = perf.total.periodos["12m"] ?? {}, all = perf.total.periodos["inicio"] ?? {};
  const cdi = perf.referencias["12m"]?.CDI;
  const curve = perf.curva as any[];
  return (
    <Panel title="Carteira" tools={<button className="btn sm ghost" onClick={onOpen}>Abrir →</button>}>
      <div className="evo-sum" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
        <div><span>Investido hoje</span><b><Money v={perf.total.valor} digits={0} /></b></div>
        <div><span><Term k="twr">Retorno 12m</Term></span><b className={(y.twr ?? 0) < 0 ? "neg" : ""}>{pct(y.twr, 1)}</b></div>
        <div><span>CDI 12m</span><b className="soft">{pct(cdi, 1)}</b></div>
        <div><span>Ganho desde {date(all.inicio)}</span><b><Money v={all.ganho} digits={0} tone={signTone(all.ganho)} /></b></div>
      </div>
      {curve.length > 1 && <Chart height={110} option={{
        legend: false, grid: { left: 0, right: 0, top: 8, bottom: 0, containLabel: false },
        tooltip: { trigger: "axis", valueFormatter: (v: number) => (v == null ? "—" : `${v.toFixed(1).replace(".", ",")}%`) },
        xAxis: { type: "category", data: curve.map((c) => date(c.date)), show: false },
        yAxis: { type: "value", show: false, scale: true },
        series: [{ name: "Carteira", type: "line", symbol: "none", data: curve.map((c) => c.Carteira), lineStyle: { width: 2, color: cssVar("--ink") } },
          { name: "CDI", type: "line", symbol: "none", data: curve.map((c) => c.CDI), lineStyle: { width: 1.5, type: "dashed", color: cssVar("--viz-prior") } }],
      }} />}
      <p className="note">Linha cheia: carteira; tracejada: CDI, desde o início do histórico.</p>
    </Panel>
  );
}
