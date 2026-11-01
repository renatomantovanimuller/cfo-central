import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { MoneyInput } from "../../components/MoneyInput";
import { QueryState } from "../../components/QueryState";
import { Chip, Empty, Money, Panel } from "../../components/ui";
import { brl, parseBRL, pct } from "../../format";

export default function Rebalance() {
  const nav = useNavigate();
  const [raw, setRaw] = useState("");
  const [aporte, setAporte] = useState<number | null>(null);
  const q = useQuery({ queryKey: ["portfolio-rebalance", aporte],
    queryFn: () => api<any>(`/api/portfolio/rebalance${aporte !== null ? `?aporte=${aporte}` : ""}`) });
  const d = q.data;
  if (!d) return <QueryState q={q} what="as sugestões de aporte" layout="panel">{() => null}</QueryState>;
  if (!d.available) return <Panel><Empty title="Sem alocação-alvo" action={<button className="btn" onClick={() => nav("/planejamento")}>Definir alvos</button>}>
    {d.reason}</Empty></Panel>;
  const full = d.rebalanceamento_completo;
  return (
    <>
      <Panel title="Próximo aporte" hint={`origem do valor: ${d.origem_aporte}`}
        tools={<form style={{ display: "flex", gap: 8, alignItems: "center" }} onSubmit={(e) => { e.preventDefault(); setAporte(parseBRL(raw)); }}>
          <MoneyInput value={raw} onChange={setRaw} placeholder={brl(d.aporte, 0)} ariaLabel="Valor do aporte" min={0} width={130} />
          <button className="btn" type="submit">Calcular</button></form>}>
        {d.reserva.aplicar > 0 && <div className="callout info"><div className="grow">
          A reserva de emergência está em {d.reserva.meses?.toFixed(1).replace(".", ",")} meses (mínimo {d.reserva.minimo_meses}).
          {" "}{brl(d.reserva.aplicar)} deste aporte vão primeiro para liquidez diária.</div></div>}
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Classe</th><th className="num">Hoje</th><th className="num">Peso</th><th className="num">Alvo</th>
            <th className="num">Aplicar</th><th className="num">Peso depois</th><th>Como</th></tr></thead>
          <tbody>{d.aporte_sem_venda.map((r: any) => (
            <tr key={r.classe}>
              <td className="strong">{r.classe}</td><td><Money v={r.atual} digits={0} /></td>
              <td className="num">{pct(r.peso_atual)}</td><td className="num">{pct(r.alvo)}</td>
              <td>{r.aplicar >= 1 ? <Money v={r.aplicar} digits={0} /> : <span className="muted">—</span>}</td>
              <td className="num">{pct(r.peso_depois)}{r.desvio_depois_pp !== null && Math.abs(r.desvio_depois_pp) >= 0.5 &&
                <div className="small soft">{r.desvio_depois_pp > 0 ? "+" : ""}{r.desvio_depois_pp.toFixed(1).replace(".", ",")} p.p.</div>}</td>
              <td className="small">{r.sugestao?.texto ?? ""}</td>
            </tr>))}</tbody>
        </table></div>
        <p className="note">Total do aporte: {brl(d.aporte)}. {d.nota}</p>
        {d.classes_sem_alvo.length > 0 && <p className="note">Sem alvo (fora do cálculo): {d.classes_sem_alvo.map((c: any) => `${c.classe} (${brl(c.valor, 0)})`).join(", ")}.</p>}
      </Panel>

      <Panel title="Rebalanceamento completo" hint="levar tudo ao alvo agora, vendendo o que está acima" flush>
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Classe</th><th>Operação</th><th className="num">Valor</th><th className="num">IR estimado</th><th>Observação</th></tr></thead>
          <tbody>{full.operacoes.map((o: any) => (
            <tr key={o.classe}><td className="strong">{o.classe}</td>
              <td>{o.operacao === "vender" ? <Chip tone="red">vender</Chip> : o.operacao === "comprar" ? <Chip tone="green">comprar</Chip> : <Chip>manter</Chip>}</td>
              <td><Money v={o.valor} digits={0} /></td><td>{o.ir_estimado ? <Money v={o.ir_estimado} /> : "—"}</td>
              <td className="small soft">{o.observacao}</td></tr>))}</tbody>
        </table></div>
        <p className="note" style={{ padding: "8px 18px 14px" }}>IR estimado nas vendas: {brl(full.ir_estimado)}.
          {full.ir_nao_estimado.length > 0 && ` Sem estimativa (custo desconhecido): ${full.ir_nao_estimado.join(", ")}.`}
          {" "}Na maioria das vezes, direcionar aportes resolve o desvio sem pagar IR.</p>
      </Panel>
    </>
  );
}
