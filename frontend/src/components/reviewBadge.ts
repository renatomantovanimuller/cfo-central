const ACTIONABLE_KINDS = new Set(["low_confidence", "uncategorized", "recurring_income", "duplicate", "exit_no_counterpart"]);

type ReviewLike = { kind?: string; severity?: string; entity_type?: string; entity_id?: string | number; data?: any };

/** O item exige uma decisão do usuário: classificação pendente (pix_*, baixa confiança...) ou severidade alta. */
export const isActionableReview = (r: ReviewLike) =>
  r.severity === "high" || !!r.kind && (r.kind.startsWith("pix_") || ACTIONABLE_KINDS.has(r.kind));

/** Decisão de classificação (resolvida com um clique), em oposição a avisos do sistema. */
export const isDecision = (r: ReviewLike) =>
  !!r.kind && (r.kind.startsWith("pix_") || ACTIONABLE_KINDS.has(r.kind));

/**
 * Junta itens que falam da mesma contraparte: "Receita recorrente: ACME… É salário?" e "Recebimento a classificar: ACME"
 * pedem a mesma decisão. Fica o item de receita recorrente, que leva o grupo de lançamentos em `merged`.
 */
export function dedupeReviews<T extends ReviewLike>(items: T[] | undefined): (T & { merged?: T })[] {
  const list = items ?? [];
  const recurringByMerchant = new Map<string, T>();
  list.forEach((r) => { if (r.kind === "recurring_income" && r.data?.merchant_id != null) recurringByMerchant.set(String(r.data.merchant_id), r); });
  const absorbed = new Map<T, T>();
  const out = list.filter((r) => {
    if (r.kind === "recurring_income" || r.entity_type !== "merchant") return true;
    const rec = recurringByMerchant.get(String(r.entity_id));
    if (!rec) return true;
    absorbed.set(rec, r);
    return false;
  });
  return out.map((r) => (absorbed.has(r) ? { ...r, merged: absorbed.get(r) } : r));
}

export const actionableReviewCount = (items: ReviewLike[] | undefined) => reviewSummary(items).pending;

/**
 * Resumo único usado no menu, no Painel e na própria Revisão, para os números baterem.
 * `pending` = decisões que só você pode tomar (classificar); `notices` = avisos do sistema, dos quais `urgent` são de severidade alta.
 */
export function reviewSummary(items: ReviewLike[] | undefined) {
  const all = dedupeReviews(items);
  const pending = all.filter(isDecision).length;
  const urgent = all.filter((r) => !isDecision(r) && r.severity === "high").length;
  return { total: all.length, pending, notices: all.length - pending, urgent };
}
