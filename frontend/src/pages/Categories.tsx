import { useQuery } from "@tanstack/react-query";
import { useApiMutation } from "../hooks/useApiMutation";
import { QueryState } from "../components/QueryState";
import { AutoSaveMoney, AutoSaveText } from "../components/MoneyInput";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import { api } from "../api";
import { Chart, cssVar, kTick } from "../components/Chart";
import { useMonth } from "../components/Layout";
import { Drawer, Money, Panel, useToast } from "../components/ui";
import { brl, monthLabel, monthLong, pct } from "../format";

const LINES: Record<string, string> = { receita_operacional: "Receita operacional", outras_receitas: "Outras receitas",
  essenciais: "Essenciais", estilo_vida: "Estilo de vida", terceiros: "Terceiros", receitas_financeiras: "Receitas financeiras",
  despesas_financeiras: "Despesas financeiras", impostos_renda: "Impostos", nao_classificado: "A classificar" };

function Spark({ values }: { values: number[] }) {
  const max = Math.max(...values.map(Math.abs), 1);
  return (
    <span style={{ display: "inline-flex", gap: 2, alignItems: "flex-end", height: 18 }} aria-hidden>
      {values.map((v, i) => <i key={i} style={{ width: 5, height: `${Math.max(2, (Math.abs(v) / max) * 18)}px`,
        background: i === values.length - 1 ? "var(--ledger)" : "var(--rule-strong)", borderRadius: 1 }} />)}
    </span>
  );
}

export default function Categories() {
  const { month } = useMonth();
  const [open, setOpen] = useState<string | null>(null);
  const [nature, setNature] = useState<"despesa" | "receita">("despesa");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const q = useQuery({ queryKey: ["categories", month], queryFn: () => api<any[]>(`/api/categories?month=${month}`) });
  const patch = useApiMutation({
    mutationFn: ({ id, body }: { id: string; body: any }) => api(`/api/categories/${id}`, { method: "PATCH", body }),
    successMessage: "Categoria atualizada. A DRE usa a nova classificação", invalidate: "all",
  });
  const create = useApiMutation({
    mutationFn: (body: any) => api("/api/categories", { method: "POST", body }),
    successMessage: "Subcategoria criada", invalidate: "all",
  });
  if (!q.data) return <QueryState q={q} what="as categorias">{() => null}</QueryState>;
  const all = q.data ?? [];
  const isExpense = (c: any) => ["despesa", "imposto"].includes(c.nature) || c.id.startsWith("findesp");
  const weight = (c: any) => Math.max(Math.abs(c.current), Math.abs(c.avg3), c.budget ?? 0);
  const roots = all.filter((c) => !c.parent_id && (nature === "despesa" ? isExpense(c) : !isExpense(c)))
    .sort((a, b) => weight(b) - weight(a));
  const sign = nature === "despesa" ? -1 : 1;
  const totalBudget = roots.reduce((a, c) => a + (c.budget ?? 0), 0);
  const totalCur = roots.reduce((a, c) => a + sign * c.current, 0);

  const row = (c: any, child = false): JSX.Element[] => {
    const cur = sign * c.current;
    const use = c.budget ? cur / c.budget : null;
    const kids = all.filter((k) => k.parent_id === c.id);
    return [
        <tr key={c.id} className="clickable" onClick={() => setOpen(c.id)}>
          <td style={{ paddingLeft: child ? 34 : 12 }}>
            {!child && kids.length > 0 && <button className="btn ghost sm" style={{ padding: "0 4px", marginRight: 4 }}
              onClick={(e) => { e.stopPropagation(); setExpanded((x) => ({ ...x, [c.id]: !x[c.id] })); }}>{expanded[c.id] ? "−" : "+"}</button>}
            <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: c.color ?? "var(--rule-strong)", marginRight: 8 }} />
            <span className={child ? "soft" : "strong"}>{c.name}</span>
          </td>
          <td className="soft small">{LINES[c.dre_line] ?? "—"}{c.essential ? "" : ""}</td>
          <td><Spark values={c.series.map((v: number) => sign * v)} /></td>
          <td><Money v={cur} colored={false} /></td>
          <td className="num soft">{brl(sign * c.avg3, 0)}</td>
          <td onClick={(e) => e.stopPropagation()} style={{ width: 200 }}>
            <AutoSaveMoney value={c.budget ?? null} placeholder="definir" ariaLabel={`Orçamento de ${c.name}`}
              onSave={(amount) => api(`/api/budgets/${c.id}`, { method: "PUT", body: { amount } })} />
          </td>
          <td style={{ width: 160 }}>{use !== null && <div className="bar-row" style={{ gridTemplateColumns: "1fr 44px" }}>
            <div className={`bar ${use > 1 ? "debit" : ""}`}><i style={{ width: `${Math.min(100, use * 100)}%`, background: use > 1 ? undefined : use > 0.85 ? "var(--ochre)" : undefined }} /></div>
            <span className="num small">{pct(use, 0)}</span></div>}</td>
        </tr>,
        ...(!child && expanded[c.id] ? kids.flatMap((k) => row(k, true)) : []),
    ];
  };

  return (
    <>
      <Panel title={nature === "despesa" ? "Despesas por categoria" : "Receitas por categoria"} hint={monthLong(month)}
        tools={<div className="segmented">
          <button className={nature === "despesa" ? "on" : ""} onClick={() => setNature("despesa")}>Despesas</button>
          <button className={nature === "receita" ? "on" : ""} onClick={() => setNature("receita")}>Receitas</button></div>} flush>
        <div className="table-wrap" style={{ maxHeight: "none" }}>
          <table className="table">
            <thead><tr><th>Categoria</th><th>Linha da DRE</th><th>6 meses</th><th className="num">Mês</th><th className="num">Média 3m</th><th>Orçamento</th><th>Uso</th></tr></thead>
            <tbody>{roots.flatMap((c) => row(c))}</tbody>
            <tbody><tr><td className="strong">Total</td><td /><td /><td><Money v={totalCur} colored={false} /></td><td /><td className="num strong">{totalBudget ? brl(totalBudget) : ""}</td>
              <td className="num small">{totalBudget ? pct(totalCur / totalBudget, 0) : ""}</td></tr></tbody>
          </table>
        </div>
      </Panel>
      {open && <CategoryDrawer id={open} onClose={() => setOpen(null)} cat={all.find((c) => c.id === open)}
        onPatch={(body) => patch.mutate({ id: open, body })} onCreate={(name) => create.mutate({ parent_id: open, name })} />}
    </>
  );
}

