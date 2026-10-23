import { useQuery } from "@tanstack/react-query";
import { Fragment, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronRight, Plus, Sparkles } from "lucide-react";
import { api } from "../api";
import { QueryState } from "../components/QueryState";
import { NumberInput } from "../components/MoneyInput";
import { Chip, Empty, Money, Panel } from "../components/ui";
import { useApiMutation } from "../hooks/useApiMutation";
import { brl, date, pct, prettyName } from "../format";
import { Term } from "../components/Term";
import { PatrimonyBridge, PatrimonyEvolution, PatrimonyProjection } from "../components/PatrimonyCharts";

type Item = { tipo: string; id: string; nome: string; instituicao: string; classe: string; faixa: string; valor: number;
  bolsos: { nome: string; valor: number }[]; conferencia?: { status: string; nota: string } | null; vencimento?: string; detalhe?: string };

const CHECK_TONE: Record<string, "green" | "ochre" | "red"> = { ok: "green", atencao: "ochre", falha: "red" };

export default function Patrimony() {
  const q = useQuery({ queryKey: ["patrimony"], queryFn: () => api<any>("/api/patrimony") });
  const b = useQuery({ queryKey: ["buckets"], queryFn: () => api<any>("/api/buckets") });
  const [group, setGroup] = useState("instituicao");
  const d = q.data;
  if (!d) return <QueryState q={q} what="o patrimônio">{() => null}</QueryState>;
  const bk = b.data;
  return (
    <>
      <section className="panel strip" aria-label="Resumo do patrimônio">
        <div><div className="lbl">Patrimônio líquido</div><div className="val num" style={{ textAlign: "left" }}>{brl(d.patrimonio_liquido)}</div>
          <div className="sub">{(() => { const n = new Set(d.itens.map((i: Item) => i.instituicao)).size; return `${d.itens.length} itens em ${n} ${n === 1 ? "lugar" : "lugares"}`; })()}</div></div>
        <div><div className="lbl"><Term k="liquidez">Disponível em 1 dia</Term></div><div className="val num" style={{ textAlign: "left" }}>{brl(d.disponivel_1_dia)}</div>
          <div className="sub">caixa e liquidez diária sem oscilação</div></div>
        {bk && <div><div className="lbl">Separado em bolsos</div><div className="val num" style={{ textAlign: "left" }}>{brl(bk.total - bk.livre)}</div>
          <div className="sub">livre: {brl(bk.livre)}</div></div>}
      </section>

      <Consolidated d={d} group={group} setGroup={setGroup} />
      {bk && <Buckets bk={bk} />}
      <PatrimonyBridge />
      <div className="grid g2">
        <PatrimonyEvolution />
        <PatrimonyProjection />
      </div>
    </>
  );
}

function groupKeys(it: Item, group: string): { key: string; valor: number }[] {
  if (group === "bolso") return it.bolsos.map((x) => ({ key: x.nome, valor: x.valor }));
  return [{ key: String((it as any)[group] ?? "—"), valor: it.valor }];
}

