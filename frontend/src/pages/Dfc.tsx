import { QueryState } from "../components/QueryState";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { Chart, cssVar } from "../components/Chart";
import { useMonth } from "../components/Layout";
import { Statement, StmtRow } from "../components/Statement";
import { Empty, Panel } from "../components/ui";
import { brl, monthLong } from "../format";

function nodeColor(name: string, links: any[]) {
  if (name === "Entradas do mês") return cssVar("--ink");
  if (name === "Sobra em caixa") return cssVar("--ledger");
  if (name.startsWith("Investimentos")) return cssVar("--ochre");
  if (links.some((l) => l.target === "Entradas do mês" && l.source === name)) return cssVar("--ledger");
  return cssVar("--debit");
}

export default function Dfc() {
  const { month } = useMonth();
  const [n, setN] = useState(12);
  const q = useQuery({ queryKey: ["dfc", month, n], queryFn: () => api<any>(`/api/dfc?end=${month}&months=${n}`) });
  const sk = useQuery({ queryKey: ["sankey", month], queryFn: () => api<any>(`/api/sankey?month=${month}`) });
  const d = q.data;
  if (!d) return <QueryState q={q} what="o fluxo de caixa">{() => null}</QueryState>;
  const months: string[] = d.months;
  const rows: StmtRow[] = [{ key: "open", label: "Saldo inicial de caixa", values: d.opening_cash, italic: true }];
  for (const s of d.sections) {
    rows.push({ key: s.key, label: s.label, values: s.values, total: s.total, subtotal: true,
      children: s.lines.map((l: any) => ({ key: l.key, label: l.label, values: l.values, total: l.total })) });
  }
  rows.push({ key: "net", label: "Variação de caixa", values: d.net_change, subtotal: true,
    total: Object.values(d.net_change as Record<string, number>).reduce((a, b) => a + b, 0) });
  rows.push({ key: "close", label: "Saldo final de caixa", values: d.closing_cash, subtotal: true, final: true });
  rows.push({ key: "check", label: "Diferença vs saldo coletado", values: d.check_vs_reported, italic: true });
  return (
    <>
      <Panel title="Fluxo do mês" hint={`${monthLong(month)}, por competência: de onde veio e para onde foi`}>
        {sk.data && sk.data.links.length > 0 ? (
          <Chart height={360} option={{
            legend: false, tooltip: { trigger: "item", valueFormatter: (v: number) => brl(v) },
            series: [{
              type: "sankey", data: sk.data.nodes.map((n: any) => ({ ...n, itemStyle: { color: nodeColor(n.name, sk.data.links) } })), links: sk.data.links, nodeAlign: "justify", nodeGap: 10, nodeWidth: 12,
              emphasis: { focus: "adjacency" }, lineStyle: { color: "gradient", opacity: 0.35, curveness: 0.5 },
              label: { color: cssVar("--ink"), fontFamily: "Archivo", fontSize: 12, formatter: (p: any) => `${p.name}  ${brl(p.value, 0)}` },
              itemStyle: { borderWidth: 0 },
            }],
          }} />
        ) : sk.data ? <Empty title="Sem movimentação neste mês" /> : <QueryState q={sk} what="o fluxo do mês" layout="panel">{() => null}</QueryState>}
      </Panel>
      <Panel title="Demonstração do fluxo de caixa" hint="método direto, só contas correntes" flush
        tools={<div className="segmented">{[6, 12, 24].map((x) => <button key={x} className={n === x ? "on" : ""} onClick={() => setN(x)}>{x} meses</button>)}</div>}>
        <Statement months={months} rows={rows} />
        <ul className="assumptions" style={{ padding: "8px 18px 14px 36px" }}>{d.notes.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
      </Panel>
    </>
  );
}
