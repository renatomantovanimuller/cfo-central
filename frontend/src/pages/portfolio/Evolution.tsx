import { useState } from "react";
import { Chart, cssVar, kTick } from "../../components/Chart";
import { Money, Panel } from "../../components/ui";
import { signTone } from "../../components/MoneyText";
import { Term } from "../../components/Term";
import { brl, date, monthLabel } from "../../format";

type Row = { date: string; valor: number; partida: number; aportes_acumulados: number; rendimento_acumulado: number;
  aporte_mes: number; rendimento_mes: number; parcial: boolean; reconstruido: boolean };

const mLabel = (r: Row) => `${monthLabel(r.date.slice(0, 7))}${r.parcial ? " (parcial)" : ""}`;

/** Barras do mês: quanto entrou de aporte e quanto a carteira rendeu (pode ser negativo). Mesmo eixo, mesma unidade. */
export function FlowChart({ rows, height = 240 }: { rows: Row[]; height?: number }) {
  return (
    <Chart height={height} option={{
      tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v, 0) },
      xAxis: { type: "category", data: rows.map(mLabel) },
      yAxis: { type: "value", axisLabel: { formatter: kTick } },
      series: [
        { name: "Aporte líquido", type: "bar", barMaxWidth: 22, barGap: "12%", data: rows.map((r) => Math.round(r.aporte_mes)),
          itemStyle: { color: cssVar("--cat-1"), borderRadius: 3 } },
        { name: "Rendimento", type: "bar", barMaxWidth: 22, data: rows.map((r) => Math.round(r.rendimento_mes)),
          itemStyle: { color: cssVar("--cat-3"), borderRadius: 3 } },
      ],
    }} />
  );
}

/** Patrimônio investido no tempo, separado em saldo de partida, aportes acumulados e rendimento acumulado. */
export function Evolution({ rows }: { rows: Row[] }) {
  const [mode, setMode] = useState<"acum" | "mes">("acum");
  if (!rows?.length) return null;
  const last = rows[rows.length - 1];
  const recon = rows.filter((r) => r.reconstruido);
  return (
    <Panel title="Evolução: aportes e rendimento" hint={`desde ${date(rows[0].date)}`}
      tools={<div className="segmented sm">
        <button className={mode === "acum" ? "on" : ""} onClick={() => setMode("acum")}>Acumulado</button>
        <button className={mode === "mes" ? "on" : ""} onClick={() => setMode("mes")}>Mês a mês</button></div>}>
      <div className="evo-sum">
        <div><span>Hoje</span><b><Money v={last.valor} digits={0} /></b></div>
        <div><span>Saldo de partida</span><b><Money v={last.partida} digits={0} /></b></div>
        <div><span><Term k="aporte">Aportes líquidos</Term></span><b><Money v={last.aportes_acumulados} digits={0} /></b></div>
        <div><span>Rendimento</span><b><Money v={last.rendimento_acumulado} digits={0} tone={signTone(last.rendimento_acumulado)} /></b></div>
      </div>
      {mode === "mes" ? <FlowChart rows={rows} /> : (
        <Chart height={260} option={{
          tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v, 0) },
          xAxis: { type: "category", data: rows.map(mLabel), boundaryGap: false },
          yAxis: { type: "value", axisLabel: { formatter: kTick } },
          series: [
            { name: "Aportes líquidos acumulados", key: "aportes_acumulados", color: "--cat-1" },
            { name: "Rendimento acumulado", key: "rendimento_acumulado", color: "--cat-3" },
          ].map((s) => ({
            name: s.name, type: "line", stack: "v", symbol: "none", data: rows.map((r: any) => Math.round(r[s.key])),
            lineStyle: { width: 2, color: cssVar(s.color) }, itemStyle: { color: cssVar(s.color) },
            areaStyle: { color: cssVar(s.color), opacity: 0.35 },
          })),
        }} />
      )}
      <p className="note">{mode === "acum" ? "O gráfico mostra só o que mudou desde o início: quanto você colocou e quanto rendeu. " : ""}Rendimento = valor de hoje − saldo de partida − aportes líquidos. Bruto de IR.
        {recon.length > 0 && ` Até ${monthLabel(recon[recon.length - 1].date.slice(0, 7))} os valores são reconstruídos.`}</p>
    </Panel>
  );
}
