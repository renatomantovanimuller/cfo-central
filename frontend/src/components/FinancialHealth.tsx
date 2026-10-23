import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Chip, Panel } from "./ui";
import { monthLabel } from "../format";

const TIER: Record<string, [string, "green" | "ochre" | "red"]> = {
  saudavel: ["saudável", "green"], equilibrando: ["equilibrando", "ochre"], vulneravel: ["vulnerável", "red"],
};

export function useFinancialHealth() {
  return useQuery({ queryKey: ["financial-health"], queryFn: () => api<any>("/api/financial-health") });
}

function ScoreBar({ v }: { v: number | null }) {
  return <div className={`bar ${v !== null && v < 40 ? "debit" : ""}`}><i style={{ width: `${v ?? 0}%`, opacity: v === null ? 0 : 1 }} /></div>;
}

/** Cartão do Painel: nota geral, faixa e os quatro pilares. */
export function HealthCard({ onOpen }: { onOpen: () => void }) {
  const q = useFinancialHealth();
  const h = q.data;
  if (!h || h.nota === null) return null;
  const [label, tone] = TIER[h.faixa] ?? ["", "ochre"];
  const prev = h.historico.length > 1 ? h.historico[h.historico.length - 2].nota : null;
  return (
    <Panel title="Saúde financeira" hint={`${h.medidos} de ${h.de} indicadores medidos`}
      tools={<button className="btn sm ghost" onClick={onOpen}>Ver indicadores</button>}>
      <div className="health">
        <div className="health-score">
          <div className="big num">{h.nota}<span className="soft small">/100</span></div>
          <Chip tone={tone}>{label}</Chip>
          {prev !== null && <div className="soft small">{h.nota - prev >= 0 ? "+" : ""}{h.nota - prev} desde o mês passado</div>}
        </div>
        <div className="health-pillars">{h.pilares.map((p: any) => (
          <div key={p.chave} className="bar-row" style={{ gridTemplateColumns: "minmax(0,1fr) 120px 36px" }}>
            <span>{p.nome}</span><ScoreBar v={p.nota} /><span className="num small">{p.nota ?? "—"}</span></div>))}</div>
      </div>
    </Panel>
  );
}

/** Painel completo (Planejamento): cada indicador com valor, explicação e o que fazer. */
export function HealthDetail() {
  const q = useFinancialHealth();
  const h = q.data;
  if (!h) return null;
  const [label, tone] = TIER[h.faixa] ?? ["sem dado", "ochre"];
  return (
    <Panel title="Saúde financeira" hint={h.nota_metodo} flush>
      <div className="toolbar" style={{ padding: "12px 18px 0" }}>
        <span className="big num" style={{ fontSize: 28 }}>{h.nota ?? "—"}</span><span className="soft">/100</span>
        {h.faixa && <Chip tone={tone}>{label}</Chip>}
        {h.historico.length > 1 && <span className="soft small">
          {h.historico.map((x: any) => `${monthLabel(x.mes)}: ${x.nota}`).join(" · ")}</span>}
      </div>
      <div className="table-wrap"><table className="table">
        <thead><tr><th>Pilar</th><th>Indicador</th><th className="num">Nota</th><th>Situação</th><th>O que fazer</th></tr></thead>
        <tbody>{h.indicadores.map((i: any) => (
          <tr key={i.chave}>
            <td className="soft small">{h.pilares.find((p: any) => p.chave === i.pilar)?.nome}</td>
            <td title={i.explicacao}><div className="strong">{i.nome}</div><div className="small muted" style={{ whiteSpace: "normal" }}>{i.explicacao}</div></td>
            <td className="num">{i.nota ?? "—"}<ScoreBar v={i.nota} /></td>
            <td className="small" style={{ whiteSpace: "normal" }}>{i.valor}</td>
            <td className="small soft" style={{ whiteSpace: "normal" }}>{i.como_melhorar}</td>
          </tr>))}</tbody>
      </table></div>
    </Panel>
  );
}
