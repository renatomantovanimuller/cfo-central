import { QueryState } from "../components/QueryState";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { Chart, cssVar, palette } from "../components/Chart";
import { Chip, Empty, Money, Panel } from "../components/ui";
import { signTone } from "../components/MoneyText";
import { brl, date, pct } from "../format";

const GROUPS: [string, string][] = [["by_class", "Classe"], ["by_bucket", "Estratégia"], ["by_indexer", "Indexador"],
  ["by_liquidity", "Liquidez"], ["by_institution", "Instituição"], ["by_issuer", "Emissor"]];

export default function Portfolio() {
  const [group, setGroup] = useState("by_class");
  const [years, setYears] = useState(2);
  const q = useQuery({ queryKey: ["portfolio"], queryFn: () => api<any>("/api/portfolio") });
  const r = useQuery({ queryKey: ["risk", years], queryFn: () => api<any>(`/api/portfolio/risk?years=${years}`) });
  const d = q.data;
  if (!d) return <QueryState q={q} what="a carteira">{() => null}</QueryState>;
  if (!d.positions.length) return <Panel><Empty title="Nenhum investimento ativo">Os investimentos aparecem aqui depois da sincronização.</Empty></Panel>;
  const a = d.allocation;
  const st = r.data?.stats;
  const perf = d.performance;
  return (
    <>
      <section className="panel strip">
        <div><div className="lbl">Patrimônio investido</div><div className="val num" style={{ textAlign: "left" }}>{brl(a.total)}</div>
          <div className="sub">{d.positions.length} posições, {a.concentration.effective_n.toFixed(1).replace(".", ",")} posições efetivas</div></div>
        <div><div className="lbl">Retorno anualizado (proxy)</div><div className="val">{pct(st?.return_ann)}</div>
          <div className="sub">CDI no período {pct(st?.rf_ann)}</div></div>
        <div><div className="lbl">Volatilidade anual</div><div className="val">{pct(st?.vol_ann)}</div>
          <div className="sub">Sharpe {st?.sharpe?.toFixed(2).replace(".", ",") ?? "—"}; Sortino {st?.sortino?.toFixed(2).replace(".", ",") ?? "—"}</div></div>
        <div><div className="lbl">Pior queda</div><div className="val neg">{pct(st?.max_drawdown)}</div>
          <div className="sub">de {date(st?.dd_peak)} a {date(st?.dd_trough)}</div></div>
        <div><div className="lbl">VaR 95% em 1 mês</div><div className="val">{pct(st?.var95_21d)}</div>
          <div className="sub">≈ {brl((st?.var95_21d ?? 0) * a.total, 0)}; beta Ibov {st?.beta?.toFixed(2).replace(".", ",") ?? "—"}</div></div>
      </section>

      <div className="grid g-wide">
        <Panel title="Carteira atual contra referências" hint={`pesos de hoje aplicados aos últimos ${years} anos`}
          tools={<div className="segmented">{[1, 2, 3].map((y) => <button key={y} className={years === y ? "on" : ""} onClick={() => setYears(y)}>{y}a</button>)}</div>}>
          {r.data?.available ? (
            <Chart height={290} option={{
              tooltip: { trigger: "axis", valueFormatter: (v: number) => `${v?.toFixed(1).replace(".", ",")}%` },
              xAxis: { type: "category", data: r.data.curves.map((c: any) => date(c.date)) },
              yAxis: { type: "value", axisLabel: { formatter: (v: number) => `${v}%` } },
              series: Object.keys(r.data.curves[0]).filter((k) => k !== "date").map((k, i) => ({
                name: k, type: "line", symbol: "none", data: r.data.curves.map((c: any) => c[k]),
                lineStyle: { width: i === 0 ? 2.6 : 1.4, type: k === "CDI" ? "dashed" : "solid" },
              })),
            }} />
          ) : r.data ? <Empty title="Séries de mercado indisponíveis">{r.data.reason}</Empty> : <QueryState q={r} what="as séries de risco" layout="panel">{() => null}</QueryState>}
        </Panel>
        <Panel title="Alocação" tools={<select className="select" value={group} onChange={(e) => setGroup(e.target.value)}>
          {GROUPS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>}>
          <Chart height={200} option={{
            legend: false, tooltip: { trigger: "item", valueFormatter: (v: number) => brl(v) },
            series: [{ type: "pie", radius: ["58%", "88%"], label: { show: false }, itemStyle: { borderColor: cssVar("--sheet"), borderWidth: 2 },
              data: a[group].map((x: any) => ({ name: x.label, value: Math.round(x.value) })) }],
          }} />
          {a[group].map((x: any, i: number) => (
            <div key={x.label} className="bar-row" style={{ gridTemplateColumns: "12px minmax(0,1fr) 64px 110px" }}>
              <i style={{ width: 10, height: 10, borderRadius: 2, background: palette()[i % 10] }} />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{x.label}</span>
              <span className="num soft">{pct(x.pct)}</span><Money v={x.value} />
            </div>))}
          <p className="note">Top 5 posições: {pct(a.concentration.top5, 0)}; exposição a dólar: {pct(a.concentration.usd_exposure, 0)}.</p>
        </Panel>
      </div>

      <Panel title="Posições" flush>
        <div className="table-wrap" style={{ maxHeight: "none" }}>
          <table className="table">
            <thead><tr><th>Ativo</th><th>Classe</th><th>Instituição</th><th className="num">Saldo</th><th className="num">Peso</th>
              <th className="num">Custo</th><th className="num">Resultado</th><th className="num">% CDI</th><th>Taxa</th><th>Vencimento</th></tr></thead>
            <tbody>{d.positions.map((p: any) => (
              <tr key={p.id}>
                <td><div className="strong">{p.code && p.code.length <= 7 ? p.code : p.name}</div>
                  <div className="small muted" style={{ maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.code && p.code.length <= 7 ? p.name : p.issuer ?? ""}</div></td>
                <td><Chip>{p.asset_class}</Chip></td>
                <td className="soft">{p.institution}</td>
                <td><Money v={p.balance} /></td>
                <td className="num">{pct(p.weight)}</td>
                <td>{p.cost ? <Money v={p.cost} /> : <span className="muted small">não informado</span>}</td>
                <td>{p.profit !== null ? <><Money v={p.profit} tone={signTone(p.profit)} /><div className="num small soft">{pct(p.return_total)}</div></> : <span className="muted">—</span>}</td>
                <td className="num">{pct(p.pct_cdi, 0)}</td>
                <td className="soft small">{p.indexer === "CDI" && p.rate ? `${p.rate}% CDI` : p.indexer === "IPCA" && p.fixed_rate ? `IPCA + ${p.fixed_rate}%` : p.indexer ?? ""}</td>
                <td className="soft">{date(p.due_date)}</td>
              </tr>))}</tbody>
          </table>
        </div>
      </Panel>

      <div className="grid g3">
        <Panel title="Contribuição ao risco" hint="quanto cada posição explica da variância">
          {(r.data?.risk_contribution ?? []).slice(0, 8).map((x: any) => (
            <div key={x.id} className="bar-row" style={{ gridTemplateColumns: "minmax(0,1fr) 90px 56px" }}>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{x.name}</span>
              <div className="bar"><i style={{ width: `${Math.max(0, x.risk_contribution) * 100}%`, background: "var(--ochre)" }} /></div>
              <span className="num small">{pct(x.risk_contribution, 0)}</span>
            </div>))}
          <p className="note">Peso não é risco: compare com a coluna de peso das posições.</p>
        </Panel>
        <Panel title="Garantia do FGC" hint="por conglomerado emissor">
          {d.fgc.length === 0 ? <p className="muted">Sem títulos cobertos pelo FGC.</p> : d.fgc.map((g: any) => (
            <div key={g.issuer} style={{ marginBottom: 10 }}>
              <div className="small" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{g.issuer}</div>
              <div className="bar-row" style={{ gridTemplateColumns: "minmax(0,1fr) 120px" }}>
                <div className={`bar ${g.usage > 1 ? "debit" : ""}`}><i style={{ width: `${Math.min(100, g.usage * 100)}%` }} /></div>
                <span className="num small">{brl(g.value, 0)} de {brl(g.limit, 0)}</span></div></div>))}
          <p className="note">Limite de R$ 250 mil por CPF por conglomerado, valor bruto.</p>
        </Panel>
        <Panel title="Vencimentos">
          {d.ladder.length === 0 ? <p className="muted">Sem títulos com vencimento.</p> : (
            <Chart height={190} option={{ legend: false, tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v) },
              xAxis: { type: "category", data: d.ladder.map((x: any) => x.bucket) }, yAxis: { type: "value", show: false },
              series: [{ type: "bar", data: d.ladder.map((x: any) => Math.round(x.value)), itemStyle: { color: cssVar("--blue"), borderRadius: [2, 2, 0, 0] }, barMaxWidth: 34 }] }} />)}
        </Panel>
      </div>

      <div className="grid g2">
        <Panel title="Correlação entre classes" hint="retornos diários">
          {r.data?.correlation ? (
            <Chart height={260} option={{
              legend: false, tooltip: { formatter: (p: any) => `${r.data.correlation.labels[p.value[1]]} × ${r.data.correlation.labels[p.value[0]]}: ${p.value[2].toFixed(2)}` },
              grid: { left: 8, right: 8, top: 8, bottom: 8, containLabel: true },
              xAxis: { type: "category", data: r.data.correlation.labels, axisLabel: { interval: 0, rotate: 20 } },
              yAxis: { type: "category", data: r.data.correlation.labels },
              visualMap: { show: false, min: -1, max: 1, inRange: { color: [cssVar("--blue"), cssVar("--sheet"), cssVar("--debit")] } },
              series: [{ type: "heatmap", label: { show: true, formatter: (p: any) => p.value[2].toFixed(2), fontSize: 11 },
                data: r.data.correlation.matrix.flatMap((row: number[], i: number) => row.map((v, j) => [j, i, v])) }],
            }} />
          ) : <p className="muted">Precisa de pelo menos duas classes com histórico.</p>}
        </Panel>
        <Panel title="Retorno realizado" hint="a partir dos saldos diários coletados">
          {perf.twr !== undefined ? (
            <dl className="kv">
              <dt>Período</dt><dd>{date(perf.first)} a {date(perf.last)} ({perf.snapshots} dias com saldo)</dd>
              <dt>Retorno ponderado no tempo</dt><dd>{nd(perf.twr, 2, perf.twr_reason)}</dd>
              <dt>CDI no período</dt><dd>{pct(perf.cdi, 2)}; carteira = {nd(perf.pct_cdi, 0, perf.pct_cdi_reason, "do CDI")}</dd>
              <dt>IPCA no período</dt><dd>{pct(perf.ipca, 2)}</dd>
              <dt>TIR (fluxos)</dt><dd>{pct(perf.xirr, 2)} ao ano</dd>
            </dl>
          ) : <p className="muted">O retorno realizado começa a ser medido a partir do segundo dia de coleta. Enquanto isso, use o histórico com pesos atuais ao lado.</p>}
          <details style={{ marginTop: 10 }}><summary className="note">Premissas e proxies</summary>
            <ul className="assumptions">{(r.data?.assumptions ?? []).map((x: string, i: number) => <li key={i}>{x}</li>)}</ul></details>
        </Panel>
      </div>

      <Realized />

      {d.movements.length > 0 && <Panel title="Movimentações" flush>
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Data</th><th>Ativo</th><th>Tipo</th><th className="num">Quantidade</th><th className="num">Preço</th><th className="num">Valor</th></tr></thead>
          <tbody>{d.movements.slice(0, 60).map((m: any, i: number) => (
            <tr key={i}><td>{date(m.date)}</td><td>{m.code ?? m.name}</td><td>{m.type === "BUY" ? "Compra" : m.type === "SELL" ? "Venda" : m.type}</td>
              <td className="num">{m.quantity?.toLocaleString("pt-BR")}</td><td className="num">{m.value?.toLocaleString("pt-BR")}</td><td><Money v={m.amount} /></td></tr>))}</tbody>
        </table></div>
      </Panel>}
    </>
  );
}