function Consolidated({ d, group, setGroup }: { d: any; group: string; setGroup: (g: string) => void }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const groups = useMemo(() => {
    const m = new Map<string, { total: number; items: { it: Item; valor: number }[] }>();
    for (const it of d.itens as Item[]) for (const g of groupKeys(it, group)) {
      const e = m.get(g.key) ?? { total: 0, items: [] };
      e.total += g.valor; e.items.push({ it, valor: g.valor }); m.set(g.key, e);
    }
    const order = group === "faixa" ? d.faixas : null;
    return [...m.entries()].sort((a, b) => order ? order.indexOf(a[0]) - order.indexOf(b[0]) : b[1].total - a[1].total);
  }, [d, group]);
  const assets = d.itens.filter((i: Item) => i.valor > 0).reduce((a: number, i: Item) => a + i.valor, 0);
  return (
    <Panel title="Onde está meu patrimônio" hint={d.nota} flush
      tools={<div className="segmented">{d.agrupamentos.map(([k, l]: [string, string]) =>
        <button key={k} className={group === k ? "on" : ""} onClick={() => setGroup(k)}>{l}</button>)}</div>}>
      <div className="table-wrap"><table className="table">
        <thead><tr><th>{d.agrupamentos.find((a: any) => a[0] === group)?.[1]}</th><th className="num">% dos ativos</th><th className="num">Valor</th></tr></thead>
        <tbody>{groups.map(([key, g]) => {
          const isOpen = !!open[key];
          return (
            <Fragment key={key}>
              <tr className="clickable" onClick={() => setOpen({ ...open, [key]: !isOpen })}>
                <td className="strong">{isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />} {key} <span className="muted small">({g.items.length})</span></td>
                <td className="num soft">{g.total > 0 && assets ? pct(g.total / assets, 1) : ""}</td>
                <td><Money v={g.total} /></td>
              </tr>
              {isOpen && g.items.sort((a, b) => b.valor - a.valor).map(({ it, valor }) => (
                <tr key={`${key}-${it.tipo}-${it.id}`} className="l1">
                  <td style={{ paddingLeft: 30 }}>
                    <div title={it.nome}>{prettyName(it.nome)} <span className="muted small">· {it.tipo}</span>
                      {it.conferencia && <> <Chip tone={CHECK_TONE[it.conferencia.status]}>{it.conferencia.status === "ok" ? "saldo confere" : "conferir"}</Chip></>}</div>
                    <div className="small muted">
                      {[group !== "instituicao" && it.instituicao, group !== "classe" && it.classe, group !== "faixa" && it.faixa,
                        it.vencimento && `vence ${date(it.vencimento)}`, it.detalhe,
                        group !== "bolso" && it.bolsos.length > 1 && `bolsos: ${it.bolsos.map((x) => `${x.nome} ${brl(x.valor, 0)}`).join(", ")}`]
                        .filter(Boolean).join(" · ")}
                      {it.conferencia && it.conferencia.status !== "ok" && <> · <Link to="/saude">{it.conferencia.nota}</Link></>}</div>
                  </td>
                  <td className="num soft small">{valor > 0 && assets ? pct(valor / assets, 1) : ""}</td>
                  <td><Money v={valor} /></td>
                </tr>))}
            </Fragment>);
        })}
          <tr className="sub"><td className="strong">= Patrimônio líquido</td><td /><td><Money v={d.total} /></td></tr>
        </tbody></table></div>
    </Panel>
  );
}

function Buckets({ bk }: { bk: any }) {
  const [edit, setEdit] = useState<number | null>(null);
  const [name, setName] = useState("");
  const create = useApiMutation({ mutationFn: () => api("/api/buckets", { method: "POST", body: { name } }),
    successMessage: "Bolso criado", invalidate: "all", onSuccess: () => setName("") });
  const suggest = useApiMutation({ mutationFn: () => api<any>("/api/buckets/suggest-reserve", { method: "POST" }),
    successMessage: (r: any) => r.criado ? `Reserva montada com ${r.fontes} fonte(s)` : r.motivo, invalidate: "all" });
  const reserve = bk.bolsos.find((x: any) => x.tipo === "reserva");
  return (
    <Panel title="Bolsos" hint="para que serve cada real: reserva, objetivos e aposentadoria. O resto fica livre." flush>
      <div className="slots">
        {bk.bolsos.map((x: any) => (
          <div key={x.id} className={`slot ${edit === x.id ? "on" : ""}`}>
            <div className="slot-head"><b>{x.nome}</b> <span className="soft small">{x.tipo === "reserva" ? "reserva" : x.tipo === "aposentadoria" ? "aposentadoria" : "objetivo"}</span></div>
            <div className="num strong">{brl(x.valor, 0)}{x.alvo ? <span className="soft small"> de {brl(x.alvo, 0)}</span> : null}</div>
            {x.alvo ? <div className={`bar ${x.progresso >= 1 ? "" : ""}`}><i style={{ width: `${Math.min(100, (x.progresso ?? 0) * 100)}%` }} /></div> : null}
            <div className="small muted">{x.fontes.length ? `${x.fontes.length} fonte(s)` : "vazio"}{x.fatia_renda_variavel > 0.2 ? ` · ${pct(x.fatia_renda_variavel, 0)} em renda variável` : ""}</div>
            <button className="btn sm ghost" onClick={() => setEdit(edit === x.id ? null : x.id)}>{edit === x.id ? "Fechar" : "Dividir"}</button>
          </div>))}
        <div className="slot free"><div className="slot-head"><b>Livre</b></div><div className="num strong">{brl(bk.livre, 0)}</div>
          <div className="small muted">não separado para nada</div></div>
      </div>
      <div className="toolbar" style={{ padding: "0 18px 14px" }}>
        {reserve && reserve.fontes.length === 0 && <button className="btn sm" disabled={suggest.isPending} onClick={() => suggest.mutate()}><Sparkles size={14} /> Montar a reserva automaticamente</button>}
        <input className="input" placeholder="Novo bolso (ex.: Carro novo)" value={name} onChange={(e) => setName(e.target.value)} />
        <button className="btn sm" disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}><Plus size={14} /> Criar bolso</button>
        <span className="note">Metas criadas no Planejamento já ganham um bolso.</span>
      </div>
      {edit !== null && <AllocationEditor bucket={bk.bolsos.find((x: any) => x.id === edit)} fontes={bk.fontes} onDone={() => setEdit(null)} />}
    </Panel>
  );
}

