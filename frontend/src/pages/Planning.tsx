import { useQuery } from "@tanstack/react-query";
import { useApiMutation } from "../hooks/useApiMutation";
import { QueryState } from "../components/QueryState";
import { MoneyInput, NumberInput } from "../components/MoneyInput";
import { formatInputNumber, parseBRL, validateNumber } from "../format";
import { Fragment, useEffect, useState } from "react";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Trash2 } from "lucide-react";
import { api } from "../api";
import { Chart, cssVar, kTick } from "../components/Chart";
import { Chip, Money, Panel, useToast } from "../components/ui";
import { brl, date, monthLabel, pct, prettyName } from "../format";
import { Term } from "../components/Term";
import { useNavigate } from "react-router-dom";
import { HealthDetail } from "../components/FinancialHealth";

export default function Planning() {
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["planning"], queryFn: () => api<any>("/api/planning") });
  const [g, setG] = useState({ name: "", target_amount: "", target_date: "", basis: "bucket", kind: "prazo", priority: "100", expected_return_aa: "10" });
  const vTarget = validateNumber(g.target_amount, { required: true, allowNegative: false, min: 0.01 });
  const vReturn = validateNumber(g.expected_return_aa, { required: true, min: 0, max: 100 });
  const goalInvalid = !!(vTarget.error || vReturn.error);
  const addGoal = useApiMutation({
    mutationFn: () => api("/api/goals", { method: "POST", body: { ...g, target_amount: vTarget.value, priority: Number(g.priority) || 100,
      target_date: g.target_date || null, expected_return_aa: (vReturn.value ?? 0) / 100 } }),
    successMessage: "Meta criada", invalidate: [["planning"]],
    onSuccess: () => setG({ ...g, name: "", target_amount: "" }),
  });
  const delGoal = useApiMutation({ mutationFn: (id: number) => api(`/api/goals/${id}`, { method: "DELETE" }), invalidate: [["planning"]], successMessage: "Meta removida" });
  const recur = useApiMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) => api(`/api/recurring/${id}`, { method: "PATCH", body: { status } }),
    invalidate: [["planning"]],
  });
  const d = q.data;
  const [goalToDelete, setGoalToDelete] = useState<any>(null);
  const [plano, setPlano] = useState<any>(null);
  const [alvos, setAlvos] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!d) return;
    setPlano({ meta_aporte_mensal: formatInputNumber(d.plano.meta_aporte_mensal), reserva_meses_minima: formatInputNumber(d.plano.reserva_meses_minima ?? 6),
      aumento: d.plano.aumento_para_aporte == null ? "" : formatInputNumber(Math.round(d.plano.aumento_para_aporte * 100)),
      score: d.plano.score_credito == null ? "" : formatInputNumber(d.plano.score_credito) });
    setAlvos(Object.fromEntries(d.politica.classes.map((c: any) => [c.classe, c.alvo !== null ? formatInputNumber(Math.round(c.alvo * 1000) / 10) : ""])));
  }, [d]);
  const savePlano = useApiMutation({
    mutationFn: (p: { aporte: number | null; meses: number; aumento: number | null; score: number | null }) => api("/api/plan/settings", { method: "PUT", body: {
      meta_aporte_mensal: p.aporte, reserva_meses_minima: p.meses, aumento_para_aporte: p.aumento === null ? null : p.aumento / 100,
      score_credito: p.score } }),
    successMessage: "Plano salvo", invalidate: "all",
  });
  const saveAlvos = useApiMutation({
    mutationFn: (rows: { asset_class: string; target_pct: number }[]) => api("/api/plan/targets", { method: "PUT", body: rows }),
    successMessage: "Alocação-alvo salva", invalidate: "all",
  });
  if (!d || !plano) return <QueryState q={q} what="o planejamento">{() => null}</QueryState>;
  const vAporte = validateNumber(plano.meta_aporte_mensal, { allowNegative: false });
  const vMeses = validateNumber(plano.reserva_meses_minima, { required: true, min: 0, max: 120 });
  const vAumento = validateNumber(plano.aumento, { allowNegative: false, min: 0, max: 100 });
  const vScore = validateNumber(plano.score, { allowNegative: false, min: 0, max: 1000 });
  const planoInvalid = !!(vAporte.error || vMeses.error || vAumento.error || vScore.error);
  const alvosInvalid = Object.values(alvos).some((v) => validateNumber(v, { min: 0, max: 100 }).error);
  const pol = d.politica;
  const somaAlvos = Object.values(alvos).reduce((a, v) => a + (parseBRL(v) ?? 0), 0);
  const f = d.forecast;
  const out = d.recurring.filter((r: any) => r.direction === "out" && r.status !== "ignored");
  const inn = d.recurring.filter((r: any) => r.direction === "in" && r.status !== "ignored");
  const annual = out.reduce((a: number, r: any) => a + r.expected_amount * (365 / r.frequency_days), 0);
  return (
    <>
      {goalToDelete && (
        <ConfirmDialog title="Excluir esta meta?" itemName={goalToDelete.name} confirmLabel="Excluir meta" danger
          onCancel={() => setGoalToDelete(null)} onConfirm={() => { delGoal.mutate(goalToDelete.id); setGoalToDelete(null); }}>{null}</ConfirmDialog>
      )}
      <HealthDetail />
      <div className="grid g-wide">
        <Panel title="Previsão de caixa" hint="contas correntes, 6 meses">
          <Chart height={260} option={{
            tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v) },
            xAxis: { type: "category", data: f.months.map((m: any) => monthLabel(m.month)) },
            yAxis: [{ type: "value", axisLabel: { formatter: kTick } }],
            series: [
              { name: "Entradas", type: "bar", stack: "f", data: f.months.map((m: any) => Math.round(m.income)), itemStyle: { color: cssVar("--ledger") } },
              { name: "Despesas em conta", type: "bar", stack: "o", data: f.months.map((m: any) => -Math.round(m.bank_expenses)), itemStyle: { color: cssVar("--debit"), opacity: .75 } },
              { name: "Fatura do cartão", type: "bar", stack: "o", data: f.months.map((m: any) => -Math.round(m.card_bill)), itemStyle: { color: cssVar("--ochre") } },
              { name: "Despesas anuais", type: "bar", stack: "o", data: f.months.map((m: any) => -Math.round(m.annual ?? 0)), itemStyle: { color: cssVar("--debit"), opacity: .45 } },
              { name: "Saldo projetado", type: "line", data: f.months.map((m: any) => Math.round(m.end_cash)), symbolSize: 6, lineStyle: { color: cssVar("--ink"), width: 2 }, itemStyle: { color: cssVar("--ink") } },
            ],
          }} />
          <p className={`small ${f.min_cash < 0 ? "neg" : "soft"}`}>Menor saldo projetado: {brl(f.min_cash)}{f.min_cash < 0 ? ". Atenção: falta caixa em algum mês." : "."}</p>
          <details><summary className="note">Premissas</summary><ul className="assumptions">{f.assumptions.map((a: string, i: number) => <li key={i}>{a}</li>)}</ul></details>
        </Panel>
        <Panel title="Capacidade de investimento">
          <dl className="kv">
            <dt>Resultado mediano</dt><dd className="strong">{brl(d.capacity.median_result_6m)} por mês</dd>
            <dt>Resultado médio</dt><dd>{brl(d.capacity.avg_result_6m)} por mês</dd>
            <dt>Taxa de poupança 6m</dt><dd>{pct(d.kpis.avg6.taxa_poupanca, 0)}</dd>
            <dt>Parcelas em 3 meses</dt><dd>{brl(d.capacity.card_commitments_3m)}</dd>
            <dt>Aporte líquido no mês</dt><dd>{brl(d.kpis.invested_net)}</dd>
          </dl>
          <p className="note">Mediana dos últimos 6 meses fechados. É o quanto sobra de forma recorrente para investir sem consumir reserva.</p>
        </Panel>
      </div>

      <div className="grid g2">
        <Panel title="Gastos recorrentes" hint={`${brl(annual, 0)} por ano`} flush>
          <table className="table"><thead><tr><th>Descrição</th><th className="num">Valor</th><th>Próximo</th><th>Situação</th></tr></thead>
            <tbody>{out.map((r: any) => (
              <tr key={r.id}><td><div className="strong" title={r.description}>{prettyName(r.description)}</div><div className="small muted">{r.frequency_days >= 300 ? <>anual · provisão {brl(r.expected_amount / 12, 0)}/mês</> : `${r.occurrences} meses, dia ${r.day_of_month}`}</div></td>
                <td><Money v={-r.expected_amount} /></td><td className="soft">{date(r.next_date)}</td>
                <td>{r.status === "confirmed" ? <Chip tone="green">confirmado</Chip> : (
                  <span className="toolbar" style={{ flexWrap: "nowrap" }}><button className="btn sm" onClick={() => recur.mutate({ id: r.id, status: "confirmed" })}>Confirmar</button>
                    <button className="btn sm ghost" onClick={() => recur.mutate({ id: r.id, status: "ignored" })}>Ignorar</button></span>)}</td></tr>))}
              {out.length === 0 && <tr><td colSpan={4} className="muted" style={{ padding: 16 }}>Recorrências aparecem após 3 meses de histórico; despesas anuais (IPVA, IPTU, seguro, anuidade), assim que aparecem uma vez.</td></tr>}</tbody></table>
        </Panel>
        <Panel title="Receitas recorrentes" flush>
          <table className="table"><thead><tr><th>Origem</th><th className="num">Valor médio</th><th>Próximo</th></tr></thead>
            <tbody>{inn.map((r: any) => (
              <tr key={r.id}><td title={r.description}>{prettyName(r.description)}</td><td><Money v={r.expected_amount} /></td><td className="soft">{date(r.next_date)}</td></tr>))}
              {inn.length === 0 && <tr><td colSpan={3} className="muted" style={{ padding: 16 }}>Nenhuma detectada ainda.</td></tr>}</tbody></table>
          {d.budget.length > 0 && <div style={{ padding: "12px 18px" }}><h4 style={{ margin: "0 0 6px" }}>Orçamento do mês</h4>
            {d.budget.map((b: any) => (
              <div key={b.id} className="bar-row" style={{ gridTemplateColumns: "minmax(0,1fr) 120px 110px" }}>
                <span>{b.name}</span><div className={`bar ${b.usage > 1 ? "debit" : ""}`}><i style={{ width: `${Math.min(100, (b.usage ?? 0) * 100)}%` }} /></div>
                <span className="num small">{brl(b.actual, 0)} de {brl(b.budget, 0)}</span></div>))}</div>}
        </Panel>
      </div>

      <div className="grid g2">
        <Panel title="Plano" hint="usado no 'quanto posso gastar', nas simulações e nos alertas">
          <dl className="kv">
            <dt>Meta de aporte mensal</dt>
            <dd><MoneyInput width={130} allowNegative={false} ariaLabel="Meta de aporte mensal" placeholder={`sugestão ${brl(d.safe_to_spend.meta_aporte, 0)}`} value={plano.meta_aporte_mensal}
              onChange={(v) => setPlano({ ...plano, meta_aporte_mensal: v })} /> <span className="soft small">vazio = 20% da renda, limitado ao que sobrou nos últimos meses</span></dd>
            <dt>Reserva mínima</dt>
            <dd><NumberInput width={70} required min={0} max={120} ariaLabel="Reserva mínima em meses" value={plano.reserva_meses_minima}
              onChange={(v) => setPlano({ ...plano, reserva_meses_minima: v })} /> <span className="soft small">meses de <Term k="essenciais">custo essencial</Term> guardados em <Term k="liquidez_d1">liquidez D0/D1</Term></span></dd>
            <dt>Parte de cada aumento</dt>
            <dd><NumberInput width={70} min={0} max={100} placeholder="—" ariaLabel="Percentual de cada aumento destinado ao aporte" value={plano.aumento}
              onChange={(v) => setPlano({ ...plano, aumento: v })} /> <span className="soft small">% de cada aumento de renda vai automaticamente para a meta de aporte (vazio = desligado)</span></dd>
            <dt>Score de crédito</dt>
            <dd><NumberInput width={80} min={0} max={1000} placeholder="—" ariaLabel="Score de crédito" value={plano.score}
              onChange={(v) => setPlano({ ...plano, score: v })} /> <span className="soft small">Serasa/Boa Vista (0–1000); o Open Finance não traz, entra na saúde financeira</span></dd>
          </dl>
          <button className="btn primary sm" style={{ marginTop: 10 }} disabled={planoInvalid || savePlano.isPending} onClick={() => savePlano.mutate({ aporte: vAporte.value, meses: vMeses.value ?? 6, aumento: vAumento.value, score: vScore.value })}>Salvar plano</button>
          <RaiseInfo a={d.aumentos} />
          <h4 style={{ margin: "16px 0 4px" }}>Reserva de emergência</h4>
          <p className={pol.reserva.ok ? "" : "neg"}>
            {brl(pol.reserva.liquido_d0_d1, 0)} em liquidez imediata = <b>{pol.reserva.meses ? pol.reserva.meses.toFixed(1) : "—"} meses</b> de custo essencial
            ({brl(pol.reserva.custo_essencial_mensal, 0)}/mês). Mínimo definido: {pol.reserva.minimo_meses} meses.</p>
          {pol.reserva.custo_essencial_mensal > 0 && pol.reserva.degraus?.length > 0 && <ol className="reserve-steps">{pol.reserva.degraus.map((g: any) => (
            <li key={g.nome} className={g.atingido ? "done" : g.nome === pol.reserva.proximo_degrau?.nome ? "current" : ""}>
              <b>{g.nome}</b> · {g.meses} {g.meses === 1 ? "mês" : "meses"} ({brl(g.valor, 0)})
              {g.atingido ? <Chip tone="green">atingido</Chip> : <span className="soft small"> faltam {brl(g.falta, 0)}</span>}</li>))}</ol>}
        </Panel>
        <Panel title="Política de investimentos" hint="alvos são seus; o app só mede o desvio (banda: 5 p.p. ou 25% do alvo, o que for menor)" flush>
          <table className="table"><thead><tr><th>Classe</th><th className="num">Atual</th><th className="num">Alvo %</th><th>Situação</th><th className="num">Para o alvo</th></tr></thead>
            <tbody>{pol.classes.map((c: any) => (
              <tr key={c.classe}><td>{c.classe}</td><td className="num">{pct(c.atual, 1)}<div className="small muted">{brl(c.valor, 0)}</div></td>
                <td className="num"><NumberInput width={64} min={0} max={100} placeholder="—" ariaLabel={`Alvo % de ${c.classe}`} value={alvos[c.classe] ?? ""}
                  onChange={(v) => setAlvos({ ...alvos, [c.classe]: v })} /></td>
                <td>{c.status === "ok" ? <Chip tone="green">na banda</Chip> : c.status === "sem alvo" ? <span className="muted small">sem alvo</span>
                  : <Chip tone="ochre">{c.status}</Chip>}</td>
                <td className="num">{c.ajuste_para_alvo === null ? "—" : <Money v={c.ajuste_para_alvo} digits={0} />}</td></tr>))}</tbody></table>
          <div className="toolbar" style={{ padding: "10px 18px" }}>
            <span className={`small ${somaAlvos > 100.01 ? "neg" : "soft"}`}>Soma dos alvos: {somaAlvos.toFixed(1)}%</span>
            <button className="btn primary sm" disabled={somaAlvos > 100.01 || alvosInvalid || saveAlvos.isPending} onClick={() => saveAlvos.mutate(Object.entries(alvos).filter(([, v]) => v.trim() !== "").map(([k, v]) => ({ asset_class: k, target_pct: (parseBRL(v) ?? 0) / 100 })))}>Salvar alvos</button>
          </div>
          <AporteDestinos a={pol.aporte} temAlvos={pol.alvos_definidos} />
          <CalendarioFiscal c={pol.calendario_fiscal} />
        </Panel>
      </div>

      <Panel title="Metas" hint="cada meta mede o próprio bolso; o aporte do mês vai para elas por prioridade e prazo (simulação de 4.000 cenários com o aporte que cada uma recebe)">
        {d.plano_aportes && d.plano_aportes.falta_para_metas > 0 && <div className="callout" style={{ marginBottom: 10 }}><div className="grow">
          O aporte de {brl(d.plano_aportes.aporte, 0)}/mês não cobre todas as metas: faltam {brl(d.plano_aportes.falta_para_metas, 0)}/mês
          (soma dos necessários: {brl(d.plano_aportes.soma_necessaria_metas, 0)}). Aumente o aporte, estenda um prazo ou reduza uma meta.</div></div>}
        {d.goals.map((x: any) => <GoalRow key={x.id} x={x} onDelete={() => setGoalToDelete(x)} />)}
        <div className="toolbar" style={{ marginTop: 12 }}>
          <input className="input" placeholder="Nome da meta" value={g.name} onChange={(e) => setG({ ...g, name: e.target.value })} />
          <select className="select" value={g.kind} onChange={(e) => setG({ ...g, kind: e.target.value })} aria-label="Tipo de meta">
            <option value="prazo">com prazo</option><option value="aposentadoria">aposentadoria / independência</option><option value="livre">acúmulo livre</option></select>
          <MoneyInput width={130} allowNegative={false} placeholder="Valor alvo" ariaLabel="Valor alvo" value={g.target_amount} onChange={(v) => setG({ ...g, target_amount: v })} />
          {g.kind === "aposentadoria" && d.sugestao_independencia?.valor && <button className="btn sm ghost" title={`gasto anual de ${brl(d.sugestao_independencia.gasto_anual, 0)} ÷ ${pct(d.sugestao_independencia.taxa_retirada, 0)} de retirada ao ano`}
            onClick={() => setG({ ...g, target_amount: formatInputNumber(Math.round(d.sugestao_independencia.valor)) })}>usar {brl(d.sugestao_independencia.valor, 0)}</button>}
          <input className="input" type="date" value={g.target_date} onChange={(e) => setG({ ...g, target_date: e.target.value })} aria-label="Prazo" />
          <NumberInput width={64} min={1} max={999} ariaLabel="Prioridade (menor vem primeiro)" value={g.priority} onChange={(v) => setG({ ...g, priority: v })} />
          <span className="soft small">prioridade</span>
          <NumberInput width={70} min={0} max={100} ariaLabel="Retorno esperado % a.a." value={g.expected_return_aa} onChange={(v) => setG({ ...g, expected_return_aa: v })} />
          <span className="soft small">% a.a.</span>
          <button className="btn primary" disabled={!g.name || goalInvalid || addGoal.isPending} onClick={() => addGoal.mutate()}>Criar meta</button>
        </div>
        <p className="note">A meta ganha um bolso: separe nele o dinheiro em <a href="#" onClick={(e) => { e.preventDefault(); nav("/patrimonio"); }}>Patrimônio e bolsos</a>.</p>
      </Panel>
      <ContributionsPanel a={d.aportes_realizados} />
    </>
  );
}

