import { useQuery } from "@tanstack/react-query";
import { useApiMutation } from "../hooks/useApiMutation";
import { QueryState } from "../components/QueryState";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { EventDrawer } from "../components/EventDrawer";
import { CategorySelect, Chip, Empty, EventTypeSelect, Panel, useToast } from "../components/ui";
import { dateTime } from "../format";
import { dedupeReviews, isDecision, reviewSummary } from "../components/reviewBadge";

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

// ordem das decisões: primeiro o que mais muda os números (renda), depois o resto
const DECISION_ORDER = ["recurring_income", "pix_in_unknown", "pix_pf_out", "exit_no_counterpart", "uncategorized", "low_confidence", "duplicate"];
// para onde ir para resolver cada aviso do sistema
const NOTICE_LINK: Record<string, [string, string]> = {
  data_health: ["/saude", "Ver em Saúde dos dados"], policy_reserve: ["/planejamento", "Abrir planejamento"], policy_drift: ["/planejamento", "Abrir planejamento"],
  item_error: ["/conexoes", "Abrir conexões"], consent_expiring: ["/conexoes", "Renovar consentimento"], sync_error: ["/conexoes", "Abrir conexões"],
  fgc_limit: ["/carteira", "Ver carteira"], missing_price: ["/config", "Conferir ativos"], card_payment_unmatched: ["/cartoes", "Ver cartões"],
  card_not_connected: ["/conexoes", "Conectar o cartão"], duplicate_account: ["/conexoes", "Abrir conexões"], anomaly: ["/razao", "Ver lançamentos"],
};
const NOTICE_HELP: Record<string, string> = {
  data_health: "Conferência automática entre o que o banco informa e o que foi importado. Costuma se resolver sozinha na próxima sincronização; se persistir, veja os detalhes.",
  policy_reserve: "A reserva de emergência está abaixo do mínimo que você definiu no plano.",
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
  const items = dedupeReviews(q.data);
  const isOpen = status === "open";
  const decisions = items.filter(isDecision);
  const notices = items.filter((r) => !isDecision(r) && r.severity !== "info");
  const infos = items.filter((r) => !isDecision(r) && r.severity === "info");
  const byKind = (rows: any[], order: string[] = []) => {
    const g = rows.reduce<Record<string, any[]>>((acc, r) => ((acc[r.kind] ??= []).push(r), acc), {});
    const rank = (k: string) => (order.indexOf(k) < 0 ? 99 : order.indexOf(k));
    return Object.entries(g).sort(([a], [b]) => rank(a) - rank(b));
  };
  const row = (r: any) => <ReviewRow key={r.id} r={r} onAct={(body) => act.mutate({ id: r.id, body })} nav={nav} open={isOpen} onOpenTx={setOpenTx} />;
  const sum = reviewSummary(q.data);
  return (
    <>
      <div className="toolbar">
        <div className="segmented">{[["open", "Abertas"], ["resolved", "Resolvidas"], ["dismissed", "Dispensadas"]].map(([k, l]) =>
          <button key={k} className={status === k ? "on" : ""} onClick={() => setStatus(k)}>{l}</button>)}</div>
        {isOpen && q.data && items.length > 0 && <span className="soft">
          <b>{sum.pending}</b> {sum.pending === 1 ? "decisão pendente" : "decisões pendentes"}
          {sum.notices ? <> · {sum.notices} {sum.notices === 1 ? "aviso" : "avisos"}{sum.urgent ? ` (${sum.urgent} urgente${sum.urgent > 1 ? "s" : ""})` : ""}</> : null}</span>}
      </div>
      {!q.data && <QueryState q={q} what="as revisões" layout="panel">{() => null}</QueryState>}
      {q.data && items.length === 0 && <Panel><Empty title={isOpen ? "Tudo em dia" : "Nenhum item aqui"}>
        {isOpen ? "Os lançamentos estão classificados com boa confiança e não há avisos." : ""}</Empty></Panel>}

      {decisions.length > 0 && <>
        {isOpen && <div className="section-title"><h3>Decisões rápidas</h3>
          <span>um clique classifica todos os lançamentos da mesma contraparte, inclusive os futuros</span></div>}
        {byKind(decisions, DECISION_ORDER).map(([kind, rows]) => (
          <Panel key={kind} title={KIND[kind] ?? kind} hint={`${rows.length}`} flush>{rows.map(row)}</Panel>))}
      </>}

      {notices.length > 0 && <>
        {isOpen && <div className="section-title"><h3>Avisos</h3><span>pedem atenção, mas não uma classificação</span></div>}
        {byKind(notices).map(([kind, rows]) => (
          <Panel key={kind} title={KIND[kind] ?? kind} hint={NOTICE_HELP[kind] ?? `${rows.length}`} flush>{rows.map(row)}</Panel>))}
      </>}

      {infos.length > 0 && (
        <details className="panel" open={!isOpen || (decisions.length === 0 && notices.length === 0)}>
          <summary><h2>Informativos</h2><span className="note">{infos.length} {infos.length === 1 ? "item" : "itens"} só para seu conhecimento</span></summary>
          {byKind(infos).map(([kind, rows]) => (
            <div key={kind}><div className="note" style={{ padding: "8px 18px 0", fontWeight: 600 }}>{KIND[kind] ?? kind}</div>{rows.map(row)}</div>))}
        </details>
      )}
      {openTx && <EventDrawer id={openTx} onClose={() => setOpenTx(null)} />}
    </>
  );
}

