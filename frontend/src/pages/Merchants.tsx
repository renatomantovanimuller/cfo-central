import { useQuery } from "@tanstack/react-query";
import { useApiMutation } from "../hooks/useApiMutation";
import { QueryState } from "../components/QueryState";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { CategoryOptions, Chip, Money, Panel, useCategories, useToast } from "../components/ui";
import { brl, date, prettyName } from "../format";

export default function Merchants() {
  const nav = useNavigate();
  const cats = useCategories();
  const [filter, setFilter] = useState("");
  const [months, setMonths] = useState(12);
  const q = useQuery({ queryKey: ["merchants", months], queryFn: () => api<any[]>(`/api/merchants?months=${months}`) });
  const patch = useApiMutation({
    mutationFn: ({ id, body }: { id: number; body: any }) => api(`/api/merchants/${id}`, { method: "PATCH", body }),
    successMessage: "Comerciante classificado. Lançamentos atualizados",
    invalidate: "all",
  });
  if (!q.data) return <QueryState q={q} what="os comerciantes">{() => null}</QueryState>;
  const rows = (q.data ?? []).filter((m) => !filter || m.name.toLowerCase().includes(filter.toLowerCase()));
  // participação só entre gastos: receitas (salário, reembolsos) na mesma soma davam percentuais sem sentido
  const total = rows.reduce((a, m) => a + Math.min(0, m.total), 0);
  return (
    <Panel title={`${rows.length} comerciantes e contrapartes`} hint="classifique uma vez; todos os lançamentos seguem" flush
      tools={<>
        <input className="input" placeholder="Filtrar" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <div className="segmented">{[3, 12, 24].map((x) => <button key={x} className={months === x ? "on" : ""} onClick={() => setMonths(x)}>{x}m</button>)}</div>
      </>}>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Nome</th><th>Documento</th><th className="num">Lançamentos</th><th className="num">Ticket médio</th>
            <th className="num">Total</th><th className="num">% dos gastos</th><th>Último</th><th>Categoria padrão</th></tr></thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.id} className="clickable" onClick={() => nav(`/razao?merchant=${m.id}&all=1`)}>
                <td title={m.name}><div className="strong">{prettyName(m.name)}</div>
                  {m.cnae && <div className="small muted" title={`CNAE ${m.cnae} (${m.cnae_source === "receita" ? "consulta do CNPJ" : "Pluggy"})`}>
                    {m.cnae_desc ?? (m.cnae_ramo ? `${m.cnae_ramo} · CNAE ${m.cnae}` : `CNAE ${m.cnae}`)}</div>}</td>
                <td className="soft small">{m.doc ? (m.doc.length === 14 ? "CNPJ " : "CPF ") + m.doc : "—"}</td>
                <td className="num">{m.count}</td>
                <td><Money v={m.avg_ticket} /></td>
                <td><Money v={m.total} /></td>
                <td className="num soft">{total && m.total < 0 ? ((m.total / total) * 100).toFixed(1).replace(".", ",") + "%" : ""}</td>
                <td className="soft">{date(m.last)}</td>
                <td onClick={(e) => e.stopPropagation()}>
                  <select className="select inline" value={m.category_origin === "user" ? m.category_id ?? "" : ""}
                    onChange={(e) => patch.mutate({ id: m.id, body: { default_category_id: e.target.value } })}>
                    <option value="">{m.category ? `Automático: ${m.category}` : "Automático"}</option>
                    {cats.data && <CategoryOptions cats={cats.data} />}
                  </select>
                  {m.category_origin === "user" && <Chip tone="green">sua escolha</Chip>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note" style={{ padding: "8px 18px 14px" }}>Gastos no período: {brl(total)}. Pix para pessoa física aparece pelo CPF da contraparte.</p>
      <CnpjEnrichment />
    </Panel>
  );
}

function CnpjEnrichment() {
  const q = useQuery({ queryKey: ["merchants-enrichment"], queryFn: () => api<any>("/api/merchants/enrichment") });
  const toggle = useApiMutation({
    mutationFn: (habilitado: boolean) => api("/api/merchants/enrichment", { method: "PUT", body: { habilitado } }),
    invalidate: [["merchants-enrichment"]],
  });
  const run = useApiMutation({
    mutationFn: () => api<any>("/api/merchants/enrich", { method: "POST" }),
    successMessage: (r: any) => `${r.consultados} CNPJs consultados, ${r.com_cnae} com ramo identificado${r.erro ? ` (${r.erro})` : ""}`,
    invalidate: "all",
  });
  const st = q.data;
  if (!st) return null;
  return (
    <div style={{ padding: "0 18px 16px", borderTop: "1px solid var(--rule)" }}>
      <h4 style={{ margin: "12px 0 4px" }}>Ramo de atividade pelo CNPJ</h4>
      <p className="note" style={{ whiteSpace: "normal" }}>
        O CNAE (ramo registrado na Receita) ajuda a classificar Pix e boletos para empresas: uma farmácia é saúde, um posto é combustível.
        O app já usa o CNAE que o banco informa ({st.com_cnae} de {st.com_cnpj} comerciantes com CNPJ têm ramo).
        Ative a consulta pública para completar os demais: envia só o CNPJ do estabelecimento ao serviço BrasilAPI (dados abertos da Receita), nunca CPFs nem valores.</p>
      <div className="toolbar">
        <label className="toolbar" style={{ gap: 6 }}><input type="checkbox" checked={st.habilitado} disabled={toggle.isPending}
          onChange={(e) => toggle.mutate(e.target.checked)} /> Consultar CNPJs automaticamente a cada sincronização</label>
        {st.habilitado && st.pendentes > 0 && <button className="btn sm" disabled={run.isPending} onClick={() => run.mutate()}>
          {run.isPending ? "Consultando…" : `Consultar agora (${st.pendentes} pendentes)`}</button>}
      </div>
    </div>
  );
}