function GoalSim({ g }: { g: any }) {
  const sim = g.simulacao;
  const p = sim.probabilidade;
  return (
    <div style={{ flexBasis: "100%", marginTop: 8 }}>
      <div className="small">
        <b className={p >= 0.7 ? "pos" : p >= 0.4 ? "" : "neg"}>{pct(p, 0)} de chance</b> de chegar em {brl(g.target_amount, 0)}
        {" · "}cenário mediano {brl(sim.final_p50, 0)} (pessimista {brl(sim.final_p10, 0)}, otimista {brl(sim.final_p90, 0)})
        <span className="muted"> · retorno {pct(sim.premissas.retorno_aa, 1)} a.a., vol {pct(sim.premissas.vol_aa, 1)} ({sim.fonte_risco})</span>
      </div>
      <Chart height={150} option={{
        legend: false, grid: { left: 50, right: 10, top: 10, bottom: 20 },
        tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v, 0) },
        xAxis: { type: "category", data: sim.trajetoria.map((t: any) => `${t.mes}m`) },
        yAxis: { type: "value", axisLabel: { formatter: kTick } },
        series: [
          { name: "Pessimista (p10)", type: "line", data: sim.trajetoria.map((t: any) => Math.round(t.p10)), symbol: "none", lineStyle: { width: 1, color: cssVar("--slate") } },
          { name: "Mediano", type: "line", data: sim.trajetoria.map((t: any) => Math.round(t.p50)), symbol: "none", lineStyle: { width: 2, color: cssVar("--ledger") } },
          { name: "Otimista (p90)", type: "line", data: sim.trajetoria.map((t: any) => Math.round(t.p90)), symbol: "none", lineStyle: { width: 1, color: cssVar("--slate") } },
          { name: "Meta", type: "line", data: sim.trajetoria.map(() => g.target_amount), symbol: "none", lineStyle: { width: 1, type: "dashed", color: cssVar("--ochre") } },
        ],
      }} />
    </div>
  );
}

