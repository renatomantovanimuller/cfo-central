import { describe, expect, it } from "vitest";
import { actionableReviewCount, isActionableReview } from "./components/reviewBadge";

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
  });
});
