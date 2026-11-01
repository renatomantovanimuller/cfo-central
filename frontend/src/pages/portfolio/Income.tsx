import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import { Chart, kTick, palette } from "../../components/Chart";
import { QueryState } from "../../components/QueryState";
import { Chip, Money, Panel } from "../../components/ui";
import { brl, date, monthLabel, pct } from "../../format";

export default function Income() {
  const q = useQuery({ queryKey: ["portfolio-income"], queryFn: () => api<any>("/api/portfolio/income") });
  const d = q.data;
  if (!d) return <QueryState q={q} what="os proventos" layout="panel">{() => null}</QueryState>;
  const tickers = Array.from(new Set(d.por_mes.flatMap((m: any) => Object.keys(m.por_ativo)))) as string[];
  return (
    <>
      <section className="panel strip">
        <div><div className="lbl">Proventos em 12 meses</div><div className="val num" style={{ textAlign: "left" }}><Money v={d.total_12m} /></div>
          <div className="sub">média de {brl(d.media_mensal_12m)} por mês</div></div>
        <div><div className="lbl">Renda fixa: próximo mês</div><div className="val num" style={{ textAlign: "left" }}><Money v={d.renda_fixa_mes_estimada} /></div>
          <div className="sub">bruto, pelo CDI atual ({pct(d.cdi_mes, 2)} no mês)</div></div>
        <div><div className="lbl">Renda passiva estimada</div><div className="val num" style={{ textAlign: "left" }}><Money v={d.renda_passiva_mes_estimada} /></div>
          <div className="sub">por mês: renda fixa + média dos proventos</div></div>
      </section>

      <Panel title="Proventos recebidos por mês" hint="créditos no seu extrato">
        {d.total_12m > 0 ? (
          <Chart height={240} option={{
            tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v) },
            xAxis: { type: "category", data: d.por_mes.map((m: any) => monthLabel(m.mes)) },
            yAxis: { type: "value", axisLabel: { formatter: kTick } },
            series: tickers.map((t, i) => ({ name: t, type: "bar", stack: "p", barMaxWidth: 26, itemStyle: { color: palette()[i % 10] },
              data: d.por_mes.map((m: any) => m.por_ativo[t] ?? 0) })),
          }} />
        ) : <p className="muted">Nenhum provento creditado nos últimos 12 meses.</p>}
      </Panel>

      <Panel title="Por ativo" flush>
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Ativo</th><th className="num">Saldo</th><th className="num">Recebido 12m</th><th className="num">DY 12m</th>
            <th className="num hide-sm">Yield on cost</th><th className="num hide-sm">Fonte: por cota 12m</th><th>Próxima data-com</th></tr></thead>
          <tbody>{d.por_ativo.map((r: any) => (
            <tr key={r.ativo}>
              <td><div className="strong">{r.ativo} {!r.na_carteira && <Chip>fora da carteira</Chip>}</div>
                <div className="small muted">{[r.classe, r.tipos?.join(", ")].filter(Boolean).join(" · ")}</div>
                {r.observacao && <div className="small muted">{r.observacao}</div>}</td>
              <td>{r.saldo !== null ? <Money v={r.saldo} /> : "—"}</td>
              <td><Money v={r.recebido_12m} /></td>
              <td className="num">{r.dy_12m !== null ? pct(r.dy_12m, 2) : "—"}</td>
              <td className="num hide-sm">{r.yoc_12m !== null ? pct(r.yoc_12m, 2) : "—"}</td>
              <td className="num hide-sm">{r.por_cota_12m_fonte !== null ? <>{brl(r.por_cota_12m_fonte, 4)}{r.dy_12m_fonte !== null && <div className="small soft">{pct(r.dy_12m_fonte, 2)} da cotação</div>}</> : "—"}</td>
              <td>{r.proximos?.length ? r.proximos.map((p: any) => <div key={p.data_com}>{date(p.data_com)} · {brl(p.estimado)}</div>) : <span className="muted">—</span>}</td>
            </tr>))}</tbody>
        </table></div>
        <p className="note" style={{ padding: "8px 18px 14px" }}>{d.nota}</p>
      </Panel>

      {d.renda_fixa_titulos.length > 0 && <Panel title="Renda fixa: rendimento estimado do próximo mês" flush>
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Título</th><th className="num">Valor bruto</th><th className="num">Taxa no mês</th><th className="num">Rendimento</th></tr></thead>
          <tbody>{d.renda_fixa_titulos.map((r: any, i: number) => <tr key={i}><td>{r.ativo}</td><td><Money v={r.valor} /></td>
            <td className="num">{pct(r.taxa_mes, 2)}</td><td><Money v={r.rendimento_mes} /></td></tr>)}</tbody>
        </table></div>
      </Panel>}
    </>
  );
}
