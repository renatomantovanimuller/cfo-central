import { brl, compact } from "../format";
import { MASK, usePrivacy } from "../privacy";

export type MoneyTone = "favorable" | "unfavorable" | "neutral";

/** Valor em BRL. `tone` define a cor por favorabilidade (não pelo sinal). Respeita o modo privacidade. */
/** Tom por favorabilidade do sinal (ganho verde, perda vermelha) para resultados, nunca para despesas. */
export const signTone = (v: number | null | undefined): MoneyTone =>
  v === null || v === undefined || v === 0 ? "neutral" : v > 0 ? "favorable" : "unfavorable";

export function MoneyText({ value, digits = 2, tone = "neutral", className = "", short = false }:
  { value: number | null | undefined; digits?: number; tone?: MoneyTone; className?: string; short?: boolean }) {
  const hidden = usePrivacy();
  const t = tone === "neutral" ? "" : `tone-${tone}`;
  const text = hidden ? MASK : short ? compact(value) : brl(value, digits);
  return <span className={`num ${t} ${className}`.trim()}>{text}</span>;
}