function ReviewRow({ r, onAct, nav, open, onOpenTx }: { r: any; onAct: (b: any) => void; nav: (p: string) => void; open: boolean; onOpenTx: (id: string) => void }) {
  const [cat, setCat] = useState(r.data?.category_id ?? "");
  const [et, setEt] = useState("");
  const tone = r.severity === "high" ? "red" : r.severity === "warn" ? "ochre" : undefined;
  const mergedMerchant = r.merged?.entity_type === "merchant" ? r.merged.entity_id : null;
  const link = r.entity_type === "merchant" ? `/razao?merchant=${r.entity_id}&all=1`
    : mergedMerchant ? `/razao?merchant=${mergedMerchant}&all=1` : r.data?.merchant_id ? `/razao?merchant=${r.data.merchant_id}&all=1` : null;
  const notice = NOTICE_LINK[r.kind];
  const classifiable = (["transaction", "merchant"].includes(r.entity_type) || (r.entity_type === "recurring" && r.data?.merchant_id))
    && !["duplicate", "anomaly"].includes(r.kind);
  const isExit = r.kind === "exit_no_counterpart";
  return (
    <div className="list-row" style={{ padding: "10px 18px", alignItems: "flex-start" }}>
      <div className="grow">
        <div className="t" style={{ whiteSpace: "normal" }}><Chip tone={tone}>{r.severity === "high" ? "urgente" : r.severity === "warn" ? "atenção" : "info"}</Chip> {r.title}</div>
        <div className="s" style={{ marginTop: 3, whiteSpace: "normal" }}>{r.detail}</div>
        {r.merged && <div className="s" style={{ marginTop: 2, whiteSpace: "normal" }}>No histórico: {r.merged.title}</div>}
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
        {link && <button className="btn sm ghost" onClick={() => nav(link)}>Ver lançamentos</button>}
        {!link && notice && r.entity_type !== "item" && <button className="btn sm ghost" onClick={() => nav(notice[0])}>{notice[1]}</button>}
        {r.entity_type === "transaction" && <button className="btn sm ghost" onClick={() => onOpenTx(r.entity_id)}>Abrir lançamento</button>}
        {r.entity_type === "item" && <button className="btn sm ghost" onClick={() => nav("/conexoes")}>Abrir conexões</button>}
        {open && <button className="btn sm" onClick={() => onAct({ action: "dismiss" })} title="Tira da lista de abertas; continua consultável em Dispensadas">Dispensar</button>}
      </div>
    </div>
  );
}
