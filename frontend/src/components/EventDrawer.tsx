import { useQuery } from "@tanstack/react-query";
import { useRef } from "react";
import { useApiMutation } from "../hooks/useApiMutation";
import { undoCategoryBody } from "./undoCategory";
import { QueryState } from "./QueryState";
import { useState } from "react";
import { api } from "../api";
import { brl, date, dateTime, EVENT_LABELS, RULE_SOURCE } from "../format";
import { CategorySelect, Chip, Drawer, EventTypeSelect, useToast } from "./ui";

export function EventDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ["event", id], queryFn: () => api<any>(`/api/events/${id}`) });
  const previousCat = useRef<Record<string, any> | undefined>();
  const [note, setNote] = useState<string | null>(null);
  const save = useApiMutation({
    mutationFn: (body: any) => api<any>(`/api/events/${id}`, { method: "PATCH", body }),
    successMessage: (r, body) => ("category_id" in body ? `Categoria alterada${r.changed > 1 ? ` · ${r.changed} lançamentos reclassificados` : ""}`
      : r.changed > 1 ? `Salvo. ${r.changed} lançamentos reclassificados` : "Salvo"),
    successAction: (_r, body) => ("category_id" in body && previousCat.current !== undefined
      ? { label: "Desfazer", onClick: () => save.mutate(previousCat.current!) } : undefined),
    invalidate: "all",
  });
  const d = q.data;
  const e = d?.event, t = d?.transaction;
  return (
    <Drawer title={e ? <><h3>{e.description}</h3><div className={`num ${e.amount < 0 ? "neg" : "pos"}`} style={{ textAlign: "left", fontSize: 20, fontWeight: 650 }}>{brl(e.amount)}</div></> : "Lançamento"} onClose={onClose}>
      {!d ? <QueryState q={q} what="o lançamento" layout="panel">{() => null}</QueryState> : (
        <>
          <section>
            <h4 style={{ margin: "0 0 8px" }}>Classificação</h4>
            <div className="grid" style={{ gap: 8 }}>
              <label className="field">Categoria
                <CategorySelect value={e.category_id} onChange={(v) => { previousCat.current = undoCategoryBody(e.category_id, !!d.override); save.mutate({ category_id: v || null, learn: true }); }} /></label>
              <label className="field">Tipo de evento
                <EventTypeSelect value={d.override?.event_type ?? ""} placeholder={`Automático (${EVENT_LABELS[e.event_type]})`}
                  onChange={(v) => save.mutate({ event_type: v || null, learn: false })} /></label>
              <label className="field">Nota
                <textarea className="input" style={{ height: 60, paddingTop: 6 }} defaultValue={e.note ?? ""}
                  onChange={(ev) => setNote(ev.target.value)} /></label>
              <div className="toolbar">
                {note !== null && <button className="btn sm primary" onClick={() => save.mutate({ note, learn: false })}>Salvar nota</button>}
                {d.override && <button className="btn sm" onClick={() => save.mutate({ clear: true })}>Voltar para automático</button>}
              </div>
              <p className="note">Ao trocar a categoria, o comerciante aprende e os demais lançamentos dele seguem a mesma classificação.</p>
            </div>
          </section>
          <section>
            <h4 style={{ margin: "0 0 8px" }}>Por que foi classificado assim</h4>
            <dl className="kv">
              <dt>Origem</dt><dd>{RULE_SOURCE[e.rule_source] ?? e.rule_source} <span className="muted">({e.rule_id ?? "—"})</span></dd>
              <dt>Confiança</dt><dd>{(e.confidence * 100).toFixed(0)}% {e.is_inferred ? <Chip tone="ochre">inferido</Chip> : <Chip tone="green">confirmado</Chip>}</dd>
              <dt>Tipo</dt><dd>{EVENT_LABELS[e.event_type]}</dd>
              {e.review_reason && <><dt>Revisão</dt><dd>{e.review_reason}</dd></>}
              {d.rule && <><dt>Regra</dt><dd>{d.rule.field} {d.rule.operator} “{d.rule.pattern}”</dd></>}
              {d.merchant && <><dt>Comerciante</dt><dd>{d.merchant.name} {d.merchant.doc && <span className="muted">{d.merchant.doc}</span>}</dd></>}
              {d.transfer && <><dt>Transferência</dt><dd>par conciliado ({d.transfer.method})</dd></>}
              {d.card_link && <><dt>Fatura</dt><dd>conciliada por {d.card_link.method} (dif. {brl(d.card_link.diff)})</dd></>}
            </dl>
          </section>
          <section>
            <h4 style={{ margin: "0 0 8px" }}>Dados da fonte</h4>
            <dl className="kv">
              <dt>Data</dt><dd>{date(t.date)} {t.status === "PENDING" && <Chip tone="ochre">pendente</Chip>}</dd>
              <dt>Data de caixa</dt><dd>{date(e.cash_date)}</dd>
              <dt>Categoria Pluggy</dt><dd>{t.pluggy_category ?? "—"} <span className="muted">{t.pluggy_category_id}</span></dd>
              <dt>Forma</dt><dd>{t.payment_method ?? "—"}</dd>
              <dt>Contraparte</dt><dd>{t.counterparty_name ?? t.merchant_name ?? "—"} <span className="muted">{t.counterparty_doc ?? t.merchant_cnpj ?? ""}</span></dd>
              {t.total_installments > 1 && <><dt>Parcela</dt><dd>{t.installment_number}/{t.total_installments}</dd></>}
              <dt>ID original</dt><dd className="small">{t.id}</dd>
              <dt>Coletado</dt><dd>{dateTime(t.first_seen_at)} · visto {dateTime(t.last_seen_at)}</dd>
              <dt>Versões brutas</dt><dd>{d.provenance.raw_versions.length}</dd>
            </dl>
          </section>
          {d.audit.length > 0 && (
            <section>
              <h4 style={{ margin: "0 0 8px" }}>Histórico</h4>
              {d.audit.map((a: any, i: number) => (
                <div key={i} className="list-row"><div className="grow"><div className="t">{a.field}: {a.old ?? "—"} → {a.new}</div>
                  <div className="s">{dateTime(a.at)} por {a.actor === "user" ? "você" : "sistema"} ({a.reason})</div></div></div>
              ))}
            </section>
          )}
          <details><summary className="soft">Payload bruto da Pluggy</summary><pre className="json">{JSON.stringify(d.raw_payload, null, 2)}</pre></details>
        </>
      )}
    </Drawer>
  );
}
