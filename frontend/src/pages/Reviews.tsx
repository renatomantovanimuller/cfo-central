import { useQuery } from "@tanstack/react-query";
import { useApiMutation } from "../hooks/useApiMutation";
import { QueryState } from "../components/QueryState";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { EventDrawer } from "../components/EventDrawer";
import { CategorySelect, Chip, Empty, EventTypeSelect, Panel, useToast } from "../components/ui";
import { dateTime } from "../format";

const KIND: Record<string, string> = {
  pix_pf_out: "Pix enviado a pessoa", pix_in_unknown: "Recebimento a classificar", low_confidence: "Categoria incerta",
  uncategorized: "Sem categoria", card_payment_unmatched: "Fatura não conciliada", card_not_connected: "Cartão não conectado", override_superseded: "Ajuste substituído", duplicate_account: "Conta duplicada", pending_stale: "Pendente antigo", policy_drift: "Alocação fora da banda", policy_reserve: "Reserva abaixo do mínimo", data_health: "Saúde dos dados",
  recurring_income: "Receita recorrente", anomaly: "Gasto atípico", duplicate: "Possível duplicidade", item_error: "Conexão com erro",
  consent_expiring: "Consentimento vencendo", sync_error: "Falha de sincronização", fgc_limit: "Limite do FGC", exit_no_counterpart: "Saída de investimento sem contrapartida", missing_price: "Sem cotação",
};
const EXIT_OPTIONS: [string, string][] = [
  ["not_connected_account", "Resgatei para conta não conectada"], ["custody_transferred", "Transferi a custódia"],
  ["provider_error", "Erro do provedor — manter posição"], ["loss", "Perda/baixa"],
];
const QUICK: Record<string, [string, string, string | null][]> = {
  pix_pf_out: [["Despesa (terceiros)", "terceiros.pf", null], ["Presente", "compras.presentes", null], ["Empréstimo a amigo", "pat.ignorar", "IGNORE"]],
  pix_in_unknown: [["Salário/bolsa", "rec.salario", null], ["Reembolso de amigo", "terceiros.pf", "REFUND"], ["Presente recebido", "rec.presentes", null]],
  recurring_income: [["É salário/bolsa", "rec.salario", null], ["Freelance", "rec.freela", null]],
};

export default function Reviews() {
  const nav = useNavigate();
  const [status, setStatus] = useState("open");
  const [openTx, setOpenTx] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["reviews", status], queryFn: () => api<any[]>(`/api/reviews?status=${status}`) });
  const act = useApiMutation({
    mutationFn: ({ id, body }: { id: number; body: any }) => api(`/api/reviews/${id}`, { method: "POST", body }),
    successMessage: (_r, v) => (v.body.action === "dismiss" ? "Dispensado" : "Resolvido e aplicado"),
    invalidate: "all",
  });
  const items = q.data ?? [];
  const groups = items.reduce<Record<string, any[]>>((acc, r) => ((acc[r.kind] ??= []).push(r), acc), {});
  return (
    <>
      <div className="toolbar">
        <div className="segmented">{[["open", "Abertas"], ["resolved", "Resolvidas"], ["dismissed", "Dispensadas"]].map(([k, l]) =>
          <button key={k} className={status === k ? "on" : ""} onClick={() => setStatus(k)}>{l}</button>)}</div>
        <span className="note">A revisão não bloqueia a sincronização. Uma decisão sobre um comerciante vale para todos os lançamentos dele.</span>
      </div>
      {!q.data && <QueryState q={q} what="as revisões" layout="panel">{() => null}</QueryState>}
      {q.data && items.length === 0 && <Panel><Empty title={status === "open" ? "Nada para revisar" : "Nenhum item aqui"}>
        {status === "open" ? "Os lançamentos estão classificados com boa confiança." : ""}</Empty></Panel>}
      {Object.entries(groups).map(([kind, rows]) => (
        <Panel key={kind} title={KIND[kind] ?? kind} hint={`${rows.length}`} flush>
          {rows.map((r) => <ReviewRow key={r.id} r={r} onAct={(body) => act.mutate({ id: r.id, body })} nav={nav} open={status === "open"} onOpenTx={setOpenTx} />)}
        </Panel>
      ))}
      {openTx && <EventDrawer id={openTx} onClose={() => setOpenTx(null)} />}
    </>
  );
}

function ReviewRow({ r, onAct, nav, open, onOpenTx }: { r: any; onAct: (b: any) => void; nav: (p: string) => void; open: boolean; onOpenTx: (id: string) => void }) {
  const [cat, setCat] = useState(r.data?.category_id ?? "");
  const [et, setEt] = useState("");
  const tone = r.severity === "high" ? "red" : r.severity === "warn" ? "ochre" : undefined;
  const link = r.entity_type === "merchant" ? `/razao?merchant=${r.entity_id}&all=1` : null;
  const classifiable = (["transaction", "merchant"].includes(r.entity_type) || (r.entity_type === "recurring" && r.data?.merchant_id))
    && !["duplicate", "anomaly"].includes(r.kind);
  const isExit = r.kind === "exit_no_counterpart";
  return (
    <div className="list-row" style={{ padding: "10px 18px", alignItems: "flex-start" }}>
      <div className="grow">
        <div className="t" style={{ whiteSpace: "normal" }}><Chip tone={tone}>{r.severity === "high" ? "urgente" : r.severity === "warn" ? "atenção" : "info"}</Chip> {r.title}</div>
        <div className="s" style={{ marginTop: 3 }}>{r.detail}</div>
        {open && isExit && (
          <>
            <div className="s" style={{ marginTop: 6, whiteSpace: "normal" }}>
              O saldo deste investimento caiu sem venda registrada nem crédito compatível em conta conectada. Enquanto você não decidir,
              o valor continua no patrimônio como "Valores em trânsito". Diga o que aconteceu:
            </div>
            <div className="toolbar" style={{ marginTop: 8 }}>
              {EXIT_OPTIONS.map(([id, label]) => (
                <button key={id} className="btn sm" onClick={() => onAct({ action: "resolve", resolution: id })}>{label}</button>))}
            </div>
          </>
        )}
        {open && classifiable && (
          <div className="toolbar" style={{ marginTop: 8 }}>
            {(QUICK[r.kind] ?? []).map(([l, c, e]) => (
              <button key={l} className="btn sm" onClick={() => onAct({ action: "resolve", category_id: c, event_type: e })}>{l}</button>))}
            <CategorySelect value={cat} onChange={setCat} />
            <EventTypeSelect value={et} onChange={setEt} placeholder="Tipo (opcional)" />
            <button className="btn sm primary" disabled={!cat && !et} onClick={() => onAct({ action: "resolve", category_id: cat || null, event_type: et || null })}>Aplicar</button>
          </div>
        )}
        {!open && <div className="s">Encerrado em {dateTime(r.resolved_at)}</div>}
      </div>
      <div className="toolbar">
        {r.entity_type === "merchant" && link && <button className="btn sm ghost" onClick={() => nav(link)}>Ver lançamentos</button>}
        {r.entity_type === "transaction" && <button className="btn sm ghost" onClick={() => onOpenTx(r.entity_id)}>Abrir lançamento</button>}
        {r.entity_type === "item" && <button className="btn sm ghost" onClick={() => nav("/conexoes")}>Abrir conexões</button>}
        {open && <button className="btn sm" onClick={() => onAct({ action: "dismiss" })}>Dispensar</button>}
      </div>
    </div>
  );
}
