import { isPrivate, MASK } from "./privacy";
const nf = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const nf0 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });

/** R$ 1.234,56 / −R$ 1.234,56 */
export const brl = (v: number | null | undefined, digits = 2) =>
  isPrivate() ? MASK : v === null || v === undefined || Number.isNaN(v) ? "—" :
  `${v < 0 ? "−" : ""}R$ ${(digits === 0 ? nf0 : nf).format(Math.abs(v))}`;

/** Convenção contábil para demonstrativos: negativos entre parênteses, sem símbolo. */
export const acct = (v: number | null | undefined) =>
  isPrivate() ? MASK : v === null || v === undefined ? "—" : Math.abs(v) < 0.005 ? "–" : v < 0 ? `(${nf.format(-v)})` : nf.format(v);

export const compact = (v: number | null | undefined) => {
  if (isPrivate()) return MASK;
  if (v === null || v === undefined) return "—";
  const a = Math.abs(v);
  const s = a >= 1e6 ? `${(a / 1e6).toFixed(1).replace(".", ",")} mi` : a >= 1e3 ? `${(a / 1e3).toFixed(1).replace(".", ",")} mil` : nf0.format(a);
  return `${v < 0 ? "−" : ""}R$ ${s}`;
};

export const pct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(digits).replace(".", ",")}%`;

export const date = (d: string | null | undefined) => (d ? d.slice(0, 10).split("-").reverse().join("/") : "—");
export const dateTime = (d: string | null | undefined) => (d ? new Date(d).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—");

const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
export const monthLabel = (ym: string, withYear = true) => {
  const [y, m] = ym.split("-");
  return withYear ? `${MONTHS[+m - 1]}/${y.slice(2)}` : MONTHS[+m - 1];
};
/** Rótulo de eixo: o mês corrente (incompleto) ganha "(parcial)". */
export const monthAxisLabel = (ym: string) => (ym === thisMonth() ? `${monthLabel(ym)} (parcial)` : monthLabel(ym));
export const PARTIAL_OPACITY = 0.5;
export const isPartialMonth = (ym: string) => ym === thisMonth();
export const monthLong = (ym: string) => {
  const [y, m] = ym.split("-");
  const names = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
  return `${names[+m - 1]} de ${y}`;
};
export const thisMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
export const addMonth = (ym: string, n: number) => {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m - 1 + n, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
export const signClass = (v: number | null | undefined) => (v === null || v === undefined ? "" : v < 0 ? "neg" : "");

export const EVENT_LABELS: Record<string, string> = {
  INCOME: "Receita", INVESTMENT_INCOME: "Receita financeira", EXPENSE: "Despesa", FINANCIAL_EXPENSE: "Despesa financeira",
  TAX: "Imposto", REFUND: "Estorno/reembolso", INTERNAL_TRANSFER: "Transferência interna",
  EXTERNAL_OWN_TRANSFER: "Conta própria não conectada", CARD_PAYMENT: "Pagamento de fatura", INVESTMENT_CONTRIBUTION: "Aporte",
  INVESTMENT_REDEMPTION: "Resgate", LOAN_IN: "Empréstimo recebido", LOAN_PAYMENT: "Parcela de empréstimo", IGNORE: "Ignorar",
};
export const RULE_SOURCE: Record<string, string> = {
  manual: "ajuste manual", rule: "sua regra", structural: "conciliação", merchant: "comerciante aprendido",
  pluggy_map: "categoria Pluggy", heuristic: "palavra-chave", default: "sem regra", modelo: "classificador treinado",
};

/* ---------- entrada de valores (pt-BR) ---------- */

const MAX_DIGITS = 15;
const GROUPED_DOT = /^\d{1,3}(\.\d{3})+$/;
const GROUPED_COMMA = /^\d{1,3}(,\d{3})+$/;

/**
 * Interpreta um valor monetário digitado pelo usuário e devolve um número com 2 casas,
 * ou `null` se for vazio ou inválido.
 *
 * Aceita: "1.234,56", "1234,56", "1234.56", "1,234.56", "R$ 1.234", "-50", "−50", "(50)", "1.234" (= 1234), "0,5".
 * Regra do ponto sozinho: "1.234" (grupo de exatamente 3 dígitos, sem zero à esquerda) é milhar;
 * "1234.56" e "0.5" são decimais. Mais de 2 casas decimais, lixo e separadores mal posicionados são rejeitados.
 */
export function parseBRL(input: string | number | null | undefined): number | null {
  if (typeof input === "number") return Number.isFinite(input) ? input : null;
  if (typeof input !== "string") return null;
  let s = input.replace(/[\s\u00a0]/g, "");
  let negative = false;
  let signed = negative;
  const takeSign = () => { if (!signed && /^[-−–]/.test(s)) { negative = signed = true; s = s.slice(1); } };
  if (/^\(.*\)$/.test(s)) { negative = true; s = s.slice(1, -1); }
  takeSign();
  s = s.replace(/^R\$/i, "");
  takeSign();
  if (s.startsWith("+")) s = s.slice(1);
  if (/^,\d{1,2}$/.test(s)) s = `0${s}`;
  if (!/^\d[\d.,]*$/.test(s) || s.replace(/\D/g, "").length > MAX_DIGITS) return null;

  let intPart = s;
  let decPart = "";
  const hasDot = s.includes(".");
  const hasComma = s.includes(",");
  if (hasDot && hasComma) {
    const decSep = s.lastIndexOf(",") > s.lastIndexOf(".") ? "," : ".";
    const thouSep = decSep === "," ? "." : ",";
    const idx = s.lastIndexOf(decSep);
    if (s.indexOf(decSep) !== idx) return null;
    intPart = s.slice(0, idx);
    decPart = s.slice(idx + 1);
    if (!(thouSep === "." ? GROUPED_DOT : GROUPED_COMMA).test(intPart)) return null;
    intPart = intPart.split(thouSep).join("");
    if (decPart === "") return null;
  } else if (hasComma) {
    const parts = s.split(",");
    if (parts.length > 2 || parts[1] === "") return null;
    [intPart, decPart = ""] = parts;
  } else if (hasDot) {
    const parts = s.split(".");
    if (parts.length > 2) {
      if (!GROUPED_DOT.test(s)) return null;
      intPart = parts.join("");
    } else {
      const [a, b] = parts;
      if (b === "") return null;
      if (/^[1-9]\d{0,2}$/.test(a) && b.length === 3) intPart = a + b; // "1.234" = 1234
      else { intPart = a; decPart = b; }
    }
  }
  if (!/^\d+$/.test(intPart) || decPart.length > 2 || (decPart !== "" && !/^\d+$/.test(decPart))) return null;
  const abs = Math.round(Number(`${intPart}.${decPart || "0"}`) * 100) / 100;
  return (negative ? -abs : abs) + 0; // "+ 0" evita -0
}

/** Inteiro sem sinal (ex.: prioridade de regra). Devolve `null` se vazio ou inválido. */
export function parseIntStrict(input: string | number | null | undefined): number | null {
  const s = typeof input === "number" ? String(input) : (input ?? "").trim();
  return /^\d{1,9}$/.test(s) ? parseInt(s, 10) : null;
}

export type NumberCheck = { value: number | null; error: string | null };
export type NumberRules = { required?: boolean; min?: number; max?: number; allowNegative?: boolean; fmt?: (n: number) => string };

/** Valida um campo numérico em texto. `error` é uma mensagem pronta para a interface. */
export function validateNumber(raw: string, rules: NumberRules = {}, parse: (s: string) => number | null = parseBRL): NumberCheck {
  const { required = false, min, max, allowNegative = true, fmt = (n) => nf.format(n) } = rules;
  if (raw.trim() === "") return { value: null, error: required ? "Informe um valor." : null };
  const value = parse(raw);
  if (value === null) return { value: null, error: "Valor inválido. Use o formato 1.234,56." };
  if (!allowNegative && value < 0) return { value: null, error: "O valor não pode ser negativo." };
  if (min !== undefined && value < min) return { value: null, error: `O valor mínimo é ${fmt(min)}.` };
  if (max !== undefined && value > max) return { value: null, error: `O valor máximo é ${fmt(max)}.` };
  return { value, error: null };
}

/** Texto de edição para um número (sem símbolo): 1234.5 → "1.234,50"; 1234 → "1.234". */
export const formatInputNumber = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(v) ? "" :
  v.toLocaleString("pt-BR", { minimumFractionDigits: Number.isInteger(v) ? 0 : 2, maximumFractionDigits: 2 });

/* ---------- nomes de comerciantes e contrapartes ---------- */

const KEEP_UPPER = new Set(["S.A.", "SA", "S/A", "LTDA", "ME", "EPP", "EIRELI", "CDB", "LCI", "LCA", "CDI", "FII", "ETF", "IPCA", "PIX",
  "TED", "DOC", "IOF", "IR", "BB", "XP", "BTG", "C6", "CPFL", "CEMIG", "SABESP", "IPVA", "IPTU", "DARF", "INSS", "FGTS", "MEI", "PJ", "PF"]);
const LOWER = new Set(["de", "da", "do", "das", "dos", "e", "em", "a", "o", "para", "por", "com"]);
// prefixos de adquirentes/gateways que aparecem no extrato antes do nome real: "IFD*RESTAURANTE", "PG *LOJA", "MP*VENDEDOR"
const GATEWAY = /^(ifd|pg|mp|pag|ppro|ebn|dl|ec|pagseguro|mercadopago|sumup|stone|cielo)\s*\*\s*/i;

/**
 * Nome legível para exibição: tira prefixos de gateway ("Ifd*", "PG *"), troca "*" solto por espaço e converte
 * TUDO MAIÚSCULO em Título ("IMOBILIARIA CENTRO" → "Imobiliaria Centro"), mantendo siglas (LTDA, S.A., CDB).
 * Nomes que já vêm com caixa mista ficam como estão. O original continua disponível (use como `title`).
 */
export function prettyName(raw: string | null | undefined): string {
  if (!raw) return "";
  let s = raw.trim().replace(GATEWAY, "").replace(/\s*\*\s*/g, " ").replace(/\s{2,}/g, " ");
  const letters = s.replace(/[^A-Za-zÀ-ÿ]/g, "");
  if (letters.length > 3 && letters === letters.toUpperCase()) {
    s = s.split(" ").map((w, i) => {
      const up = w.toUpperCase();
      if (KEEP_UPPER.has(up) || /\d/.test(w) && w.length <= 4) return up;
      const low = w.toLowerCase();
      if (i > 0 && LOWER.has(low)) return low;
      return low.charAt(0).toUpperCase() + low.slice(1);
    }).join(" ");
  }
  return s;
}