function AllocationEditor({ bucket, fontes, onDone }: { bucket: any; fontes: any[]; onDone: () => void }) {
  const mine = Object.fromEntries(bucket.fontes.filter((f: any) => f.origem === "manual").map((f: any) => [`${f.type}:${f.id}`, f.pct]));
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(Object.entries(mine).map(([k, v]) => [k, String(Math.round((v as number) * 1000) / 10)])));
  const save = useApiMutation({
    mutationFn: () => api(`/api/buckets/${bucket.id}/allocations`, { method: "PUT", body: Object.entries(vals)
      .filter(([, v]) => v.trim() !== "" && Number(v.replace(",", ".")) > 0)
      .map(([k, v]) => { const [source_type, ...rest] = k.split(":"); return { source_type, source_id: rest.join(":"), pct: Number(v.replace(",", ".")) / 100 }; }) }),
    successMessage: "Bolso atualizado", invalidate: "all", onSuccess: onDone,
  });
  if (!bucket) return null;
  const implicit = bucket.fontes.filter((f: any) => f.origem === "finalidade");
  return (
    <div style={{ padding: "0 18px 16px" }}>
      <h4 style={{ margin: "4px 0" }}>Dividir para "{bucket.nome}"</h4>
      {implicit.length > 0 && <p className="note">Entram inteiras pela finalidade Reserva (Configurações): {implicit.map((f: any) => f.label).join(", ")}.</p>}
      {fontes.filter((f) => f.value > 0).length === 0 ? <Empty title="Nada para dividir">Conecte contas ou cadastre bens.</Empty> :
        <div className="table-wrap"><table className="table"><thead><tr><th>Fonte</th><th className="num">Valor</th><th className="num">Já em outros bolsos</th><th className="num">Neste bolso (%)</th></tr></thead>
          <tbody>{fontes.filter((f) => f.value > 0).map((f) => {
            const k = `${f.type}:${f.id}`;
            const own = mine[k] ?? 0;
            const others = Math.max(0, f.alocado - own);
            return (
              <tr key={k}><td>{prettyName(f.label)} <span className="muted small">· {f.institution ?? f.classe}</span></td>
                <td><Money v={f.value} /></td><td className="num soft">{others > 0 ? pct(others, 0) : "—"}</td>
                <td className="num"><NumberInput width={70} min={0} max={Math.round((1 - others) * 1000) / 10} placeholder="0" ariaLabel={`% de ${f.label}`}
                  value={vals[k] ?? ""} onChange={(v) => setVals({ ...vals, [k]: v })} /></td></tr>);
          })}</tbody></table></div>}
      <div className="toolbar" style={{ marginTop: 8 }}>
        <button className="btn primary sm" disabled={save.isPending} onClick={() => save.mutate()}>Salvar divisão</button>
        <button className="btn sm ghost" onClick={onDone}>Cancelar</button>
      </div>
    </div>
  );
}
