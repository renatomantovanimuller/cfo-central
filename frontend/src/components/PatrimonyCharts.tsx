import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { api } from "../api";
import { Chart, cssVar, kTick, palette } from "./Chart";
import { MoneyInput } from "./MoneyInput";
import { Chip, Empty, Panel } from "./ui";
import { QueryState } from "./QueryState";
import { brl, monthLabel, parseBRL, pct } from "../format";

const PARTS: [string, string, string][] = [
  ["poupanca", "Poupança do mês", "--ledger"], ["extraordinarios", "Extraordinários", "--slate"],
  ["valorizacao", "Valorização dos investimentos", "--ochre"], ["manuais", "Itens manuais", "--ink-3"],
  ["nao_explicado", "Não explicado", "--debit"],
];

/** Eixo começa perto do menor nível da ponte: a partir do zero as variações do mês (pequenas perto do total) somem. */
function floorAxis(steps: [string, number, boolean][]) {
  let acc = 0, lo = Infinity;
  for (const [, v, total] of steps) { acc = total ? v : acc + v; lo = Math.min(lo, acc); }
  if (!isFinite(lo) || lo <= 0) return undefined;
  const mag = 10 ** Math.max(0, Math.floor(Math.log10(lo)) - 1);
  return Math.floor((lo * 0.97) / mag) * mag;
}

/** Ponte do patrimônio: de onde veio a variação de cada mês. */
export function PatrimonyBridge() {
  const q = useQuery({ queryKey: ["patrimony-bridge"], queryFn: () => api<any>("/api/patrimony/bridge?months=12") });
  const [sel, setSel] = useState<string | null>(null);
  const d = q.data;
  if (!d) return <QueryState q={q} what="a ponte do patrimônio" layout="panel">{() => null}</QueryState>;
  if (!d.meses.length) return null;
  const last = d.meses.find((m: any) => m.mes === sel) ?? [...d.meses].reverse().find((m: any) => !m.parcial) ?? d.meses[d.meses.length - 1];
  const steps = [["Início", last.inicio, true], ...PARTS.map(([k, l]) => [l, last[k] ?? 0, false]), ["Fim", last.fim, true]] as [string, number, boolean][];
  let acc = 0;
  const base: (number | string)[] = [], up: number[] = [], down: number[] = [];
  for (const [, v, total] of steps) {
    if (total) { base.push(0); up.push(Math.round(v)); down.push(0); acc = v; continue; }
    const next = acc + v;
    base.push(Math.round(Math.min(acc, next))); up.push(v >= 0 ? Math.round(v) : 0); down.push(v < 0 ? Math.round(-v) : 0); acc = next;
  }
  return (
    <Panel title="De onde veio a variação do patrimônio" hint={d.nota}
      tools={<select className="select" value={last.mes} onChange={(e) => setSel(e.target.value)}>
        {d.meses.map((m: any) => <option key={m.mes} value={m.mes}>{monthLabel(m.mes)}{m.parcial ? " (parcial)" : ""}</option>)}</select>}>
      <div className="grid g2">
        <Chart height={260} option={{
          tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: (p: any[]) => {
            const i = p[0].dataIndex; return `${steps[i][0]}: ${brl(steps[i][1], 0)}`; } },
          xAxis: { type: "category", data: steps.map((s) => s[0]), axisLabel: { interval: 0, rotate: 25, fontSize: 10 } },
          yAxis: { type: "value", axisLabel: { formatter: kTick }, min: floorAxis(steps) },
          series: [
            { type: "bar", stack: "w", data: base, itemStyle: { color: "transparent" }, emphasis: { disabled: true } },
            { type: "bar", stack: "w", data: up, itemStyle: { color: cssVar("--ledger") } },
            { type: "bar", stack: "w", data: down, itemStyle: { color: cssVar("--debit") } },
          ],
        }} />
        <div>
          <dl className="kv">
            <dt>Patrimônio no início</dt><dd className="num">{brl(last.inicio, 0)}</dd>
            {PARTS.map(([k, l]) => <Fragment key={k}><dt>{l}</dt><dd className={`num ${(last[k] ?? 0) < 0 ? "neg" : ""}`}>{last[k] === null ? "sem dado" : brl(last[k], 0)}</dd></Fragment>)}
            <dt className="strong">Patrimônio no fim</dt><dd className="num strong">{brl(last.fim, 0)}</dd>
          </dl>
          {last.estimado && <Chip tone="ochre">mês com valores estimados</Chip>}
          {Math.abs(last.nao_explicado) > Math.max(500, Math.abs(last.fim - last.inicio) * 0.3) &&
            <p className="note">"Não explicado" alto: confira em Saúde dos dados se falta alguma conta conectada ou lançamento.</p>}
        </div>
      </div>
    </Panel>
  );
}

