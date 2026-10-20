const ACTIONABLE_KINDS = new Set(["low_confidence", "uncategorized", "recurring_income", "duplicate", "exit_no_counterpart"]);

type ReviewLike = { kind?: string; severity?: string };

/** O item exige uma decisão do usuário: classificação pendente (pix_*, baixa confiança...) ou severidade alta. */
export const isActionableReview = (r: ReviewLike) =>
  r.severity === "high" || !!r.kind && (r.kind.startsWith("pix_") || ACTIONABLE_KINDS.has(r.kind));

export const actionableReviewCount = (items: ReviewLike[] | undefined) => (items ?? []).filter(isActionableReview).length;