/** Percentual ou "n/d" (com o motivo em tooltip) quando o backend não consegue calcular. */
function nd(v: number | null | undefined, digits: number, reason?: string | null, suffix = "") {
  if (v === null || v === undefined || !Number.isFinite(v)) {
    return <span title={reason || "Dados insuficientes para calcular."} style={{ cursor: "help" }}>n/d{reason ? " ⓘ" : ""}</span>;
  }
  return <>{pct(v, digits)}{suffix ? ` ${suffix}` : ""}</>;
}

function Realized() {
  const q = useQuery({ queryKey: ["portfolio-realized"], queryFn: () => api<any>("/api/portfolio/realized") });
  const d = q.data;
  if (!d) return <QueryState q={q} what="o resultado realizado" layout="panel">{() => null}</QueryState>;
  const rf = d.renda_fixa, rv = d.renda_variavel;
  const t = rf.totais;
  return (
    <>
      <Panel title="Resultado por título · renda fixa e Tesouro" hint={`${t.com_historico_completo} de ${t.titulos} com histórico completo`} flush>
        <div className="strip" style={{ borderBottom: "1px solid var(--rule)" }}>
          <div><div className="lbl">Resultado líquido</div><div className="val num" style={{ textAlign: "left" }}><Money v={t.resultado_liquido} tone={signTone(t.resultado_liquido)} /></div><div className="sub">títulos com histórico completo</div></div>
          <div><div className="lbl">Já realizado</div><div className="val num" style={{ textAlign: "left" }}><Money v={t.resultado_realizado} tone={signTone(t.resultado_realizado)} /></div><div className="sub">títulos encerrados</div></div>
          <div><div className="lbl">IR/IOF retido</div><div className="val num" style={{ textAlign: "left" }}>{brl(t.ir_iof_retido)}</div><div className="sub">nos resgates</div></div>
        </div>
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Título</th><th>Início</th><th>Situação</th><th className="num">Aplicado</th><th className="num">Resgatado líq.</th><th className="num">Saldo</th><th className="num">Resultado</th><th className="num">TIR a.a.</th><th className="num">% CDI</th></tr></thead>
          <tbody>{rf.titulos.map((x: any) => (
            <tr key={x.id}>
              <td className="desc"><div>{x.nome.replace(" - SOCIEDADE DE CREDITO, FINANCIAMENTO E INVESTIMENTO", "")}</div>
                <div className="s">{x.classe ?? ""}{x.vencimento ? ` · vence ${date(x.vencimento)}` : ""}</div></td>
              <td>{date(x.inicio)}</td>
              <td>{x.status === "ativo" ? <Chip tone="green">ativo</Chip> : <Chip>encerrado</Chip>}{!x.historico_completo && <div className="small muted">histórico parcial</div>}</td>
              <td className="num">{brl(x.aplicado)}</td><td className="num">{brl(x.resgatado_liquido)}</td><td className="num">{brl(x.saldo)}</td>
              <td>{x.resultado !== null ? <Money v={x.resultado} tone={signTone(x.resultado)} /> : <span className="muted">—</span>}</td>
              <td className="num">{x.tir_aa !== null ? pct(x.tir_aa, 1) : "—"}</td>
              <td className="num">{x.pct_cdi !== null ? pct(x.pct_cdi, 0) : "—"}</td>
            </tr>))}</tbody>
        </table></div>
        <p className="note" style={{ padding: "8px 18px 14px" }}>{rf.nota}</p>
      </Panel>

      <Panel title="Custo de renda variável" hint="preço médio só com evidência; nada é inventado" flush>
        <table className="table">
          <thead><tr><th>Ativo</th><th className="num">Quantidade</th><th className="num">Com custo</th><th className="num">Preço médio</th><th className="num">Preço atual</th><th className="num">Resultado (parte conhecida)</th><th>Acompanhado desde</th></tr></thead>
          <tbody>{rv.ativos.map((a: any) => (
            <tr key={a.ativo}><td className="strong">{a.ativo}</td><td className="num">{a.quantidade?.toLocaleString("pt-BR")}</td>
              <td className="num">{a.quantidade_com_custo.toLocaleString("pt-BR")}{a.custo_completo ? <Chip tone="green">completo</Chip> : null}</td>
              <td className="num">{a.preco_medio_conhecido ? brl(a.preco_medio_conhecido) : "—"}</td>
              <td className="num">{a.preco_atual ? brl(a.preco_atual) : "—"}</td>
              <td>{a.resultado_nao_realizado_conhecido !== null ? <Money v={a.resultado_nao_realizado_conhecido} tone={signTone(a.resultado_nao_realizado_conhecido)} /> : <span className="muted">—</span>}</td>
              <td>{date(a.acompanhado_desde)}</td></tr>))}</tbody>
        </table>
        <p className="note" style={{ padding: "8px 18px 14px" }}>{rv.nota}</p>
      </Panel>
    </>
  );
}
