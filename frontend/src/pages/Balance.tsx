import { Link } from "react-router-dom";
import { QueryState } from "../components/QueryState";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Chart, cssVar, kTick } from "../components/Chart";
import { Chip, Panel } from "../components/ui";
import { acct, brl, date } from "../format";

function Line({ label, v, strong, indent, muted }: { label: string; v: number; strong?: boolean; indent?: boolean; muted?: boolean }) {
  return (
    <tr className={strong ? "sub" : indent ? "l1" : ""}>
      <td className={muted ? "muted" : ""}>{strong ? "= " : ""}{label}</td>
      <td className={`num ${strong && v < 0 ? "neg" : ""}`}>{acct(v)}</td>
    </tr>
  );
}

export default function Balance() {
  const q = useQuery({ queryKey: ["balance"], queryFn: () => api<any>("/api/balance") });
  const h = useQuery({ queryKey: ["bp-history-24"], queryFn: () => api<any[]>("/api/balance/history?months=18") });
  const d = q.data;
  if (!d) return <QueryState q={q} what="o balanço">{() => null}</QueryState>;
  const t = d.totals;
  const classes = Object.entries(d.investments_by_class as Record<string, number>).sort((a, b) => b[1] - a[1]);
  const hist = h.data ?? [];
  return (
    <>
      <div className="grid g2">
        <Panel title="Ativo" hint={`posição em ${date(d.as_of)}`} flush>
          <table className="stmt"><tbody>
            <Line label="Caixa e equivalentes" v={t.cash} />
            {d.cash.map((c: any) => <Line key={c.account_id} label={`${c.name} (${c.institution ?? ""})`} v={c.balance} indent />)}
            <Line label="Investimentos" v={t.investments} />
            {classes.map(([k, v]) => <Line key={k} label={k} v={v} indent />)}
            {(t.in_transit ?? 0) > 0 && <Line label="Valores em trânsito" v={t.in_transit} />}
            {(d.in_transit ?? []).map((x: any) => (
              <tr key={x.key} className="l1"><td>{x.name} — {x.label ?? "em trânsito"} (saída em {date(x.date)}) <Link to="/revisao">revisar</Link></td>
                <td className="num">{acct(x.amount)}</td></tr>))}
            {d.manual_assets.length > 0 && <Line label="Outros ativos (manuais)" v={t.manual_assets} />}
            {d.manual_assets.map((m: any) => <Line key={m.id} label={`${m.name} (em ${date(m.as_of)})`} v={m.value} indent />)}
            <Line label="Ativo total" v={t.assets} strong />
          </tbody></table>
        </Panel>
        <Panel title="Passivo e patrimônio líquido" flush>
          <table className="stmt"><tbody>
            <Line label="Cartões de crédito" v={t.card_current + t.card_future} />
            {d.cards.map((c: any) => (
              <tr key={c.account_id} className="l1"><td>{c.name}: fatura atual {brl(c.current)}, a faturar {brl(Math.max(0, (c.used_total ?? c.current) - c.current))}</td>
                <td className="num">{acct(c.used_total ?? c.current)}</td></tr>))}
            <Line label="Empréstimos e financiamentos" v={t.loans} />
            {d.loans.map((l: any) => <Line key={l.id} label={l.name} v={l.outstanding} indent />)}
            {d.manual_liabilities.length > 0 && <Line label="Outros passivos (manuais)" v={t.manual_liabilities} />}
            <Line label="Passivo total" v={t.liabilities} strong />
            <tr><td colSpan={2} style={{ height: 10 }} /></tr>
            <Line label="Patrimônio líquido" v={t.net_worth} strong />
            <tr className="l1"><td>Patrimônio de liquidez imediata</td><td className="num">{acct(t.liquid_net_worth)}</td></tr>
          </tbody></table>
        </Panel>
      </div>
      <Panel title="Evolução patrimonial" hint="fim de cada mês">
        {!h.data && <QueryState q={h} what="a evolução patrimonial" layout="panel">{() => null}</QueryState>}
        <Chart height={300} option={{
          tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v) },
          xAxis: { type: "category", data: hist.map((x) => date(x.date).slice(3)) },
          yAxis: { type: "value", axisLabel: { formatter: kTick } },
          series: [
            { name: "Caixa", type: "bar", stack: "a", data: hist.map((x) => Math.round(x.cash)), itemStyle: { color: cssVar("--slate") } },
            { name: "Investimentos", type: "bar", stack: "a", data: hist.map((x) => Math.round(x.investments)), itemStyle: { color: cssVar("--ledger") } },
            { name: "Cartões", type: "bar", stack: "b", data: hist.map((x) => -Math.round(x.cards)), itemStyle: { color: cssVar("--debit") } },
            { name: "Patrimônio líquido", type: "line", data: hist.map((x) => Math.round(x.net_worth)), symbolSize: 6, lineStyle: { color: cssVar("--ink"), width: 2 }, itemStyle: { color: cssVar("--ink") } },
          ],
        }} />
        <div className="toolbar" style={{ marginTop: 6 }}>
          {hist.some((x) => x.inferred) && <Chip tone="ochre">meses estimados</Chip>}
          <span className="note">Meses sem snapshot: contas e cartões recuados pelos lançamentos; investimentos recuados pelos aportes e pelo retorno estimado da carteira atual.</span>
        </div>
      </Panel>
      <Panel title="Premissas">
        <ul className="assumptions">{d.assumptions.map((a: string, i: number) => <li key={i}>{a}</li>)}</ul>
      </Panel>
    </>
  );
}
