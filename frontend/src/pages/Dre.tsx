import { QueryState } from "../components/QueryState";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Chart, cssVar, kTick } from "../components/Chart";
import { useMonth } from "../components/Layout";
import { Statement, StmtRow } from "../components/Statement";
import { Panel } from "../components/ui";
import { ProvisionalBanner } from "../components/Onboarding";
import { Term } from "../components/Term";
import { brl, isPartialMonth, monthAxisLabel, PARTIAL_OPACITY } from "../format";

export default function Dre() {
  const { month } = useMonth();
  const nav = useNavigate();
  const [n, setN] = useState(12);
  const [av, setAv] = useState(false);
  const q = useQuery({ queryKey: ["dre", month, n], queryFn: () => api<any>(`/api/dre?end=${month}&months=${n}`) });
  const d = q.data;
  if (!d) return <QueryState q={q} what="a DRE">{() => null}</QueryState>;
  const months: string[] = d.months;
  const mapRow = (r: any): StmtRow => ({
    key: r.key ?? r.id, id: r.id, label: r.label, values: r.values, total: r.total, subtotal: r.subtotal,
    final: r.key === "resultado_liquido" || r.key === "resultado_total", av: r.av, children: (r.children ?? []).map(mapRow),
  });
  const rows: StmtRow[] = d.rows.map(mapRow);
  rows.push({ key: "savings", label: "Taxa de poupança", values: d.savings_rate, percent: true, italic: true });
  if (d.valuation) {
    rows.push({ key: "valuation", label: "Valorização da carteira (estimada)", values: d.valuation.values, italic: true,
      total: Object.values(d.valuation.values as Record<string, number | null>).reduce<number>((a, b) => a + (b ?? 0), 0) });
    rows.push({ key: "economic", label: "Resultado econômico (com valorização)", values: d.economic_result, subtotal: true, final: true,
      total: Object.values(d.economic_result as Record<string, number | null>).reduce<number>((a, b) => a + (b ?? 0), 0) });
  }
  const res = d.rows.find((r: any) => r.key === "resultado_liquido");
  const rec = d.rows.find((r: any) => r.key === "receita_liquida");
  const onCell = (r: StmtRow, m: string | null) => {
    if (!m || !r.id) return;
    nav(`/razao?category=${r.id}&month=${m}`);
  };
  return (
    <>
      <ProvisionalBanner />
      <Panel title="Resultado mês a mês" hint={<>quanto sobrou de cada mês (sem herança/doações), <Term k="competencia">por competência</Term></>}>
        <Chart height={220} option={{
          tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v) },
          xAxis: { type: "category", data: months.map((m) => monthAxisLabel(m)) },
          yAxis: { type: "value", axisLabel: { formatter: kTick } },
          series: [
            { name: "Receita líquida", type: "line", data: months.map((m) => Math.round(rec.values[m])), symbol: "none", lineStyle: { color: cssVar("--slate"), width: 1.5 }, areaStyle: { color: cssVar("--band") } },
            { name: "Resultado recorrente", type: "bar", data: months.map((m) => ({ value: Math.round(res.values[m]), itemStyle: { color: res.values[m] < 0 ? cssVar("--debit") : cssVar("--ledger"), ...(isPartialMonth(m) && { opacity: PARTIAL_OPACITY }) } })), barMaxWidth: 26, itemStyle: { color: cssVar("--ledger") } },
          ],
        }} />
      </Panel>
      <Panel title={<Term k="dre">Demonstração do resultado</Term>} hint="clique num valor de categoria para ver os lançamentos"
        tools={<>
          <div className="segmented">{[6, 12, 24].map((x) => <button key={x} className={n === x ? "on" : ""} onClick={() => setN(x)}>{x} meses</button>)}</div>
          <button className={`btn sm ${av ? "primary" : ""}`} onClick={() => setAv(!av)}>% da receita</button>
        </>} flush>
        <Statement months={months} rows={rows} showAv={av} onCell={onCell} />
        <p className="note" style={{ padding: "8px 18px 14px" }}>
          Compras no cartão entram na data da compra. Pagamento de fatura, transferências entre contas, aportes e resgates ficam fora do resultado.
          {d.valuation && ` ${d.valuation.note}`}
        </p>
      </Panel>
    </>
  );
}
