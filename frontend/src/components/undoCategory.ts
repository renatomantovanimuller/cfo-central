/** Corpo do PATCH que devolve o lançamento à categoria anterior (sem override anterior, limpa o ajuste). */
export const undoCategoryBody = (previous: string | null | undefined, hadOverride = true) =>
  previous || hadOverride ? { category_id: previous || null, learn: !!previous } : { clear: true };
