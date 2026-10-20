import { QueryState } from "../components/QueryState";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Chart, cssVar, kTick } from "../components/Chart";
import { Empty, Money, Panel } from "../components/ui";
import { brl, date, monthLabel, pct } from "../format";

export default function Cards() {
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["cards"], queryFn: () => api<any>("/api/cards") });
  const d = q.data;
  if (!d) return <QueryState q={q} what="os cartões">{() => null}</QueryState>;
  if (!d.cards.length) return <Panel><Empty title="Nenhum cartão conectado" /></Panel>;
  const inst = d.installments;
  return (
    <>
      <div className="grid g2">
        {d.cards.map((c: any) => {
          const used = c.used_total ?? c.current;
          const u = c.limit ? used / c.limit : null;
          return (
            <Panel key={c.account_id} title={c.name} hint={c.institution}
              tools={<button className="btn sm" onClick={() => nav(`/razao?account=${c.account_id}`)}>Lançamentos</button>}>
              <div className="strip" style={{ margin: "0 -18px", borderBottom: "1px solid var(--rule)" }}>
                <div><div className="lbl">Fatura atual</div><div className="val num" style={{ textAlign: "left" }}>{brl(c.current)}</div>
                  <div className="sub">vence {date(c.due_date)}, fecha {date(c.close_date)}</div></div>
                <div><div className="lbl">Limite comprometido</div><div className="val num" style={{ textAlign: "left" }}>{brl(used)}</div>
                  <div className="sub">{pct(u, 0)} de {brl(c.limit, 0)}{c.contract_limit && c.limit && c.contract_limit > c.limit ? ` (contratado ${brl(c.contract_limit, 0)})` : ""}</div></div>
                <div><div className="lbl">Disponível</div><div className="val num" style={{ textAlign: "left" }}>{brl(c.available)}</div></div>
              </div>
              {u !== null && <div className={`bar ${u > 0.8 ? "debit" : ""}`} style={{ marginTop: 12 }}><i style={{ width: `${Math.min(100, u * 100)}%` }} /></div>}
              <h4 style={{ margin: "14px 0 4px" }}>Faturas fechadas</h4>
              {c.bills.length === 0 ? <p className="muted">Sem faturas informadas.</p> : (
                <Chart height={160} option={{ legend: false, tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v) },
                  xAxis: { type: "category", data: [...c.bills].reverse().map((b: any) => date(b.due_date).slice(3)) },
                  yAxis: { type: "value", axisLabel: { formatter: kTick } },
                  series: [{ type: "bar", data: [...c.bills].reverse().map((b: any) => Math.round(b.total ?? 0)), itemStyle: { color: cssVar("--blue"), borderRadius: [2, 2, 0, 0] }, barMaxWidth: 22 }] }} />)}
            </Panel>
          );
        })}
      </div>
      <div className="grid g-wide">
        <Panel title="Parcelas já contratadas" hint="o que vai cair nas próximas faturas">
          {inst.by_month.length === 0 ? <p className="muted">Nenhuma compra parcelada em aberto.</p> : (
            <Chart height={240} option={{ legend: false, tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v) },
              xAxis: { type: "category", data: inst.by_month.map((x: any) => monthLabel(x.month)) },
              yAxis: { type: "value", axisLabel: { formatter: kTick } },
              series: [{ type: "bar", data: inst.by_month.map((x: any) => Math.round(x.amount)), itemStyle: { color: cssVar("--ochre"), borderRadius: [2, 2, 0, 0] }, barMaxWidth: 30 }] }} />)}
          <p className="note">Total a vencer em parcelas: {brl(inst.total)}.</p>
        </Panel>
        <Panel title="Compras parceladas em aberto">
          {inst.plans.length === 0 && <p className="muted">Nada parcelado.</p>}
          {inst.plans.map((p: any) => (
            <div key={p.key} className="list-row"><div className="grow"><div className="t">{p.description}</div>
              <div className="s">{p.paid}/{p.total} pagas; faltam {p.remaining} de {brl(p.installment)}</div></div><Money v={p.remaining_amount} colored={false} /></div>))}
        </Panel>
      </div>
      <Panel title="Gasto no cartão por mês" hint="por data de compra">
        <Chart height={220} option={{ legend: false, tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v) },
          xAxis: { type: "category", data: d.monthly_spend.map((x: any) => monthLabel(x.month)) },
          yAxis: { type: "value", axisLabel: { formatter: kTick } },
          series: [{ type: "line", data: d.monthly_spend.map((x: any) => Math.round(x.value)), symbolSize: 6, areaStyle: { color: cssVar("--band") }, lineStyle: { color: cssVar("--ledger"), width: 2 }, itemStyle: { color: cssVar("--ledger") } }] }} />
      </Panel>
    </>
  );
}
