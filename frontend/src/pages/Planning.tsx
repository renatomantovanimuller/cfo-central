import { useQuery } from "@tanstack/react-query";
import { useApiMutation } from "../hooks/useApiMutation";
import { QueryState } from "../components/QueryState";
import { MoneyInput, NumberInput } from "../components/MoneyInput";
import { formatInputNumber, parseBRL, validateNumber } from "../format";
import { useEffect, useState } from "react";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Trash2 } from "lucide-react";
import { api } from "../api";
import { Chart, cssVar, kTick } from "../components/Chart";
import { Chip, Money, Panel, useToast } from "../components/ui";
import { brl, date, monthLabel, pct, prettyName } from "../format";
import { Term } from "../components/Term";

export default function Planning() {
  const q = useQuery({ queryKey: ["planning"], queryFn: () => api<any>("/api/planning") });
  const [g, setG] = useState({ name: "", target_amount: "", target_date: "", basis: "investments", expected_return_aa: "10" });
  const vTarget = validateNumber(g.target_amount, { required: true, allowNegative: false, min: 0.01 });
  const vReturn = validateNumber(g.expected_return_aa, { required: true, min: 0, max: 100 });
  const goalInvalid = !!(vTarget.error || vReturn.error);
  const addGoal = useApiMutation({
    mutationFn: () => api("/api/goals", { method: "POST", body: { ...g, target_amount: vTarget.value,
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
    setPlano({ meta_aporte_mensal: formatInputNumber(d.plano.meta_aporte_mensal), reserva_meses_minima: formatInputNumber(d.plano.reserva_meses_minima ?? 6) });
    setAlvos(Object.fromEntries(d.politica.classes.map((c: any) => [c.classe, c.alvo !== null ? formatInputNumber(Math.round(c.alvo * 1000) / 10) : ""])));
  }, [d]);
  const savePlano = useApiMutation({
    mutationFn: (p: { aporte: number | null; meses: number }) => api("/api/plan/settings", { method: "PUT", body: {
      meta_aporte_mensal: p.aporte, reserva_meses_minima: p.meses } }),
    successMessage: "Plano salvo", invalidate: "all",
  });
  const saveAlvos = useApiMutation({
    mutationFn: (rows: { asset_class: string; target_pct: number }[]) => api("/api/plan/targets", { method: "PUT", body: rows }),
    successMessage: "Alocação-alvo salva", invalidate: "all",
  });
  if (!d || !plano) return <QueryState q={q} what="o planejamento">{() => null}</QueryState>;
  const vAporte = validateNumber(plano.meta_aporte_mensal, { allowNegative: false });
  const vMeses = validateNumber(plano.reserva_meses_minima, { required: true, min: 0, max: 120 });
  const planoInvalid = !!(vAporte.error || vMeses.error);
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
              <tr key={r.id}><td><div className="strong" title={r.description}>{prettyName(r.description)}</div><div className="small muted">{r.occurrences} meses, dia {r.day_of_month}</div></td>
                <td><Money v={-r.expected_amount} /></td><td className="soft">{date(r.next_date)}</td>
                <td>{r.status === "confirmed" ? <Chip tone="green">confirmado</Chip> : (
                  <span className="toolbar" style={{ flexWrap: "nowrap" }}><button className="btn sm" onClick={() => recur.mutate({ id: r.id, status: "confirmed" })}>Confirmar</button>
                    <button className="btn sm ghost" onClick={() => recur.mutate({ id: r.id, status: "ignored" })}>Ignorar</button></span>)}</td></tr>))}
              {out.length === 0 && <tr><td colSpan={4} className="muted" style={{ padding: 16 }}>Recorrências aparecem após 3 meses de histórico.</td></tr>}</tbody></table>
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
          </dl>
          <button className="btn primary sm" style={{ marginTop: 10 }} disabled={planoInvalid || savePlano.isPending} onClick={() => savePlano.mutate({ aporte: vAporte.value, meses: vMeses.value ?? 6 })}>Salvar plano</button>
          <h4 style={{ margin: "16px 0 4px" }}>Reserva de emergência</h4>
          <p className={pol.reserva.ok ? "" : "neg"}>
            {brl(pol.reserva.liquido_d0_d1, 0)} em liquidez imediata = <b>{pol.reserva.meses ? pol.reserva.meses.toFixed(1) : "—"} meses</b> de custo essencial
            ({brl(pol.reserva.custo_essencial_mensal, 0)}/mês). Mínimo definido: {pol.reserva.minimo_meses} meses.</p>
        </Panel>
        <Panel title="Política de investimentos" hint="alvos são seus; o app só mede o desvio (banda ± 5 p.p.)" flush>
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
        </Panel>
      </div>

      <Panel title="Metas" hint={`aporte necessário e simulação de 4.000 cenários com aporte de ${brl(d.aporte_simulacao, 0)}/mês e o risco da carteira`}>
        {d.goals.map((x: any) => (
          <div key={x.id} className="list-row" style={{ flexWrap: "wrap" }}>
            <div className="grow"><div className="t">{x.name}</div>
              <div className="s">{brl(x.current, 0)} de {brl(x.target_amount, 0)}{x.target_date ? `, até ${date(x.target_date)}` : ""}; retorno esperado {pct(x.expected_return_aa, 0)} a.a.</div>
              <div className="bar" style={{ marginTop: 6, maxWidth: 420 }}><i style={{ width: `${Math.min(100, (x.progress ?? 0) * 100)}%` }} /></div></div>
            <div style={{ textAlign: "right" }}><div className="num strong">{x.monthly_needed !== null ? `${brl(x.monthly_needed, 0)}/mês` : "—"}</div>
              <div className="small muted">{x.months_left ? `${x.months_left} meses` : ""}</div></div>
            <button className="btn ghost sm danger" onClick={() => setGoalToDelete(x)} aria-label="Remover meta"><Trash2 size={14} /></button>
            {x.simulacao && <GoalSim g={x} />}
          </div>))}
        <div className="toolbar" style={{ marginTop: 12 }}>
          <input className="input" placeholder="Nome da meta" value={g.name} onChange={(e) => setG({ ...g, name: e.target.value })} />
          <MoneyInput width={130} allowNegative={false} placeholder="Valor alvo" ariaLabel="Valor alvo" value={g.target_amount} onChange={(v) => setG({ ...g, target_amount: v })} />
          <input className="input" type="date" value={g.target_date} onChange={(e) => setG({ ...g, target_date: e.target.value })} />
          <select className="select" value={g.basis} onChange={(e) => setG({ ...g, basis: e.target.value })}>
            <option value="investments">medir pelos investimentos</option><option value="net_worth">medir pelo patrimônio líquido</option></select>
          <NumberInput width={80} min={0} max={100} ariaLabel="Retorno esperado % a.a." value={g.expected_return_aa} onChange={(v) => setG({ ...g, expected_return_aa: v })} />
          <span className="soft small">% a.a.</span>
          <button className="btn primary" disabled={!g.name || goalInvalid || addGoal.isPending} onClick={() => addGoal.mutate()}>Criar meta</button>
        </div>
      </Panel>
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
