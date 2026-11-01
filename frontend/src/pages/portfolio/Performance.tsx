import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { api } from "../../api";
import { Chart, cssVar, kTick, palette } from "../../components/Chart";
import { signTone } from "../../components/MoneyText";
import { QueryState } from "../../components/QueryState";
import { Term } from "../../components/Term";
import { Chip, Empty, Money, Panel } from "../../components/ui";
import { brl, date, pct } from "../../format";

const GROUPS: [string, string][] = [["por_instituicao", "Instituição"], ["por_classe", "Classe"], ["por_ativo", "Ativo"]];

/** Percentual com "n/d" e motivo quando o backend não consegue calcular. */
function P({ v, digits = 1, why }: { v: number | null | undefined; digits?: number; why?: string | null }) {
  if (v === null || v === undefined || !Number.isFinite(v)) return <span className="muted" title={why ?? "Dados insuficientes"}>—</span>;
  return <span className={v < 0 ? "neg" : ""}>{pct(v, digits)}</span>;
}

export default function Performance() {
  const [period, setPeriod] = useState("12m");
  const [group, setGroup] = useState("por_classe");
  const q = useQuery({ queryKey: ["portfolio-performance"], queryFn: () => api<any>("/api/portfolio/performance") });
  const d = q.data;
  if (!d) return <QueryState q={q} what="a performance da carteira" layout="panel">{() => null}</QueryState>;
  if (!d.available) return <Panel><Empty title="Sem histórico para medir">{d.reason}</Empty></Panel>;
  const per = d.periodos.find((p: any) => p.key === period);
  const t = d.total.periodos[period] ?? {};
  const ref = d.referencias[period] ?? {};
  const rows: any[] = d[group];
  const refKeys = Object.keys(ref);
  const recon = d.curva.filter((c: any) => c.reconstruido);
  const seriesKeys = Object.keys(d.curva[0] ?? {}).filter((k) => !["date", "reconstruido"].includes(k));
  const classes = Array.from(new Set(d.evolucao.flatMap((e: any) => Object.keys(e).filter((k) => !["date", "reconstruido"].includes(k))))) as string[];

  return (
    <>
      <div className="toolbar" style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
        <div className="segmented" role="tablist" aria-label="Período">
          {d.periodos.map((p: any) => <button key={p.key} role="tab" aria-selected={period === p.key} className={period === p.key ? "on" : ""}
            onClick={() => setPeriod(p.key)}>{p.label}</button>)}</div>
        <span className="small soft">dados até {date(d.fim)}{d.snapshots_desde ? `; saldos coletados desde ${date(d.snapshots_desde)} (antes disso, reconstruído)` : ""}</span>
      </div>

      <section className="panel strip">
        <div><div className="lbl"><Term k="twr">Retorno no período</Term></div><div className="val"><P v={t.twr} digits={2} why={t.motivo} /></div>
          <div className="sub">{t.inicio_efetivo_posterior ? `desde ${date(t.inicio)}` : `desde ${date(per?.inicio)}`}{per?.janela_menor ? " (início do histórico)" : ""}</div></div>
        <div><div className="lbl"><Term k="pct_cdi">Contra o CDI</Term></div><div className="val">{t.pct_cdi !== null && t.pct_cdi !== undefined ? `${pct(t.pct_cdi, 0)}` : "—"}</div>
          <div className="sub">CDI {pct(ref.CDI, 2)}; IPCA {pct(ref.IPCA, 2)}</div></div>
        <div><div className="lbl">Ganho</div><div className="val num" style={{ textAlign: "left" }}><Money v={t.ganho} tone={signTone(t.ganho)} /></div>
          <div className="sub">bruto de IR, já sem os aportes</div></div>
        <div><div className="lbl"><Term k="aporte">Aportes líquidos</Term></div><div className="val num" style={{ textAlign: "left" }}><Money v={t.aportes_liquidos} /></div>
          <div className="sub">de {brl(t.valor_inicial, 0)} para {brl(t.valor_final, 0)}</div></div>
        <div><div className="lbl"><Term k="tir">TIR</Term></div><div className="val"><P v={t.tir_aa} digits={1} /></div><div className="sub">ao ano, pelos seus fluxos</div></div>
      </section>

      <div className="grid g-wide">
        <Panel title="Carteira contra referências" hint="retorno acumulado desde o início do histórico">
          <Chart height={300} option={{
            tooltip: { trigger: "axis", valueFormatter: (v: number) => (v === null || v === undefined ? "—" : `${v.toFixed(1).replace(".", ",")}%`) },
            xAxis: { type: "category", data: d.curva.map((c: any) => date(c.date)) },
            yAxis: { type: "value", axisLabel: { formatter: (v: number) => `${v}%` } },
            series: seriesKeys.map((k, i) => ({
              name: k, type: "line", symbol: "none", connectNulls: false, data: d.curva.map((c: any) => c[k] ?? null),
              lineStyle: { width: k === "Carteira" ? 2.6 : 1.4, type: k === "CDI" || k === "IPCA" ? "dashed" : "solid" },
              ...(i === 0 && recon.length ? { markArea: { silent: true, itemStyle: { color: cssVar("--rule"), opacity: 0.35 },
                data: [[{ xAxis: date(recon[0].date), name: "reconstruído" }, { xAxis: date(recon[recon.length - 1].date) }]] } } : {}),
            })),
          }} />
          {recon.length > 0 && <p className="note">Área sombreada: valores reconstruídos a partir das movimentações e cotações (antes do 1º saldo coletado).</p>}
        </Panel>
        <Panel title="Referências no período" hint={per?.label}>
          <dl className="kv">
            <dt>Carteira</dt><dd className="strong"><P v={t.twr} digits={2} /></dd>
            {refKeys.map((k) => <Fragment key={k}><dt>{k}</dt><dd><P v={ref[k]} digits={2} why="cotação sem qualidade no período" /></dd></Fragment>)}
          </dl>
          <p className="note">Ibovespa com proventos usa o BOVA11 (cotação ajustada). Referência com defeito na fonte fica em branco.</p>
        </Panel>
      </div>

      <Panel title="Por grupo" tools={<div className="segmented">{GROUPS.map(([k, l]) =>
        <button key={k} className={group === k ? "on" : ""} onClick={() => setGroup(k)}>{l}</button>)}</div>} flush>
        <div className="table-wrap" style={{ maxHeight: "none" }}><table className="table">
          <thead><tr><th>{GROUPS.find(([k]) => k === group)?.[1]}</th><th className="num">Valor hoje</th><th className="num hide-sm">Peso</th>
            <th className="num">Retorno</th><th className="num"><Term k="pct_cdi">% CDI</Term></th><th className="num">Ganho</th>
            <th className="num hide-sm">Aportes líq.</th><th className="num hide-sm"><Term k="tir">TIR a.a.</Term></th></tr></thead>
          <tbody>{rows.map((r: any, i: number) => {
            const x = r.periodos[period] ?? {};
            return (
              <tr key={`${r.id ?? r.nome}-${i}`}>
                <td><div className="strong">{r.nome}</div>
                  <div className="small muted">{[r.instituicao, group === "por_ativo" ? r.classe : null].filter(Boolean).join(" · ")}
                    {x.inicio_efetivo_posterior ? ` desde ${date(x.inicio)}` : ""}
                    {x.dias && x.dias_com_posicao !== undefined && x.dias_com_posicao < x.dias * 0.9 && x.dias_com_posicao > 0 ? ` · investido ${x.dias_com_posicao} de ${x.dias} dias` : ""}</div>
                  {x.reconstruido && <Chip>reconstruído</Chip>} {r.ativo === false && <Chip>encerrado</Chip>}
                  {r.notas?.length ? <span className="small muted" title={r.notas.join("\n")} style={{ cursor: "help" }}> ⓘ</span> : null}</td>
                <td><Money v={r.valor} /></td>
                <td className="num hide-sm">{pct(r.peso)}</td>
                <td className="num"><P v={x.twr} digits={2} why={x.motivo} /></td>
                <td className="num">{x.pct_cdi !== null && x.pct_cdi !== undefined ? pct(x.pct_cdi, 0) : "—"}</td>
                <td>{x.ganho !== undefined && x.ganho !== null ? <Money v={x.ganho} tone={signTone(x.ganho)} /> : "—"}</td>
                <td className="hide-sm">{x.aportes_liquidos !== undefined ? <Money v={x.aportes_liquidos} /> : "—"}</td>
                <td className="num hide-sm"><P v={x.tir_aa} /></td>
              </tr>);
          })}</tbody>
        </table></div>
        <p className="note" style={{ padding: "8px 18px 14px" }}>Retorno ponderado no tempo, bruto de IR: aportes e resgates não contam como ganho.
          % do CDI só aparece em períodos de pelo menos 1 mês.</p>
      </Panel>

      <Panel title="Evolução do patrimônio investido" hint="fim de cada mês, por classe">
        <Chart height={260} option={{
          tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v, 0) },
          xAxis: { type: "category", data: d.evolucao.map((e: any) => date(e.date)) },
          yAxis: { type: "value", axisLabel: { formatter: kTick } },
          series: classes.map((c, i) => ({ name: c, type: "bar", stack: "v", data: d.evolucao.map((e: any) => e[c] ?? 0),
            itemStyle: { color: palette()[i % 10], opacity: 1 }, barMaxWidth: 28 })),
        }} />
        <p className="note">Meses antes de {date(d.snapshots_desde)} são reconstruídos.</p>
      </Panel>

      {(d.fluxos_inferidos.length > 0 || d.notas.length > 0) && <Panel title="O que foi inferido" hint="transparência do cálculo">
        {d.fluxos_inferidos.length > 0 && <div className="table-wrap"><table className="table">
          <thead><tr><th>Data</th><th>Ativo</th><th className="num">Valor</th><th>Por quê</th></tr></thead>
          <tbody>{d.fluxos_inferidos.map((f: any, i: number) => <tr key={i}><td>{date(f.data)}</td><td>{f.ativo}</td><td><Money v={f.valor} /></td><td className="small soft">{f.motivo}</td></tr>)}</tbody>
        </table></div>}
        {d.notas.length > 0 && <ul className="assumptions">{d.notas.map((n: string, i: number) => <li key={i}>{n}</li>)}</ul>}
      </Panel>}
      <details style={{ margin: "4px 2px 18px" }}><summary className="note">Premissas</summary>
        <ul className="assumptions">{d.premissas.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul></details>
    </>
  );
}