function CategoryDrawer({ id, onClose, cat, onPatch, onCreate }: { id: string; onClose: () => void; cat: any; onPatch: (b: any) => void; onCreate: (n: string) => void }) {
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["cat-detail", id], queryFn: () => api<any>(`/api/categories/${id}/detail`) });
  const [newName, setNewName] = useState("");
  const d = q.data;
  const expense = cat && ["despesa", "imposto", "financeiro"].includes(cat.nature);
  const s = expense ? -1 : 1;
  return (
    <Drawer title={d?.category.name ?? "Categoria"} onClose={onClose}>
      {!d ? <QueryState q={q} what="a categoria" layout="panel">{() => null}</QueryState> : <>
        <Chart height={200} option={{
          legend: false, tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v) },
          xAxis: { type: "category", data: d.series.map((x: any) => monthLabel(x.month)) },
          yAxis: { type: "value", axisLabel: { formatter: kTick } },
          series: [{ type: "bar", data: d.series.map((x: any) => Math.round(s * x.value)), itemStyle: { color: cssVar("--ledger"), borderRadius: [2, 2, 0, 0] } }],
        }} />
        {d.subcategories.length > 1 && <section><h4 style={{ margin: "0 0 6px" }}>Subcategorias, 12 meses</h4>
          {d.subcategories.map((x: any) => <div key={x.id} className="list-row"><div className="grow t">{x.name}</div><Money v={s * x.value} colored={false} /></div>)}</section>}
        <section><h4 style={{ margin: "0 0 6px" }}>Comerciantes, 12 meses</h4>
          {d.merchants.length === 0 && <p className="muted">Nenhum comerciante identificado.</p>}
          {d.merchants.map((m: any) => (
            <div key={m.id} className="list-row" style={{ cursor: "pointer" }} onClick={() => nav(`/razao?merchant=${m.id}&all=1`)}>
              <div className="grow"><div className="t">{m.name}</div><div className="s">{m.count} lançamentos, ticket médio {brl(s * m.avg_ticket)}</div></div>
              <Money v={s * m.total} colored={false} /></div>))}</section>
        {cat && <section><h4 style={{ margin: "0 0 6px" }}>Ajustes</h4>
          <div className="grid" style={{ gap: 8 }}>
            <label className="field">Nome<AutoSaveText value={cat.name} ariaLabel="Nome da categoria" onSave={(name) => api(`/api/categories/${id}`, { method: "PATCH", body: { name } })} /></label>
            {expense && <label className="field">Linha da DRE
              <select className="select" value={cat.dre_line ?? ""} onChange={(e) => onPatch({ dre_line: e.target.value, essential: e.target.value === "essenciais" })}>
                <option value="essenciais">Custo de vida essencial</option><option value="estilo_vida">Estilo de vida</option>
                <option value="terceiros">Transferências a terceiros</option><option value="despesas_financeiras">Despesas financeiras</option>
                <option value="impostos_renda">Impostos</option></select></label>}
            {!cat.parent_id && <div className="toolbar">
              <input className="input" placeholder="Nova subcategoria" value={newName} onChange={(e) => setNewName(e.target.value)} />
              <button className="btn" disabled={!newName} onClick={() => { onCreate(newName); setNewName(""); }}><Plus size={14} /> Criar</button></div>}
            <button className="btn sm" onClick={() => nav(`/razao?category=${id}&all=1`)}>Ver todos os lançamentos</button>
          </div></section>}
      </>}
    </Drawer>
  );
}
