import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api";
import { Chart, cssVar, kTick } from "../../components/Chart";
import { signTone } from "../../components/MoneyText";
import { QueryState } from "../../components/QueryState";
import { Term } from "../../components/Term";
import { Chip, Drawer, Money } from "../../components/ui";
import { brl, date, monthLabel, pct } from "../../format";
import { FlowChart } from "./Evolution";

/** Página de um ativo: valor, aportes × rendimento, retorno por período contra o CDI, movimentações, proventos e lotes. */
export function HoldingDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ["holding", id], queryFn: () => api<any>(`/api/portfolio/holding/${encodeURIComponent(id)}`) });
  const [view, setView] = useState<"valor" | "cotacao">("valor");
  const d = q.data;
  const title = d?.available ? <div><h3>{d.nome}</h3><div className="small soft">{[d.classe, d.instituicao, d.tipo].filter(Boolean).join(" · ")}</div></div> : "Ativo";
  return (
    <Drawer title={title} onClose={onClose}>
      {!d ? <QueryState q={q} what="o ativo" layout="panel">{() => null}</QueryState>
        : !d.available ? <p className="muted">{d.reason}</p> : <Body d={d} view={view} setView={setView} />}
    </Drawer>
  );
}

function Body({ d, view, setView }: { d: any; view: "valor" | "cotacao"; setView: (v: "valor" | "cotacao") => void }) {
  const p = d.posicao ?? {};
  const per = (k: string) => d.periodos.find((x: any) => x.key === k) ?? {};
  const all = per("inicio"), y12 = per("12m");
  const recon = d.curva.some((c: any) => c.reconstruido);
  const series = view === "cotacao" && d.cotacao.length ? d.cotacao.map((c: any) => [c.date, c.close]) : d.curva.map((c: any) => [c.date, c.valor]);
  return (
    <>
      <div className="mini-kpis">
        <div><span>Saldo</span><b><Money v={d.curva[d.curva.length - 1]?.valor} /></b>{d.encerrado && <Chip>encerrado</Chip>}</div>
        <div><span><Term k="twr">Retorno 12m</Term></span><b className={(y12.twr ?? 0) < 0 ? "neg" : ""}>{pct(y12.twr, 1)}</b>
          <small>{y12.pct_cdi != null ? `${pct(y12.pct_cdi, 0)} do CDI` : "—"}</small></div>
        <div><span>Ganho desde {date(all.inicio)}</span><b><Money v={all.ganho} tone={signTone(all.ganho)} /></b>
          <small>aportes {brl(all.aportes_liquidos, 0)}</small></div>
        {p.cost ? <div><span>Custo (Pluggy)</span><b><Money v={p.cost} /></b><small>resultado {pct(p.return_total, 1)}</small></div>
          : <div><span><Term k="tir">TIR</Term></span><b>{pct(all.tir_aa, 1)}</b><small>ao ano</small></div>}
      </div>

      <section>
        <div className="row-head"><h4>{view === "cotacao" ? "Cotação" : "Valor da posição"}</h4>
          {d.cotacao.length > 0 && <div className="segmented sm">
            <button className={view === "valor" ? "on" : ""} onClick={() => setView("valor")}>Valor</button>
            <button className={view === "cotacao" ? "on" : ""} onClick={() => setView("cotacao")}>Cotação</button></div>}</div>
        <Chart height={200} option={{
          legend: false, grid: { top: 12 },
          tooltip: { trigger: "axis", valueFormatter: (v: number) => (view === "cotacao" ? brl(v) : brl(v, 0)) },
          xAxis: { type: "time", axisLabel: { formatter: (v: number) => { const d = new Date(v); return monthLabel(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`); }, hideOverlap: true } },
          yAxis: { type: "value", scale: true, axisLabel: { formatter: kTick } },
          series: [{ type: "line", name: view === "cotacao" ? "Cotação" : "Valor", symbol: "none", data: series,
            lineStyle: { width: 2, color: cssVar("--cat-1") }, areaStyle: view === "valor" ? { color: cssVar("--seq-1"), opacity: .5 } : undefined }],
        }} />
        {recon && view === "valor" && <p className="note">Antes de {date(d.curva.find((c: any) => !c.reconstruido)?.date)} o valor é reconstruído pelas movimentações e pelo indexador.</p>}
      </section>

      {d.aportes.length > 1 && d.aportes.some((r: any) => Math.abs(r.aporte_mes) >= 1 || Math.abs(r.rendimento_mes) >= 1) && <section><h4>Aportes e rendimento por mês</h4><FlowChart rows={d.aportes} height={190} /></section>}

      <section>
        <h4>Retorno por período</h4>
        <table className="table compact"><thead><tr><th>Período</th><th className="num">Retorno</th><th className="num">CDI</th><th className="num">% CDI</th><th className="num">Ganho</th></tr></thead>
          <tbody>{d.periodos.map((x: any) => (
            <tr key={x.key}><td>{x.label}{x.inicio_efetivo_posterior && <span className="small muted"> · desde {date(x.inicio)}</span>}</td>
              <td className={`num ${(x.twr ?? 0) < 0 ? "neg" : ""}`}>{x.twr != null ? pct(x.twr, 2) : <span className="muted" title={x.motivo}>—</span>}</td>
              <td className="num soft">{pct(x.cdi, 2)}</td><td className="num">{x.pct_cdi != null ? pct(x.pct_cdi, 0) : "—"}</td>
              <td><Money v={x.ganho} digits={0} tone={signTone(x.ganho)} /></td></tr>))}</tbody></table>
      </section>

      <dl className="kv">
        {p.rate != null && <><dt>Taxa</dt><dd>{p.indexer === "CDI" ? `${p.rate}% do CDI` : p.indexer === "IPCA" && p.fixed_rate ? `IPCA + ${p.fixed_rate}%` : `${p.rate}`}</dd></>}
        {p.due_date && <><dt>Vencimento</dt><dd>{date(p.due_date)}</dd></>}
        {p.issuer && <><dt>Emissor</dt><dd>{p.issuer}</dd></>}
        {p.quantity != null && <><dt>Quantidade</dt><dd className="num" style={{ textAlign: "left" }}>{String(p.quantity).replace(".", ",")}</dd></>}
        {d.lotes?.preco_medio_conhecido != null && <><dt>Preço médio</dt><dd>{brl(d.lotes.preco_medio_conhecido)}
          {!d.lotes.custo_completo && <span className="small muted"> (só de {String(d.lotes.quantidade_com_custo).replace(".", ",")} cotas com custo conhecido)</span>}</dd></>}
        {d.lotes?.resultado_realizado ? <><dt>Resultado realizado</dt><dd><Money v={d.lotes.resultado_realizado} tone={signTone(d.lotes.resultado_realizado)} /></dd></> : null}
      </dl>

      {d.proventos.length > 0 && <section><h4>Proventos recebidos</h4>
        {d.proventos.slice(0, 12).map((r: any, i: number) => (
          <div key={i} className="list-row"><div className="grow"><div className="t">{r.tipo ?? "Provento"}</div><div className="s">{date(r.data)}{r.quantidade ? ` · ${r.quantidade} cotas` : ""}</div></div>
            <Money v={r.valor} /></div>))}
        <p className="note">Total: {brl(d.proventos.reduce((a: number, r: any) => a + r.valor, 0))}.</p></section>}

      <section><h4>Movimentações</h4>
        {d.movimentacoes.length === 0 ? <p className="muted small">Nenhuma movimentação na janela.</p> : d.movimentacoes.slice(0, 30).map((m: any, i: number) => (
          <div key={i} className="list-row"><div className="grow"><div className="t">{m.valor > 0 ? "Aplicação" : "Resgate"}</div>
            <div className="s">{date(m.data)}{m.quantidade ? ` · ${m.quantidade > 0 ? "+" : ""}${String(m.quantidade).replace(".", ",")} cotas` : ""}{m.origem !== "pluggy" ? ` · ${m.origem}` : ""}</div></div>
            <Money v={m.valor} /></div>))}
        {d.fluxos_inferidos.length > 0 && <details><summary className="note">{d.fluxos_inferidos.length} fluxos inferidos (sem movimentação correspondente)</summary>
          {d.fluxos_inferidos.map((f: any, i: number) => <div key={i} className="small soft">{date(f.data)}: {brl(f.valor)} · {f.motivo}</div>)}</details>}
      </section>
      {(d.notas.length > 0 || d.premissas.length > 0) && <details><summary className="note">Notas e premissas</summary>
        <ul className="assumptions">{[...d.notas, ...d.premissas].map((n: string, i: number) => <li key={i}>{n}</li>)}</ul></details>}
    </>
  );
}
