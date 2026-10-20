import { QueryState } from "../components/QueryState";
import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api } from "../api";
import { useMonth } from "../components/Layout";
import { Panel } from "../components/ui";
import { acct, brl, monthLabel, monthLong, pct } from "../format";

type Row = {
  key: string; id?: string; label: string; level: number; subtotal?: boolean; final?: boolean;
  mes: number; media6: number | null; delta: number | null; delta_pct: number | null; orcamento: number | null;
  execucao: number | null; av: number | null; ytd: number; media12: number | null;
};

const EXPENSE_LINES = new Set(["essenciais", "estilo_vida", "terceiros", "nao_classificado", "impostos_renda", "despesas_financeiras"]);

export default function DreGerencial() {
  const { month } = useMonth();
  const nav = useNavigate();
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const q = useQuery({ queryKey: ["dre-gerencial", month], queryFn: () => api<any>(`/api/dre/gerencial?month=${month}`) });
  const d = q.data;
  if (!d) return <QueryState q={q} what="a DRE gerencial">{() => null}</QueryState>;
  const ind = d.indicadores;
  const rows: Row[] = d.rows;

  // agrupa filhos sob o pai para expandir/recolher
  const tree: { row: Row; kids: { row: Row; kids: Row[] }[] }[] = [];
  for (const r of rows) {
    if (r.level === 0) tree.push({ row: r, kids: [] });
    else if (r.level === 1) tree[tree.length - 1].kids.push({ row: r, kids: [] });
    else { const p = tree[tree.length - 1].kids; p[p.length - 1]?.kids.push(r); }
  }
  const lineOf = (r: Row) => r.key.split(":")[0];
  // valores com sinal: despesa mais negativa que a média ou receita menor que a média pioram o resultado
  // despesa é neutra; só resultados e subtotais desfavoráveis ficam em vermelho (mesma regra do Statement)
  const deltaTone = (r: Row) => (!r.subtotal || r.delta === null || Math.abs(r.delta) < 0.5 ? "" : r.delta < 0 ? "neg" : r.final ? "pos" : "");
  const resultTone = (r: Row, v: number) => (r.subtotal && v < 0 ? "neg" : r.subtotal && r.final && v > 0 ? "pos" : "");
  const isExpense = (r: Row) => EXPENSE_LINES.has(lineOf(r));
  const cells = (r: Row) => (
    <>
      <td className={`num ${resultTone(r, r.mes)}`}>{acct(r.mes)}</td>
      <td className="num soft">{acct(r.media6)}</td>
      <td className={`num ${deltaTone(r)}`}>{r.delta === null ? "—" : `${r.delta > 0 ? "+" : ""}${acct(r.delta)}`}
        {r.delta_pct !== null && Math.abs(r.delta_pct) < 10 && <span className="av">{r.delta_pct > 0 ? "+" : ""}{pct(r.delta_pct, 0)}</span>}</td>
      <td className="num soft">{r.av === null ? "—" : pct(r.av, 0)}</td>
      <td className="num">{r.orcamento && isExpense(r) ? acct(-r.orcamento) : "—"}
        {r.execucao !== null && <span className={`av ${r.execucao > 1 ? "neg" : ""}`}>{pct(r.execucao, 0)} usado</span>}</td>
      <td className={`num total-col ${resultTone(r, r.ytd)}`}>{acct(r.ytd)}</td>
    </>
  );
  const goLedger = (r: Row) => r.id && nav(`/razao?category=${r.id}&month=${month}`);

  return (
    <>
      <section className="panel strip" aria-label="Indicadores">
        <div><div className="lbl">Poupança recorrente</div><div className="val">{pct(ind.taxa_poupanca_mes, 0)}</div>
          <div className="sub">média 6m {pct(ind.taxa_poupanca_6m, 0)}</div></div>
        <div><div className="lbl">Receita recorrente (6m)</div><div className="val num" style={{ textAlign: "left" }}>{brl(ind.receita_recorrente_6m, 0)}</div>
          <div className="sub">gasto médio {brl(ind.gasto_medio_6m, 0)}/mês</div></div>
        <div><div className="lbl">Peso do custo essencial</div><div className="val">{pct(ind.peso_essenciais, 0)}</div>
          <div className="sub">{brl(ind.essenciais_6m, 0)}/mês da receita</div></div>
        <div><div className="lbl">Reserva líquida</div><div className="val num" style={{ textAlign: "left" }}>{brl(ind.reserva_liquida, 0)}</div>
          <div className="sub">{ind.meses_de_essenciais ? `${ind.meses_de_essenciais.toFixed(1)} meses de custo essencial` : "—"}</div></div>
        <div><div className="lbl">Parcelas no próximo mês</div><div className="val num" style={{ textAlign: "left" }}>{brl(ind.parcelas_proximo_mes, 0)}</div>
          <div className="sub">{pct(ind.comprometimento_parcelas, 0)} da receita recorrente</div></div>
        <div><div className="lbl">Extraordinários no ano</div><div className="val num" style={{ textAlign: "left" }}>{brl(ind.extraordinarios_ano, 0)}</div>
          <div className="sub">fora do resultado recorrente</div></div>
      </section>

      <Panel title={<>DRE gerencial · {monthLong(month)} {d.parcial && <span className="chip ochre" style={{ marginLeft: 6 }}>mês em andamento</span>}</>} hint={`média de ${monthLabel(d.media_de[0])} a ${monthLabel(d.media_de[d.media_de.length - 1])}; clique numa categoria para ver os lançamentos`} flush>
        <div className="table-wrap" style={{ maxHeight: "none" }}>
          <table className="stmt">
            <thead><tr><th>Linha</th><th>{monthLabel(month)}</th><th>Média 6m</th><th>Δ vs média</th><th>% receita</th><th>Orçamento</th><th className="total-col">Acum. {month.slice(0, 4)}</th></tr></thead>
            <tbody>
              {tree.map(({ row, kids }) => (
                <Fragment key={row.key}>
                  <tr className={[row.subtotal ? "sub" : "", row.final ? "final" : ""].join(" ")}>
                    <td>{kids.length > 0
                      ? <button className="toggle" onClick={() => setOpen((o) => ({ ...o, [row.key]: !o[row.key] }))} aria-label={open[row.key] ? "Recolher" : "Expandir"}>
                          {open[row.key] ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</button>
                      : <span style={{ display: "inline-block", width: 18 }} />}
                      {row.subtotal && "= "}{row.label}</td>
                    {cells(row)}
                  </tr>
                  {open[row.key] && kids.map(({ row: c, kids: leafs }) => (
                    <Fragment key={c.key}>
                      <tr className="l1">
                        <td style={{ cursor: "pointer" }} onClick={() => leafs.length ? setOpen((o) => ({ ...o, [c.key]: !o[c.key] })) : goLedger(c)}>
                          {leafs.length > 0 && (open[c.key] ? <ChevronDown size={12} /> : <ChevronRight size={12} />)} {c.label}</td>
                        {cells(c)}
                      </tr>
                      {open[c.key] && leafs.map((l) => (
                        <tr key={l.key} className="l2"><td style={{ cursor: "pointer" }} onClick={() => goLedger(l)}>{l.label}</td>{cells(l)}</tr>
                      ))}
                    </Fragment>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="assumptions" style={{ padding: "8px 18px 14px 34px" }}>{d.notas.map((n: string, i: number) => <li key={i}>{n}</li>)}</ul>
      </Panel>
    </>
  );
}