/** Investimentos por classe ou instituição, fim de cada mês. */
export function PatrimonyEvolution() {
  const q = useQuery({ queryKey: ["patrimony-evolution"], queryFn: () => api<any>("/api/patrimony/evolution?months=12") });
  const [by, setBy] = useState<"por_classe" | "por_instituicao">("por_classe");
  const d = q.data;
  if (!d) return <QueryState q={q} what="a evolução" layout="panel">{() => null}</QueryState>;
  const series = Object.entries(d[by] as Record<string, (number | null)[]>);
  return (
    <Panel title="Evolução dos investimentos" hint={d.nota}
      tools={<div className="segmented"><button className={by === "por_classe" ? "on" : ""} onClick={() => setBy("por_classe")}>Classe</button>
        <button className={by === "por_instituicao" ? "on" : ""} onClick={() => setBy("por_instituicao")}>Instituição</button></div>}>
      {d.meses_com_dado < 2 ? <Empty title="Ainda pouco histórico">A evolução aparece conforme o app sincroniza mês a mês ({d.meses_com_dado} mês com dado).</Empty> :
        <Chart height={260} option={{
          tooltip: { trigger: "axis", valueFormatter: (v: number) => (v == null ? "—" : brl(v, 0)) },
          xAxis: { type: "category", data: d.meses.map(monthLabel) }, yAxis: { type: "value", axisLabel: { formatter: kTick } },
          series: series.map(([k, v], i) => ({ name: k, type: "line", stack: "e", areaStyle: { opacity: .55 }, symbol: "none",
            data: v, connectNulls: false, lineStyle: { width: 1 }, itemStyle: { color: palette()[i % 10] } })),
        }} />}
    </Panel>
  );
}

/** Projeção do patrimônio financeiro com faixas de cenário e "quando chego a R$ X". */
export function PatrimonyProjection() {
  const [alvo, setAlvo] = useState("");
  const [real, setReal] = useState(true);
  const v = parseBRL(alvo);
  const q = useQuery({ queryKey: ["patrimony-projection", v], queryFn: () => api<any>(`/api/patrimony/projection?years=10${v ? `&alvo=${v}` : ""}`) });
  const d = q.data;
  if (!d) return <QueryState q={q} what="a projeção" layout="panel">{() => null}</QueryState>;
  const t = d.trajetoria;
  const k = (x: string) => (real ? `${x}_real` : x);
  return (
    <Panel title="Projeção do patrimônio" hint={d.nota}
      tools={<div className="segmented"><button className={real ? "on" : ""} onClick={() => setReal(true)} title="Valores em poder de compra de hoje">Real</button>
        <button className={!real ? "on" : ""} onClick={() => setReal(false)}>Nominal</button></div>}>
      <Chart height={220} option={{
        tooltip: { trigger: "axis", valueFormatter: (x: number) => brl(x, 0) },
        xAxis: { type: "category", data: t.map((x: any) => `${Math.floor(x.mes / 12)}a`), axisLabel: { interval: (i: number) => i === 0 || Math.floor(t[i].mes / 12) !== Math.floor(t[i - 1].mes / 12) } },
        yAxis: { type: "value", axisLabel: { formatter: kTick } },
        series: [
          { name: "Pessimista (p10)", type: "line", symbol: "none", data: t.map((x: any) => Math.round(x[k("p10")])), lineStyle: { width: 1, color: cssVar("--slate") } },
          { name: "Mediano", type: "line", symbol: "none", data: t.map((x: any) => Math.round(x[k("p50")])), lineStyle: { width: 2.4, color: cssVar("--ledger") } },
          { name: "Otimista (p90)", type: "line", symbol: "none", data: t.map((x: any) => Math.round(x[k("p90")])), lineStyle: { width: 1, color: cssVar("--slate") } },
          ...(d.alvo ? [{ name: "Alvo", type: "line", symbol: "none", data: t.map(() => d.alvo), lineStyle: { type: "dashed", color: cssVar("--ochre") } }] : []),
        ],
      }} />
      <div className="toolbar">{d.marcos.map((m: any) => <span key={m.anos} className="small"><b>{m.anos} {m.anos === 1 ? "ano" : "anos"}:</b> {brl(real ? m.p50_real : m.p50, 0)}</span>)}</div>
      <div className="toolbar" style={{ marginTop: 6 }}>
        <span className="small">Quando chego a</span>
        <MoneyInput width={140} allowNegative={false} placeholder="R$ 1.000.000" ariaLabel="Valor alvo da projeção" value={alvo} onChange={setAlvo} />
        {d.alvo && <span className="small">{d.meses_ate_alvo_p50 ? `no cenário mediano, em ${(d.meses_ate_alvo_p50 / 12).toFixed(1).replace(".", ",")} anos` : "não chega em 10 anos no cenário mediano"}
          {" · "}{pct(d.probabilidade_alvo, 0)} de chance em 10 anos</span>}
      </div>
      <p className="note">Início {brl(d.inicio, 0)} (caixa + investimentos), aporte de {brl(d.aporte_mensal, 0)}/mês, retorno {pct(d.retorno_aa, 1)} a.a. e oscilação {pct(d.vol_aa, 1)} ({d.fonte_risco}); inflação {pct(d.inflacao, 0)} a.a. para "reais de hoje". O alvo é nominal.</p>
    </Panel>
  );
}