function RaiseInfo({ a }: { a: any }) {
  if (!a) return null;
  const last = a.aplicados?.[a.aplicados.length - 1];
  if (a.detectado && a.fracao == null) return <p className="note" style={{ marginTop: 8 }}>
    Sua renda recorrente subiu {brl(a.detectado.aumento, 0)}/mês. Defina a parte de cada aumento que vai para o aporte: decidir antes de se acostumar com o dinheiro novo é o que mais faz a poupança crescer.</p>;
  if (last) return <p className="note" style={{ marginTop: 8 }}>
    Último aumento: +{brl(last.aumento, 0)}/mês em {monthLabel(last.mes)}{last.acrescimo_aporte ? `; meta de aporte +${brl(last.acrescimo_aporte, 0)}` : ""}.</p>;
  return null;
}

function AporteDestinos({ a, temAlvos }: { a: any; temAlvos: boolean }) {
  if (!a?.valor) return null;
  return (
    <div style={{ padding: "4px 18px 12px" }}>
      <h4 style={{ margin: "8px 0 4px" }}>Para onde vai o aporte deste mês ({brl(a.valor, 0)})</h4>
      {a.destinos.length === 0
        ? <p className="note">{temAlvos ? "Carteira já nos alvos: aporte na proporção dos alvos." : "Defina a alocação-alvo acima para ver a divisão sugerida do aporte."}</p>
        : <dl className="kv">{a.destinos.map((x: any) => <Fragment key={x.destino}><dt>{x.destino}</dt><dd className="num">{brl(x.valor, 0)} <span className="soft small">{x.motivo}</span></dd></Fragment>)}</dl>}
      <p className="note">Rebalancear pelo aporte evita vender (e pagar IR). Só classes, não produtos.</p>
    </div>
  );
}

