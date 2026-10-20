import { QueryState } from "../components/QueryState";
import { useQuery } from "@tanstack/react-query";
import { useApiMutation } from "../hooks/useApiMutation";
import { undoCategoryBody } from "../components/undoCategory";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Wand2 } from "lucide-react";
import { api, qs } from "../api";
import { EventDrawer } from "../components/EventDrawer";
import { useMonth } from "../components/Layout";
import { CategoryOptions, CategorySelect, Chip, Confidence, Empty, EventTypeSelect, Money, Panel, useCategories, useToast } from "../components/ui";
import { brl, date, EVENT_LABELS, monthLong, prettyName } from "../format";
import { Term } from "../components/Term";

const TONE: Record<string, any> = { INCOME: "green", INVESTMENT_INCOME: "green", EXPENSE: undefined, REFUND: "blue",
  CARD_PAYMENT: "blue", INTERNAL_TRANSFER: "blue", EXTERNAL_OWN_TRANSFER: "blue", INVESTMENT_CONTRIBUTION: "ochre",
  INVESTMENT_REDEMPTION: "ochre", FINANCIAL_EXPENSE: "red", TAX: "red" };

export default function Ledger() {
  const { month } = useMonth();
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const cats = useCategories();
  const [open, setOpen] = useState<string | null>(null);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(1);
  const [qText, setQText] = useState(sp.get("q") ?? "");
  const allMonths = sp.get("all") === "1";
  const filters = {
    month: allMonths ? undefined : (sp.get("month") ?? month), category: sp.get("category") ?? undefined,
    merchant: sp.get("merchant") ?? undefined, event_type: sp.get("event_type") ?? undefined,
    account: sp.get("account") ?? undefined, q: sp.get("q") ?? undefined, review: sp.get("review") ?? undefined,
    direction: sp.get("direction") ?? undefined,
  };
  useEffect(() => { setPage(1); setSel(new Set()); }, [sp.toString(), month]);
  useEffect(() => { if (sp.get("month") && sp.get("month") !== month) { sp.delete("month"); setSp(sp, { replace: true }); } }, [month]);
  const conns = useQuery({ queryKey: ["connections"], queryFn: () => api<any>("/api/connections") });
  const accounts = useMemo(() => (conns.data?.items ?? []).flatMap((i: any) => i.accounts.map((a: any) => ({ ...a, inst: i.institution }))), [conns.data]);
  const q = useQuery({ queryKey: ["events", filters, page], queryFn: () => api<any>(`/api/events${qs({ ...filters, page, page_size: 100 })}`) });

  const set = (k: string, v?: string | null) => { v ? sp.set(k, v) : sp.delete(k); setSp(sp, { replace: true }); };
  const patch = useApiMutation({
    mutationFn: ({ id, body }: { id: string; body: any; previous?: string | null }) => api<any>(`/api/events/${id}`, { method: "PATCH", body }),
    successMessage: (r, v) => (v.previous === undefined ? (r.changed > 1 ? `Salvo. ${r.changed} lançamentos do mesmo comerciante seguiram` : "Salvo")
      : `Categoria alterada${r.changed > 1 ? ` · ${r.changed} lançamentos do mesmo comerciante seguiram` : ""}`),
    successAction: (_r, v) => v.previous === undefined ? undefined
      : { label: "Desfazer", onClick: () => patch.mutate({ id: v.id, body: undoCategoryBody(v.previous) }) },
    invalidate: "all",
  });
  const bulk = useApiMutation({
    mutationFn: (body: any) => api<any>("/api/events/bulk", { method: "POST", body: { ids: [...sel], ...body } }),
    successMessage: (r) => `${r.updated} lançamentos atualizados`,
    invalidate: "all",
    onSuccess: () => setSel(new Set()),
  });

  const d = q.data;
  const pages = d ? Math.ceil(d.total / d.page_size) : 1;
  const toggle = (id: string) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const activeChips = [
    filters.category && ["category", `Categoria: ${cats.data?.find((c) => c.id === filters.category)?.name ?? filters.category}`],
    filters.merchant && ["merchant", "Comerciante selecionado"],
    filters.review && ["review", "Só a revisar"],
  ].filter(Boolean) as [string, string][];

  return (
    <>
      <Panel>
        <div className="toolbar">
          <input className="input" style={{ flex: "1 1 240px" }} placeholder="Buscar descrição, contraparte ou nota" value={qText}
            onChange={(e) => setQText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && set("q", qText)} onBlur={() => set("q", qText)} />
          <select className="select" value={filters.account ?? ""} onChange={(e) => set("account", e.target.value)}>
            <option value="">Todas as contas</option>
            {accounts.map((a: any) => <option key={a.id} value={a.id}>{a.nickname ?? a.name} ({a.inst})</option>)}
          </select>
          <select className="select" value={filters.category ?? ""} onChange={(e) => set("category", e.target.value)}>
            <option value="">Todas as categorias</option>
            {cats.data && <CategoryOptions cats={cats.data} />}
          </select>
          <EventTypeSelect value={filters.event_type ?? ""} placeholder="Todos os tipos" onChange={(v) => set("event_type", v)} />
          <div className="segmented">
            {[["", "Tudo"], ["out", "Saídas"], ["in", "Entradas"]].map(([v, l]) => (
              <button key={v} className={(filters.direction ?? "") === v ? "on" : ""} onClick={() => set("direction", v)}>{l}</button>))}
          </div>
          <label className="soft small" style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={allMonths} onChange={(e) => set("all", e.target.checked ? "1" : "")} /> todos os meses</label>
          <label className="soft small" style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={!!filters.review} onChange={(e) => set("review", e.target.checked ? "true" : "")} /> só a revisar</label>
        </div>
        {activeChips.length > 0 && <div className="toolbar" style={{ marginTop: 10 }}>
          {activeChips.map(([k, l]) => <button key={k} className="chip green" style={{ border: 0, cursor: "pointer" }} onClick={() => set(k)}>{l} ✕</button>)}
        </div>}
      </Panel>

      <Panel flush title={`${d?.total ?? "…"} lançamentos`} hint={allMonths ? "todos os meses" : monthLong(filters.month!)}
        tools={d && <span className="small soft">Entradas <span className="num pos">{brl(d.inflow)}</span>  Saídas <span className="num">{brl(d.outflow)}</span></span>}>
        {sel.size > 0 && (
          <div className="toolbar" style={{ padding: "0 18px 10px" }}>
            <strong>{sel.size} selecionados</strong>
            <CategorySelect placeholder="Mover para categoria…" onChange={(v) => v && bulk.mutate({ category_id: v, learn: false })} />
            <EventTypeSelect placeholder="Definir tipo…" onChange={(v) => v && bulk.mutate({ event_type: v, learn: false })} />
            <button className="btn sm" onClick={() => setSel(new Set())}>Limpar seleção</button>
          </div>
        )}
        {!d ? <QueryState q={q} what="os lançamentos" layout="panel">{() => null}</QueryState> : d.items.length === 0 ? <Empty title="Nenhum lançamento com esses filtros">Tente outro mês ou marque “todos os meses”.</Empty> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr>
                <th style={{ width: 28 }} className="hide-sm"><input type="checkbox" aria-label="Selecionar página"
                  checked={!!d && d.items.length > 0 && d.items.every((r: any) => sel.has(r.id))}
                  onChange={(e) => setSel(e.target.checked ? new Set(d.items.map((r: any) => r.id)) : new Set())} /></th>
                <th>Data</th><th>Descrição</th><th className="hide-sm">Conta</th><th className="hide-sm">Categoria</th><th className="hide-sm">Tipo</th><th className="hide-sm"><Term k="confianca">Confiança</Term></th><th className="num">Valor</th><th className="hide-sm" />
              </tr></thead>
              <tbody>
                {d?.items.map((r: any) => (
                  <tr key={r.id} className="clickable" onClick={() => setOpen(r.id)} style={{ opacity: r.is_removed ? .5 : 1 }}>
                    <td className="hide-sm" onClick={(e) => e.stopPropagation()}><input type="checkbox" checked={sel.has(r.id)} onChange={() => toggle(r.id)} aria-label="Selecionar" /></td>
                    <td className="num" style={{ textAlign: "left" }}>{date(r.date)}</td>
                    <td className="desc"><div title={r.description ?? undefined}>{prettyName((r.description ?? "").split("|")[0])} {r.installment && <Chip>{r.installment}</Chip>} {r.is_pending && <Chip tone="ochre">pendente</Chip>} {r.needs_review && <Chip tone="ochre">revisar</Chip>}</div>
                      <div className="s" title={r.counterparty ?? undefined}>{r.counterparty ? prettyName(r.counterparty) : (r.description ?? "").split("|")[1] ?? ""}{r.note ? `; ${r.note}` : ""}</div>
                      <div className="s show-sm">{r.category ?? "sem categoria"}</div></td>
                    <td className="soft hide-sm" style={{ whiteSpace: "nowrap" }}>{r.account}</td>
                    <td className="hide-sm" onClick={(e) => e.stopPropagation()}>
                      <select className="select inline" value={r.category_id ?? ""} onChange={(e) => patch.mutate({ id: r.id, previous: r.category_id ?? null, body: { category_id: e.target.value, learn: true } })}>
                        {cats.data && <CategoryOptions cats={cats.data} />}
                      </select></td>
                    <td className="hide-sm"><Chip tone={TONE[r.event_type]}>{EVENT_LABELS[r.event_type]}</Chip></td>
                    <td className="hide-sm"><Confidence v={r.confidence} /></td>
                    <td><Money v={r.amount} tone={r.amount > 0 ? "favorable" : "neutral"} /></td>
                    <td className="hide-sm" onClick={(e) => e.stopPropagation()}>
                      <button className="btn ghost sm" title="Criar regra a partir deste lançamento"
                        onClick={() => nav(`/regras?pattern=${encodeURIComponent(r.counterparty || r.description)}&category=${r.category_id ?? ""}&field=${r.counterparty ? "merchant" : "description"}`)}><Wand2 size={14} /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {pages > 1 && (
          <div className="toolbar" style={{ justifyContent: "center", padding: 12 }}>
            <button className="btn sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Anterior</button>
            <span className="soft small">página {page} de {pages}</span>
            <button className="btn sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Próxima</button>
          </div>
        )}
      </Panel>
      {open && <EventDrawer id={open} onClose={() => setOpen(null)} />}
    </>
  );
}
