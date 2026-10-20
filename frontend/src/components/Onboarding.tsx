import { ReactNode, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Check, X } from "lucide-react";
import { api } from "../api";
import { brl, pct } from "../format";
import { Onboarding, PROVISIONAL_SHARE, useOnboarding } from "../hooks/useOnboarding";
import { PluggyForm } from "./Integrations";
import { reviewSummary } from "./reviewBadge";

type Step = { key: string; title: string; detail: ReactNode; done: boolean; action?: ReactNode };

const HIDE_KEY = "cfo.checklist.oculto";
const readHidden = () => { try { return localStorage.getItem(HIDE_KEY) === "1"; } catch { return false; } };

function useSteps(o: Onboarding | undefined, pendingDecisions: number) {
  const nav = useNavigate();
  if (!o) return [];
  const syncing = !!o.sync?.running;
  const go = (to: string, label: string, primary = true) => <button className={`btn ${primary ? "primary" : ""}`} onClick={() => nav(to)}>{label}</button>;
  const steps: Step[] = [
    { key: "pluggy", title: "Cadastrar a chave da Pluggy", done: o.pluggy_configured,
      detail: "A Pluggy é o serviço de Open Finance que lê seus extratos. O plano MeuPluggy é gratuito para uso pessoal." },
    { key: "bank", title: "Conectar o primeiro banco", done: o.items > 0,
      detail: "Autorize o banco no meu.pluggy.ai e depois clique em Conectar. Repita para cada banco (até 5).",
      action: go("/conexoes", "Conectar banco") },
    { key: "sync", title: "Importar os lançamentos", done: o.events > 0,
      detail: syncing ? <>Importando agora: {o.sync.step}. Leva de 1 a 3 minutos por banco.</> : "A primeira importação traz até 12 meses de histórico.",
      action: syncing ? <span className="spinner sm" role="status" aria-label="Importando" /> : undefined },
    { key: "review", title: "Confirmar o que é salário e o que é transferência",
      done: o.events > 0 && pendingDecisions === 0 && o.income_unclassified_share < PROVISIONAL_SHARE,
      detail: pendingDecisions > 0 ? `${pendingDecisions} ${pendingDecisions === 1 ? "decisão" : "decisões"} de um clique. Cada uma vale para todos os lançamentos da mesma contraparte.`
        : "Sem pendências de classificação.",
      action: pendingDecisions > 0 ? go("/revisao", "Revisar agora") : undefined },
    { key: "budget", title: "Definir orçamentos", done: o.budgets > 0,
      detail: "Escolha um teto mensal para as categorias que mais pesam (mercado, restaurantes, compras).",
      action: go("/categorias", "Definir orçamento", false) },
    { key: "plan", title: "Definir quanto quer investir por mês", done: o.plan_set,
      detail: "Usado no \"quanto posso gastar\" e nas metas. Sem isso, o app sugere 20% da renda, limitado ao que de fato sobra.",
      action: go("/planejamento", "Definir meta", false) },
  ];
  return steps;
}

function StepList({ steps, pluggyInline }: { steps: Step[]; pluggyInline: boolean }) {
  const current = steps.find((s) => !s.done)?.key;
  return (
    <ol className="steps">
      {steps.map((s, i) => (
        <li key={s.key} className={`step ${s.done ? "done" : ""} ${s.key === current ? "current" : ""}`}>
          <span className="n" aria-hidden>{s.done ? <Check size={14} /> : i + 1}</span>
          <div>
            <div className="t">{s.title}{s.done && <span className="sr-only"> (feito)</span>}</div>
            <div className="s">{s.detail}</div>
            {pluggyInline && s.key === "pluggy" && s.key === current && <div style={{ marginTop: 12 }}><PluggyForm /></div>}
          </div>
          {/* os três primeiros passos dependem um do outro: só o atual tem botão; os demais podem ser feitos em qualquer ordem */}
          <div>{!s.done && s.key !== "pluggy" && (i >= 3 || s.key === current) && s.action}</div>
        </li>
      ))}
    </ol>
  );
}

/** Tela de boas-vindas: substitui o Painel enquanto não há nenhum lançamento. */
export function Welcome() {
  const o = useOnboarding();
  const steps = useSteps(o.data, 0).slice(0, 3);
  const done = steps.filter((s) => s.done).length;
  return (
    <section className="panel welcome">
      <div>
        <h2>Bem-vindo ao CFO Central</h2>
        <p className="lead" style={{ marginTop: 6 }}>
          Seu painel financeiro pessoal: ele lê seus bancos pelo Open Finance, separa receitas, despesas, faturas e investimentos
          e mostra quanto sobra por mês. Tudo fica neste computador. Três passos e os números aparecem aqui.
        </p>
      </div>
      <div className="progress" aria-label={`${done} de ${steps.length} passos`}><i style={{ width: `${(done / steps.length) * 100}%` }} /></div>
      {o.data ? <StepList steps={steps} pluggyInline /> : <span className="spinner" role="status" aria-label="Carregando" />}
      <p className="note" style={{ margin: 0 }}>
        Nada aqui movimenta dinheiro: o acesso aos bancos é só de leitura e pode ser revogado no meu.pluggy.ai a qualquer momento.
      </p>
    </section>
  );
}

/** Lista compacta de configuração que segue no Painel até o usuário terminar (ou ocultar). */
export function SetupChecklist() {
  const o = useOnboarding();
  const reviews = useQuery({ queryKey: ["reviews-count"], queryFn: () => api<any[]>("/api/reviews") });
  const pending = reviewSummary(reviews.data).pending;
  const steps = useSteps(o.data, pending);
  const [hidden, setHidden] = useState(readHidden);
  const [open, setOpen] = useState(true);
  const left = steps.filter((s) => !s.done);
  if (!o.data || hidden || left.length === 0 || o.data.events === 0) return null;
  const hide = () => { try { localStorage.setItem(HIDE_KEY, "1"); } catch { /* sem storage: só nesta sessão */ } setHidden(true); };
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Primeiros passos</h2>
        <span className="hint">{steps.length - left.length} de {steps.length} concluídos</span>
        <div className="tools">
          <button className="btn sm ghost" onClick={() => setOpen(!open)}>{open ? "Recolher" : "Mostrar"}</button>
          <button className="btn sm ghost" onClick={hide} aria-label="Ocultar primeiros passos" title="Ocultar"><X size={14} /></button>
        </div>
      </div>
      <div className="panel-body">
        <div className="progress" style={{ marginBottom: open ? 12 : 0 }}><i style={{ width: `${((steps.length - left.length) / steps.length) * 100}%` }} /></div>
        {open && <StepList steps={steps} pluggyInline={false} />}
      </div>
    </section>
  );
}

/** Aviso de que receitas ainda "a classificar" distorcem o resultado (aparece no Painel e na DRE). */
export function ProvisionalBanner() {
  const o = useOnboarding();
  const nav = useNavigate();
  const d = o.data;
  if (!d || d.events === 0 || d.income_unclassified_share < PROVISIONAL_SHARE) return null;
  return (
    <div className="callout" role="status">
      <div className="grow">
        <b>Números provisórios.</b> {pct(d.income_unclassified_share, 0)} do que você recebeu nos últimos 3 meses ({brl(d.income_unclassified, 0)})
        ainda está como "a classificar". Enquanto o app não souber o que é salário, reembolso ou transferência entre suas contas, receita e resultado podem estar distorcidos.
      </div>
      <button className="btn primary" onClick={() => nav("/revisao")}>Classificar recebimentos</button>
    </div>
  );
}
