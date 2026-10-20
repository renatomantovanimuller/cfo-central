import { ReactNode, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api } from "../api";
import { brl, EVENT_LABELS } from "../format";
import { MoneyText, type MoneyTone } from "./MoneyText";

export function Panel(props: { title?: ReactNode; hint?: ReactNode; tools?: ReactNode; children: ReactNode; flush?: boolean; className?: string }) {
  return (
    <section className={`panel ${props.className ?? ""}`}>
      {(props.title || props.tools) && (
        <div className="panel-head">
          {props.title && <h2>{props.title}</h2>}
          {props.hint && <span className="hint">{props.hint}</span>}
          {props.tools && <div className="tools">{props.tools}</div>}
        </div>
      )}
      <div className={`panel-body ${props.flush ? "flush" : ""}`}>{props.children}</div>
    </section>
  );
}

/** Valores neutros por padrão; `tone` explícito define favorabilidade. `colored` mantém o uso antigo (vermelho só para negativos desfavoráveis). */
export const Money = ({ v, digits = 2, colored = false, tone }:
  { v: number | null | undefined; digits?: number; colored?: boolean; tone?: MoneyTone }) => (
  <MoneyText value={v} digits={digits}
    tone={tone ?? (colored && v !== null && v !== undefined && v < 0 ? "unfavorable" : "neutral")} />
);


export const Chip = ({ children, tone }: { children: ReactNode; tone?: "green" | "red" | "ochre" | "blue" }) => (
  <span className={`chip ${tone ?? ""}`}>{children}</span>
);

export const Confidence = ({ v }: { v: number }) => (
  <span className={`conf ${v < 0.6 ? "low" : ""}`} title={`confiança ${(v * 100).toFixed(0)}%`}><i style={{ width: `${Math.round(v * 100)}%` }} /></span>
);

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function Drawer({ title, onClose, children, actions }: { title: ReactNode; onClose: () => void; children: ReactNode; actions?: ReactNode }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true">
        <header>
          <div style={{ flex: 1, minWidth: 0 }}>{typeof title === "string" ? <h3>{title}</h3> : title}</div>
          {actions}
          <button className="btn ghost sm" onClick={onClose} aria-label="Fechar"><X size={16} /></button>
        </header>
        <div className="body">{children}</div>
      </aside>
    </>
  );
}

export { ToastProvider, useToast } from "./Toast";

/* ---------- seletores ---------- */
export type Cat = { id: string; parent_id: string | null; name: string; nature: string; dre_line: string | null; color: string | null; active: boolean };

export function useCategories() {
  return useQuery({ queryKey: ["categories-flat"], queryFn: () => api<Cat[]>("/api/categories/flat"), staleTime: 60_000 });
}

export function CategoryOptions({ cats, includePatrimonial = true }: { cats: Cat[]; includePatrimonial?: boolean }) {
  const roots = cats.filter((c) => !c.parent_id && c.active && (includePatrimonial || c.nature !== "patrimonial"));
  return (
    <>
      {roots.map((r) => (
        <optgroup key={r.id} label={r.name}>
          <option value={r.id}>{r.name}</option>
          {cats.filter((c) => c.parent_id === r.id && c.active).map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </optgroup>
      ))}
    </>
  );
}

export function CategorySelect({ value, onChange, className = "select", placeholder, includePatrimonial = true }:
  { value?: string | null; onChange: (v: string) => void; className?: string; placeholder?: string; includePatrimonial?: boolean }) {
  const { data = [] } = useCategories();
  return (
    <select className={className} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
      <option value="">{placeholder ?? "Categoria…"}</option>
      <CategoryOptions cats={data} includePatrimonial={includePatrimonial} />
    </select>
  );
}

export function EventTypeSelect({ value, onChange, className = "select", placeholder = "Tipo de evento…" }:
  { value?: string | null; onChange: (v: string) => void; className?: string; placeholder?: string }) {
  return (
    <select className={className} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
      <option value="">{placeholder}</option>
      {Object.entries(EVENT_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
    </select>
  );
}

export function Delta({ cur, ref_, invert = false }: { cur?: number | null; ref_?: number | null; invert?: boolean }) {
  if (cur === null || cur === undefined || !ref_) return null;
  const d = (cur - ref_) / Math.abs(ref_);
  const good = invert ? d < 0 : d > 0;
  return <span className={good ? "pos" : "neg"}>{d > 0 ? "+" : ""}{(d * 100).toFixed(0)}%</span>;
}

export const fmtBRL = brl;
