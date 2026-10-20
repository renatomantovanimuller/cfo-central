import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

export type Onboarding = {
  pluggy_configured: boolean; email_configured: boolean; items: number; events: number; budgets: number; plan_set: boolean;
  recurring_confirmed: number; income_unclassified: number; income_unclassified_share: number; sync: { running?: boolean; step?: string };
};

/** Estado da configuração inicial (o que falta para os números ficarem confiáveis). */
export const useOnboarding = () =>
  useQuery({ queryKey: ["onboarding"], queryFn: () => api<Onboarding>("/api/onboarding"), staleTime: 10_000, refetchInterval: 60_000 });

/** Receita "a classificar" acima deste peso deixa os resultados provisórios. */
export const PROVISIONAL_SHARE = 0.3;
