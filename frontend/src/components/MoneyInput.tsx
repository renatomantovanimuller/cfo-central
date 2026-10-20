import { ReactNode, useEffect, useState } from "react";
import { formatInputNumber, NumberRules, parseBRL, parseIntStrict, validateNumber } from "../format";
import { useApiMutation } from "../hooks/useApiMutation";

type Parse = (s: string) => number | null;

type FieldProps = NumberRules & {
  value: string;
  onChange: (raw: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  width?: number;
  disabled?: boolean;
};

function NumericField({ parse, ...p }: FieldProps & { parse: Parse }) {
  const [touched, setTouched] = useState(false);
  const { error } = validateNumber(p.value, p, parse);
  const show = error && (p.value.trim() !== "" || touched);
  return (
    <span className="money-field">
      <input className={`input num ${show ? "invalid" : ""}`} style={{ width: p.width ?? 120 }} inputMode="decimal"
        value={p.value} placeholder={p.placeholder} aria-label={p.ariaLabel} disabled={p.disabled}
        aria-invalid={!!show} onChange={(e) => p.onChange(e.target.value)} onBlur={() => setTouched(true)} />
      {show && <span className="field-error" role="alert">{error}</span>}
    </span>
  );
}

/** Campo de dinheiro (pt-BR). Use `validateNumber(raw, rules)` no pai para bloquear o envio. */
export const MoneyInput = (p: FieldProps) => <NumericField parse={parseBRL} {...p} />;
/** Percentual ou número decimal (aceita vírgula). */
export const NumberInput = (p: FieldProps) => <NumericField parse={parseBRL} {...p} />;
/** Inteiro sem sinal. */
export const IntInput = (p: FieldProps) => <NumericField parse={parseIntStrict} {...p} />;

/* ---------- salvamento inline (onBlur) ---------- */
export type SaveStatus = "idle" | "saving" | "saved" | "error";

export function SaveBadge({ status }: { status: SaveStatus }) {
  const text = status === "saving" ? "salvando…" : status === "saved" ? "salvo ✓" : status === "error" ? "erro ao salvar" : "";
  return <span className={`save-badge ${status}`} aria-live="polite">{text}</span>;
}

function useAutoSave<V>(save: (v: V) => Promise<unknown>, successMessage?: string, onFail?: () => void) {
  const [saved, setSaved] = useState(false);
  const m = useApiMutation<unknown, V>({
    mutationFn: save, successMessage, invalidate: "all", errorPrefix: "Não foi possível salvar",
    onSuccess: () => { setSaved(true); window.setTimeout(() => setSaved(false), 2000); },
    onError: () => { setSaved(false); onFail?.(); },
  });
  const status: SaveStatus = m.isPending ? "saving" : m.isError ? "error" : saved ? "saved" : "idle";
  return { run: m.mutate, status };
}

/** Dinheiro que salva ao sair do campo; valor inválido não é enviado; erro restaura o valor anterior. */
export function AutoSaveMoney({ value, onSave, placeholder, ariaLabel, width = 110 }:
  { value: number | null; onSave: (v: number | null) => Promise<unknown>; placeholder?: string; ariaLabel?: string; width?: number }) {
  const [raw, setRaw] = useState(formatInputNumber(value));
  useEffect(() => setRaw(formatInputNumber(value)), [value]);
  const { run, status } = useAutoSave<number | null>(onSave, undefined, () => setRaw(formatInputNumber(value)));
  const { value: parsed, error } = validateNumber(raw, { allowNegative: false });
  const commit = () => { if (!error && parsed !== value) run(parsed); };
  return (
    <span className="autosave">
      <span className="money-field">
        <input className={`input num ${error ? "invalid" : ""}`} style={{ width, height: 28 }} inputMode="decimal" value={raw}
          placeholder={placeholder} aria-label={ariaLabel} aria-invalid={!!error}
          onChange={(e) => setRaw(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
        {error && <span className="field-error" role="alert">{error}</span>}
      </span>
      <SaveBadge status={status} />
    </span>
  );
}

export function AutoSaveText({ value, onSave, placeholder, width, ariaLabel }:
  { value: string; onSave: (v: string) => Promise<unknown>; placeholder?: string; width?: number; ariaLabel?: string }) {
  const [raw, setRaw] = useState(value);
  useEffect(() => setRaw(value), [value]);
  const { run, status } = useAutoSave<string>(onSave, undefined, () => setRaw(value));
  return (
    <span className="autosave">
      <input className="input" style={width ? { width } : undefined} value={raw} placeholder={placeholder} aria-label={ariaLabel}
        onChange={(e) => setRaw(e.target.value)} onBlur={() => raw !== value && run(raw)} />
      <SaveBadge status={status} />
    </span>
  );
}

export function AutoSaveSelect({ value, onSave, children, successMessage }:
  { value: string; onSave: (v: string) => Promise<unknown>; children: ReactNode; successMessage?: string }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const { run, status } = useAutoSave<string>(onSave, successMessage, () => setV(value));
  return (
    <span className="autosave">
      <select className="select" value={v} onChange={(e) => { setV(e.target.value); run(e.target.value); }}>{children}</select>
      <SaveBadge status={status} />
    </span>
  );
}

export function AutoSaveCheck({ checked, onSave, ariaLabel, successMessage }:
  { checked: boolean; onSave: (v: boolean) => Promise<unknown>; ariaLabel: string; successMessage?: string }) {
  const [v, setV] = useState(checked);
  useEffect(() => setV(checked), [checked]);
  const { run, status } = useAutoSave<boolean>(onSave, successMessage, () => setV(checked));
  return (
    <span className="autosave">
      <input type="checkbox" checked={v} aria-label={ariaLabel} onChange={(e) => { setV(e.target.checked); run(e.target.checked); }} />
      <SaveBadge status={status} />
    </span>
  );
}
