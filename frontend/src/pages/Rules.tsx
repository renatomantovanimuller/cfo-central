import { useQuery } from "@tanstack/react-query";
import { useApiMutation } from "../hooks/useApiMutation";
import { QueryState } from "../components/QueryState";
import { IntInput, MoneyInput } from "../components/MoneyInput";
import { parseIntStrict, validateNumber } from "../format";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Trash2 } from "lucide-react";
import { api } from "../api";
import { CategorySelect, Chip, EventTypeSelect, Money, Panel, useToast } from "../components/ui";
import { date, EVENT_LABELS } from "../format";

const FIELDS: Record<string, string> = { description: "Descrição", merchant: "Nome do comerciante/contraparte", merchant_id: "Comerciante (nº do cadastro)",
  cnpj: "CNPJ/CPF da contraparte", pluggy_category: "Categoria Pluggy (código)", mcc: "MCC do cartão", account: "Conta (id)" };
const OPS: Record<string, string> = { contains: "contém", equals: "é igual a", starts: "começa com", regex: "regex" };

export default function Rules() {
  const [sp] = useSearchParams();
  const blank = { field: sp.get("field") ?? "description", operator: "contains", pattern: sp.get("pattern") ?? "",
    category_id: sp.get("category") ?? "", event_type: "", direction: "", priority: 100, amount_min: "", amount_max: "" };
  const [f, setF] = useState<any>(blank);
  const [preview, setPreview] = useState<any>(null);
  const rules = useQuery({ queryKey: ["rules"], queryFn: () => api<any[]>("/api/rules") });
  const vMin = validateNumber(f.amount_min, { allowNegative: false });
  const vMax = validateNumber(f.amount_max, { allowNegative: false });
  const vPri = validateNumber(String(f.priority), { required: true }, parseIntStrict);
  const invalid = !!(vMin.error || vMax.error || vPri.error);
  const body = () => ({ ...f, category_id: f.category_id || null, event_type: f.event_type || null, direction: f.direction || null,
    amount_min: vMin.value, amount_max: vMax.value, priority: vPri.value ?? 100 });
  useEffect(() => {
    if (invalid || !f.pattern || !(f.category_id || f.event_type)) { setPreview(null); return; }
    const h = setTimeout(() => api("/api/rules/preview", { method: "POST", body: body() }).then(setPreview).catch(() => setPreview(null)), 350);
    return () => clearTimeout(h);
  }, [JSON.stringify(f)]);
  const create = useApiMutation({
    mutationFn: () => api<any>("/api/rules", { method: "POST", body: body() }),
    successMessage: (r) => `Regra criada. ${r.changed} lançamentos reclassificados`,
    invalidate: "all",
    onSuccess: () => setF({ ...blank, pattern: "" }),
  });
  const del = useApiMutation({
    mutationFn: (id: number) => api(`/api/rules/${id}`, { method: "DELETE" }),
    successMessage: "Regra removida",
    invalidate: "all",
  });
  const [toDelete, setToDelete] = useState<any>(null);
  const set = (k: string) => (v: any) => setF((x: any) => ({ ...x, [k]: v?.target ? v.target.value : v }));
  return (
    <>
      {toDelete && (
        <ConfirmDialog title="Excluir esta regra?" itemName={`${FIELDS[toDelete.field] ?? toDelete.field} ${OPS[toDelete.operator]} “${toDelete.pattern}”`}
          confirmLabel="Excluir regra" danger onCancel={() => setToDelete(null)}
          onConfirm={() => { del.mutate(toDelete.id); setToDelete(null); }}>Os lançamentos serão reclassificados sem ela.</ConfirmDialog>
      )}
      <Panel title="Nova regra" hint="regras vencem categorias automáticas e conciliação; ajustes manuais vencem regras">
        <div className="toolbar">
          <select className="select" value={f.field} onChange={set("field")}>{Object.entries(FIELDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          <select className="select" value={f.operator} onChange={set("operator")}>{Object.entries(OPS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          <input className="input" style={{ flex: "1 1 220px" }} placeholder="texto, documento ou expressão" value={f.pattern} onChange={set("pattern")} />
        </div>
        <div className="toolbar" style={{ marginTop: 8 }}>
          <CategorySelect value={f.category_id} onChange={set("category_id")} placeholder="Categoria (opcional)" />
          <EventTypeSelect value={f.event_type} onChange={set("event_type")} placeholder="Tipo de evento (opcional)" />
          <select className="select" value={f.direction} onChange={set("direction")}>
            <option value="">entradas e saídas</option><option value="out">só saídas</option><option value="in">só entradas</option></select>
          <MoneyInput width={100} placeholder="valor mín." ariaLabel="Valor mínimo" allowNegative={false} value={f.amount_min} onChange={set("amount_min")} />
          <MoneyInput width={100} placeholder="valor máx." ariaLabel="Valor máximo" allowNegative={false} value={f.amount_max} onChange={set("amount_max")} />
          <label className="field" style={{ gridAutoFlow: "column", alignItems: "center" }}>Prioridade
            <IntInput width={70} required value={String(f.priority)} onChange={set("priority")} /></label>
          <button className="btn primary" disabled={invalid || !f.pattern || !(f.category_id || f.event_type) || create.isPending} onClick={() => create.mutate()}>Criar regra</button>
        </div>
        {preview && (
          <div style={{ marginTop: 12 }}>
            <p className="soft small">Afeta <strong>{preview.count}</strong> lançamentos (soma <Money v={preview.total} />).</p>
            {preview.sample.slice(0, 8).map((s: any) => (
              <div key={s.id} className="list-row"><span className="soft num" style={{ width: 80, textAlign: "left" }}>{date(s.date)}</span>
                <div className="grow t">{s.description}</div><Money v={s.amount} /></div>))}
          </div>
        )}
      </Panel>
      {!rules.data ? <QueryState q={rules} what="as regras" layout="panel">{() => null}</QueryState> : <Panel title={`${rules.data.length} regras`} flush>
        <table className="table">
          <thead><tr><th>Prioridade</th><th>Condição</th><th>Resultado</th><th className="num">Aplicações</th><th>Origem</th><th /></tr></thead>
          <tbody>
            {(rules.data ?? []).map((r) => (
              <tr key={r.id}>
                <td className="num" style={{ textAlign: "left" }}>{r.priority}</td>
                <td>{FIELDS[r.field] ?? r.field} {OPS[r.operator]} <strong>“{r.pattern}”</strong>
                  {r.direction && <span className="soft"> ({r.direction === "in" ? "entradas" : "saídas"})</span>}
                  {(r.amount_min || r.amount_max) && <span className="soft"> entre {r.amount_min ?? 0} e {r.amount_max ?? "∞"}</span>}</td>
                <td>{r.category ?? ""} {r.event_type && <Chip tone="blue">{EVENT_LABELS[r.event_type]}</Chip>}</td>
                <td className="num">{r.hits}</td>
                <td><Chip tone={r.origin === "user" ? "green" : undefined}>{r.origin === "user" ? "você" : r.origin}</Chip></td>
                <td><button className="btn ghost sm danger" onClick={() => setToDelete(r)} aria-label="Remover regra"><Trash2 size={14} /></button></td>
              </tr>
            ))}
            {rules.data?.length === 0 && <tr><td colSpan={6} className="muted" style={{ padding: 18 }}>Nenhuma regra ainda. Crie a partir de um lançamento (ícone de varinha no razão) ou acima.</td></tr>}
          </tbody>
        </table>
      </Panel>}
    </>
  );
}