function CalendarioFiscal({ c }: { c: any }) {
  if (!c || (!c.faixas.length && !c.come_cotas)) return null;
  return (
    <div style={{ padding: "0 18px 14px" }}>
      <h4 style={{ margin: "8px 0 4px" }}>Calendário fiscal</h4>
      {c.faixas.map((f: any) => (
        <div key={`${f.titulo}-${f.data}`} className="small">{prettyName(f.titulo)}{f.instituicao ? ` (${f.instituicao})` : ""}: em {f.dias} {f.dias === 1 ? "dia" : "dias"} ({date(f.data)}) o IR cai de {pct(f.de, 1)} para {pct(f.para, 1)}. Se precisar resgatar, vale esperar.</div>))}
      {c.come_cotas && <div className="small">Próximo come-cotas dos fundos: {date(c.come_cotas)}.</div>}
    </div>
  );
}

const STATUS_TONE: Record<string, "green" | "ochre" | "red" | undefined> = { "no ritmo": "green", "concluída": "green", "atrasada": "red", "medida antiga": "ochre" };

function GoalRow({ x, onDelete }: { x: any; onDelete: () => void }) {
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState({ target_amount: formatInputNumber(x.target_amount), target_date: x.target_date ?? "", priority: String(x.priority ?? 100) });
  const save = useApiMutation({
    mutationFn: (body: any) => api(`/api/goals/${x.id}`, { method: "PATCH", body }),
    successMessage: "Meta atualizada", invalidate: "all", onSuccess: () => setEdit(false),
  });
  return (
    <div className="list-row" style={{ flexWrap: "wrap" }}>
      <div className="grow">
        <div className="t">{x.name} <span className="soft small">· {x.kind_label} · prioridade {x.priority}</span> {x.status && <Chip tone={STATUS_TONE[x.status]}>{x.status}</Chip>}</div>
        <div className="s">{brl(x.current, 0)} de {brl(x.target_amount, 0)}{x.target_date ? `, até ${date(x.target_date)}` : ""}; retorno esperado {pct(x.expected_return_aa, 0)} a.a.</div>
        <div className="bar" style={{ marginTop: 6, maxWidth: 420 }}><i style={{ width: `${Math.min(100, (x.progress ?? 0) * 100)}%` }} /></div>
        {x.avisos?.map((a: string) => <div key={a} className="note" style={{ whiteSpace: "normal", marginTop: 4 }}>⚠ {a}</div>)}
      </div>
      <div style={{ textAlign: "right" }}>
        <div className="num strong">{x.monthly_needed != null ? `${brl(x.monthly_needed, 0)}/mês necessário` : "—"}</div>
        {x.aporte_alocado != null && <div className="small">{brl(x.aporte_alocado, 0)}/mês no plano{x.falta_aporte > 0 ? ` (faltam ${brl(x.falta_aporte, 0)})` : ""}</div>}
        <div className="small muted">{x.months_left ? `${x.months_left} meses` : ""}</div>
      </div>
      <button className="btn ghost sm" onClick={() => setEdit(!edit)}>{edit ? "Fechar" : "Editar"}</button>
      <button className="btn ghost sm danger" onClick={onDelete} aria-label="Remover meta"><Trash2 size={14} /></button>
      {edit && <div className="toolbar" style={{ flexBasis: "100%", marginTop: 6 }}>
        <MoneyInput width={130} allowNegative={false} ariaLabel="Valor alvo" value={f.target_amount} onChange={(v) => setF({ ...f, target_amount: v })} />
        <input className="input" type="date" value={f.target_date} onChange={(e) => setF({ ...f, target_date: e.target.value })} aria-label="Prazo" />
        <NumberInput width={64} min={1} max={999} ariaLabel="Prioridade" value={f.priority} onChange={(v) => setF({ ...f, priority: v })} />
        {x.legacy && <button className="btn sm" onClick={() => save.mutate({ basis: "bucket" })}>Converter para bolso</button>}
        <button className="btn primary sm" disabled={save.isPending} onClick={() => save.mutate({ target_amount: parseBRL(f.target_amount) ?? x.target_amount,
          target_date: f.target_date || null, priority: Number(f.priority) || 100 })}>Salvar</button>
      </div>}
      {x.simulacao && <GoalSim g={x} />}
    </div>
  );
}

