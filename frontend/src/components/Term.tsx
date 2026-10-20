import { ReactNode, useEffect, useId, useRef, useState } from "react";

/** Explicações curtas, em linguagem comum, para os termos técnicos que aparecem nas telas. */
export const GLOSSARY: Record<string, string> = {
  dre: "Demonstração do Resultado: quanto entrou (receitas) menos quanto saiu (despesas) em cada mês. Mostra se você está poupando ou gastando mais do que ganha.",
  dfc: "Demonstração do Fluxo de Caixa: o dinheiro que efetivamente entrou e saiu das contas, inclusive pagamento de fatura, aportes e resgates.",
  balanco: "Balanço: fotografia do que você tem (contas, investimentos, bens) e do que deve (cartão, empréstimos) no fim de cada mês.",
  competencia: "Por competência: o gasto conta no mês em que aconteceu (data da compra no cartão), não no mês em que a fatura foi paga.",
  patrimonio: "Patrimônio líquido: tudo o que você tem (contas, investimentos, bens informados) menos tudo o que deve (faturas atuais e futuras, empréstimos).",
  liquidez: "Liquidez imediata: dinheiro que dá para usar em até 1 dia útil (conta + investimentos resgatáveis, sem previdência/COE), já descontada a fatura atual do cartão. As parcelas futuras não entram aqui, por isso este número pode ser maior que o patrimônio líquido.",
  receita_liquida: "Receita líquida: tudo o que você recebeu como renda no mês (salário, freelas, rendimentos), já descontado o imposto retido.",
  resultado_recorrente: "Resultado recorrente: receita menos despesas do mês, sem contar entradas extraordinárias como herança ou doação. É o quanto sobrou de verdade.",
  poupanca: "Taxa de poupança: que parte da sua renda sobrou no mês. 20% significa que você guardou R$ 20 a cada R$ 100 recebidos.",
  aporte: "Aporte líquido: quanto você colocou em investimentos no mês menos quanto resgatou.",
  capacidade: "Capacidade de investir: o valor típico (mediana) que sobrou por mês nos últimos 6 meses fechados. Se for negativo, você vem gastando mais do que ganha.",
  proxy: "Estimativa (proxy): como ainda não há histórico próprio, o retorno é calculado aplicando os pesos de hoje da sua carteira aos preços passados de cada ativo.",
  volatilidade: "Volatilidade: o quanto o valor da carteira oscila. Quanto maior, mais sobe e desce no caminho.",
  sharpe: "Sharpe e Sortino: quanto retorno acima do CDI a carteira entregou para cada unidade de risco. Acima de 1 é bom; perto de 0, o risco não compensou.",
  drawdown: "Pior queda: a maior perda do pico ao fundo no período, antes de recuperar.",
  var: "VaR 95% em 1 mês: em 95 de cada 100 meses, a perda não deve passar deste percentual. É uma estimativa, não um limite.",
  beta: "Beta Ibov: o quanto a carteira acompanha a bolsa. 1 = anda junto com o Ibovespa; 0 = não tem relação.",
  posicoes_efetivas: "Posições efetivas: quantos investimentos de mesmo tamanho dariam a mesma diversificação. Se for muito menor que o número de posições, o dinheiro está concentrado em poucas.",
  fgc: "FGC: garantia de até R$ 250 mil por CPF e por banco emissor (conglomerado) para CDB, LCI, LCA e afins, caso o banco quebre.",
  tir: "TIR: o rendimento anual equivalente considerando as datas e valores de cada aplicação e resgate.",
  twr: "Retorno ponderado no tempo: mede o desempenho dos investimentos sem ser distorcido pelos aportes e resgates.",
  pct_cdi: "% do CDI: quanto o investimento rendeu comparado ao CDI (a taxa de referência da renda fixa). 100% = rendeu igual ao CDI.",
  liquidez_d1: "D0/D1: dinheiro disponível no mesmo dia (D0) ou no dia útil seguinte (D1), como conta corrente e CDB de liquidez diária.",
  resultado_economico: "Resultado econômico: o resultado do mês mais a valorização (ou desvalorização) dos seus investimentos.",
  essenciais: "Custo de vida essencial: moradia, mercado, saúde, transporte, contas da casa. O que não dá para cortar no curto prazo.",
  confianca: "Confiança: o quanto o app tem certeza da categoria sugerida. Baixa confiança vira item na Revisão.",
};

/**
 * Termo com explicação: sublinhado pontilhado, abre a definição ao passar o mouse ou ao focar (teclado e toque no celular).
 * Use `k` para um verbete do GLOSSARY ou `tip` para um texto próprio.
 */
export function Term({ k, tip, children }: { k?: keyof typeof GLOSSARY | string; tip?: string; children: ReactNode }) {
  const text = tip ?? (k ? GLOSSARY[k] : undefined);
  const [open, setOpen] = useState(false);
  const id = useId();
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  if (!text) return <>{children}</>;
  return (
    <span ref={ref} className="term" tabIndex={0} role="button" aria-describedby={open ? id : undefined} aria-expanded={open}
      onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
      onClick={(e) => e.stopPropagation()}>
      {children}
      {open && <span className="term-tip" role="tooltip" id={id}>{text}</span>}
    </span>
  );
}
