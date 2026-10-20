import { describe, expect, it } from "vitest";
import { actionableReviewCount, dedupeReviews, isActionableReview, reviewSummary } from "./components/reviewBadge";

describe("badge de revisão", () => {
  it("conta classificação e severidade alta, ignora alertas de sistema", () => {
    expect(isActionableReview({ kind: "pix_unknown", severity: "info" })).toBe(true);
    expect(isActionableReview({ kind: "low_confidence", severity: "warn" })).toBe(true);
    expect(isActionableReview({ kind: "exit_no_counterpart", severity: "warn" })).toBe(true);
    expect(isActionableReview({ kind: "sync_stale", severity: "high" })).toBe(true);
    expect(isActionableReview({ kind: "sync_stale", severity: "warn" })).toBe(false);
  });
  it("devolve 0 sem dados", () => {
    expect(actionableReviewCount(undefined)).toBe(0);
    expect(actionableReviewCount([{ kind: "x", severity: "info" }, { kind: "duplicate" }])).toBe(1);
    expect(actionableReviewCount([{ kind: "sync_stale", severity: "high" }])).toBe(0); // aviso urgente não é decisão
  });
});

describe("revisão unificada", () => {
  const items = [
    { id: 1, kind: "recurring_income", severity: "warn", entity_type: "recurring", entity_id: "k", data: { merchant_id: 7 } },
    { id: 2, kind: "pix_in_unknown", severity: "info", entity_type: "merchant", entity_id: "7" },
    { id: 3, kind: "pix_in_unknown", severity: "info", entity_type: "merchant", entity_id: "8" },
    { id: 4, kind: "data_health", severity: "warn", entity_type: "health", entity_id: "x" },
  ];
  it("junta o grupo da mesma contraparte ao item de receita recorrente", () => {
    const d = dedupeReviews(items);
    expect(d.map((r) => r.id)).toEqual([1, 3, 4]);
    expect(d[0].merged?.id).toBe(2);
  });
  it("menu, painel e revisão usam a mesma contagem", () => {
    expect(reviewSummary(items)).toEqual({ total: 3, pending: 2, notices: 1, urgent: 0 });
    expect(actionableReviewCount(items)).toBe(2);
  });
});