function ContributionsPanel({ a }: { a: any }) {
  if (!a) return null;
  return (
    <Panel title="Aportes: planejado × realizado" hint={a.nota}>
      <Chart height={200} option={{
        tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v, 0) },
        xAxis: { type: "category", data: a.meses.map((m: any) => monthLabel(m.mes)) },
        yAxis: { type: "value", axisLabel: { formatter: kTick } },
        series: [
          { name: "Realizado", type: "bar", data: a.meses.map((m: any) => ({ value: Math.round(m.realizado),
            itemStyle: { color: m.cumprido ? cssVar("--ledger") : cssVar("--ochre") } })) },
          ...(a.meses[0]?.meta ? [{ name: "Meta", type: "line", symbol: "none", data: a.meses.map((m: any) => Math.round(m.meta)),
            lineStyle: { type: "dashed", color: cssVar("--ink") } }] : []),
        ],
      }} />
      <p className="small">{a.sequencia > 0 ? `${a.sequencia} ${a.sequencia === 1 ? "mês seguido" : "meses seguidos"} com a meta de aporte cumprida.` : "Nenhum mês recente com a meta cumprida: o plano de aportes acima mostra para onde direcionar."}
        {" "}Este mês: {brl(a.mes_atual.realizado, 0)}{a.mes_atual.meta ? ` de ${brl(a.mes_atual.meta, 0)}` : ""}.</p>
    </Panel>
  );
}
