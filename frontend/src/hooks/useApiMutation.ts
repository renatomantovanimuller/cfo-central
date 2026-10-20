import { QueryKey, useMutation, useQueryClient } from "@tanstack/react-query";
import { ToastAction, useToast } from "../components/Toast";

export type ApiMutationOptions<TData, TVars> = {
  mutationFn: (vars: TVars) => Promise<TData>;
  /** Mensagem de sucesso (toast). Função que devolve `null` não mostra nada. */
  successMessage?: string | ((data: TData, vars: TVars) => string | null);
  /** Ação do toast de sucesso (ex.: Desfazer, que fica 6 s na tela). */
  successAction?: (data: TData, vars: TVars) => ToastAction | undefined;
  /** Prefixo da mensagem de erro, ex.: "Não foi possível salvar". A mensagem da API vem depois. */
  errorPrefix?: string;
  /** Consultas a invalidar no sucesso. "all" invalida tudo (padrão histórico do app). */
  invalidate?: QueryKey[] | "all";
  onSuccess?: (data: TData, vars: TVars) => void;
  onError?: (error: Error, vars: TVars) => void;
};

/** Texto do erro da API (ApiError já traz o `detail` do servidor). */
export const errorText = (e: unknown) => (e instanceof Error && e.message ? e.message : "Erro inesperado.");

/**
 * Envolve `useMutation` com o comportamento padrão do app: toast de erro com a mensagem da API,
 * toast de sucesso opcional e invalidação de consultas. Toda mutação do front deve passar por aqui.
 */
export function useApiMutation<TData = unknown, TVars = void>(opts: ApiMutationOptions<TData, TVars>) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation<TData, Error, TVars>({
    mutationFn: opts.mutationFn,
    onSuccess: (data, vars) => {
      const msg = typeof opts.successMessage === "function" ? opts.successMessage(data, vars) : opts.successMessage;
      if (msg) toast(msg, false, opts.successAction?.(data, vars));
      if (opts.invalidate === "all") qc.invalidateQueries();
      else opts.invalidate?.forEach((queryKey) => qc.invalidateQueries({ queryKey }));
      opts.onSuccess?.(data, vars);
    },
    onError: (error, vars) => {
      toast(opts.errorPrefix ? `${opts.errorPrefix}: ${errorText(error)}` : errorText(error), true);
      opts.onError?.(error, vars);
    },
  });
}
