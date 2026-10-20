import { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { errorText } from "../hooks/useApiMutation";

export function Skeleton({ height = 14, width = "100%" }: { height?: number; width?: number | string }) {
  return <span className="skeleton" style={{ height, width }} aria-hidden />;
}

function SkeletonPanel({ lines = 4 }: { lines?: number }) {
  return (
    <div className="skeleton-panel">
      <Skeleton height={16} width="30%" />
      <div className="skeleton-lines">
        {Array.from({ length: lines }, (_, i) => <Skeleton key={i} width={`${100 - i * 9}%`} />)}
      </div>
    </div>
  );
}

type Props<T> = {
  q: UseQueryResult<T>;
  /** O que está sendo carregado, com artigo: "a DRE", "os lançamentos". */
  what: string;
  children: (data: T) => ReactNode;
  /** "page" (padrão) mostra vários painéis de esqueleto; "panel" só linhas. */
  layout?: "page" | "panel";
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
};

/** Loading (esqueleto), erro (mensagem + "Tentar de novo") e vazio, distintos entre si. */
export function QueryState<T>({ q, what, children, layout = "page", isEmpty, empty }: Props<T>) {
  if (q.data === undefined) {
    if (q.isError) {
      return (
        <div className="state-box error" role="alert">
          <h3>Não foi possível carregar {what}.</h3>
          <p>{errorText(q.error)}</p>
          <button className="btn" onClick={() => q.refetch()} disabled={q.isFetching}>
            {q.isFetching ? <span className="spinner sm" /> : null} Tentar de novo
          </button>
        </div>
      );
    }
    return layout === "panel" ? <SkeletonPanel /> : (
      <div className="skeleton-page" aria-busy="true" aria-label={`Carregando ${what}`}>
        <SkeletonPanel lines={2} /><SkeletonPanel /><SkeletonPanel lines={6} />
      </div>
    );
  }
  if (isEmpty?.(q.data)) return <>{empty ?? <div className="state-box"><h3>Nada por aqui ainda</h3></div>}</>;
  return (
    <>
      {q.isError && (
        <div className="state-banner" role="alert">
          Não foi possível atualizar {what}; os dados abaixo podem estar desatualizados.
          <button className="btn sm" onClick={() => q.refetch()} disabled={q.isFetching}>Tentar de novo</button>
        </div>
      )}
      {children(q.data)}
    </>
  );
}
