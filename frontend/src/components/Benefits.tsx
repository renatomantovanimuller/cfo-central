import { useQuery } from "@tanstack/react-query";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useApiMutation } from "../hooks/useApiMutation";
import { brl, date, dateTime, formatInputNumber, monthLabel, thisMonth, validateNumber } from "../format";
import { MoneyInput } from "./MoneyInput";
import { Chip, Panel } from "./ui";

type Valor = { desde: string; valor: string };
type Item = { id: string; nome: string; fornecedor: string; dia: string; valores: Valor[]; ate: string; ativo: boolean };

const EMISSORES = ["Pluxee (Sodexo)", "Alelo", "VR", "Ticket", "Caju", "Flash", "Swile", "iFood Benefícios", "Ben Visa Vale", "Up Brasil"];
const blank = (n: number): Item => ({ id: `b${n}`, nome: n === 1 ? "Vale-refeição" : "Vale-alimentação", fornecedor: "", dia: "1",
  valores: [{ desde: thisMonth(), valor: "" }], ate: "", ativo: true });

const fromApi = (it: any): Item => ({ ...it, fornecedor: it.fornecedor ?? "", dia: String(it.dia), ate: it.ate ?? "",
  valores: it.valores.map((v: any) => ({ desde: v.desde, valor: formatInputNumber(v.valor) })) });

/** VR/VA não chegam pelo Open Finance: valor e dia do crédito informados aqui viram crédito + consumo mensais no razão. */
export function BenefitsPanel() {
  const q = useQuery({ queryKey: ["benefits"], queryFn: () => api<any>("/api/benefits") });
  const [items, setItems] = useState<Item[] | null>(null);
  useEffect(() => { if (q.data && items === null) setItems(q.data.config.itens.map(fromApi)); }, [q.data, items]);
  const save = useApiMutation({
    mutationFn: (body: any) => api<any>("/api/benefits", { method: "PUT", body }),
    successMessage: (r) => `Benefícios salvos · ${r.meses} meses no razão`, invalidate: "all",
    onSuccess: (r) => setItems(r.config.itens.map(fromApi)),
  });
  const check = useApiMutation({ mutationFn: () => api<any>("/api/benefits/pluggy-check", { method: "POST" }), invalidate: [["benefits"]],
    successMessage: (r) => (r.erro ? `Não consegui consultar a Pluggy: ${r.erro}` : r.encontrados.length ? "Há conector de benefício na Pluggy" : "Pluggy consultada: nenhum conector de benefício") });

  const list = items ?? [];
  const errors = list.flatMap((it) => it.valores.map((v) => validateNumber(v.valor, { required: true, allowNegative: false }).error)).filter(Boolean);
  const dirty = q.data && JSON.stringify(list) !== JSON.stringify(q.data.config.itens.map(fromApi));
  const upd = (i: number, patch: Partial<Item>) => setItems(list.map((it, k) => (k === i ? { ...it, ...patch } : it)));
  const updV = (i: number, j: number, patch: Partial<Valor>) =>
    upd(i, { valores: list[i].valores.map((v, k) => (k === j ? { ...v, ...patch } : v)) });
  const submit = () => save.mutate({ itens: list.map((it) => ({ ...it, dia: Number(it.dia) || 1, ate: it.ate || null,
    valores: it.valores.map((v) => ({ desde: v.desde, valor: validateNumber(v.valor).value })) })) });
  const pl = q.data?.pluggy;

  return (
    <div id="beneficios"><Panel title="Vale-refeição e alimentação" hint="cartões de benefício não têm Open Finance: informe aqui">
      {pl && (
        <div className={`callout ${pl.encontrados?.length || pl.erro ? "warn" : "info"}`}>
          {pl.encontrados?.length ? <>
            <b>A Pluggy já tem conector para: {pl.encontrados.map((c: any) => c.nome).join(", ")}.</b> Conecte em Conexões e,
            quando os lançamentos chegarem, desligue o benefício abaixo para não contar em dobro.</>
            : pl.erro ? <>Não consegui consultar a lista de conectores da Pluggy ({pl.erro}).</>
              : <>Conferido na Pluggy em {dateTime(pl.verificado_em)}: nenhum conector de benefício entre {pl.total_conectores} conectores. Confiro de novo toda semana.</>}
          {" "}<button className="btn ghost sm" onClick={() => check.mutate()} disabled={check.isPending}><RefreshCw size={13} /> Verificar agora</button>
        </div>
      )}

      {list.length === 0 && <p className="note">Nenhum benefício informado. Com ele, a receita do mês passa a incluir o crédito e o gasto com
        alimentação passa a mostrar o que você paga com o cartão; o resultado do mês não muda.</p>}

      {list.map((it, i) => (
        <fieldset key={i} className="benefit">
          <div className="toolbar">
            <label className="field">Nome<input className="input" value={it.nome} onChange={(e) => upd(i, { nome: e.target.value })} /></label>
            <label className="field">Emissor<input className="input" list="emissores" value={it.fornecedor} placeholder="Pluxee, Alelo…"
              onChange={(e) => upd(i, { fornecedor: e.target.value })} /></label>
            <label className="field">Dia do crédito<input className="input num" style={{ width: 70 }} inputMode="numeric" value={it.dia}
              onChange={(e) => upd(i, { dia: e.target.value.replace(/\D/g, "").slice(0, 2) })} /></label>
            <label className="field">Até<input className="input" type="month" value={it.ate} onChange={(e) => upd(i, { ate: e.target.value })} /></label>
            <label className="soft small" style={{ display: "flex", gap: 6, alignItems: "center", alignSelf: "end", height: 34 }}>
              <input type="checkbox" checked={it.ativo} onChange={(e) => upd(i, { ativo: e.target.checked })} /> ativo</label>
            <button className="btn ghost sm danger" style={{ alignSelf: "end" }} aria-label={`Remover ${it.nome}`}
              onClick={() => setItems(list.filter((_, k) => k !== i))}><Trash2 size={14} /></button>
          </div>
          <div className="small soft" style={{ margin: "8px 0 4px" }}>Valor mensal (um por reajuste)</div>
          {it.valores.map((v, j) => (
            <div key={j} className="toolbar" style={{ marginBottom: 6 }}>
              <span className="small soft" style={{ width: 40 }}>desde</span>
              <input className="input" type="month" value={v.desde} aria-label="Desde" onChange={(e) => updV(i, j, { desde: e.target.value })} />
              <MoneyInput value={v.valor} onChange={(x) => updV(i, j, { valor: x })} ariaLabel="Valor mensal" placeholder="0,00" allowNegative={false} required />
              {it.valores.length > 1 && <button className="btn ghost sm" aria-label="Remover valor"
                onClick={() => upd(i, { valores: it.valores.filter((_, k) => k !== j) })}><Trash2 size={13} /></button>}
            </div>))}
          <button className="btn ghost sm" onClick={() => upd(i, { valores: [...it.valores, { desde: thisMonth(), valor: "" }] })}>
            <Plus size={13} /> Reajuste</button>
        </fieldset>))}
      <datalist id="emissores">{EMISSORES.map((e) => <option key={e} value={e} />)}</datalist>

      <div className="toolbar" style={{ marginTop: 10 }}>
        <button className="btn" onClick={() => setItems([...list, blank(list.length + 1)])}><Plus size={14} /> Adicionar benefício</button>
        <button className="btn primary" disabled={!dirty || errors.length > 0 || save.isPending} onClick={submit}>Salvar</button>
        {dirty && <span className="small soft">alterações não salvas</span>}
      </div>

      {q.data?.ultimos?.length > 0 && <>
        <p className="note">Últimos 12 meses: {brl(q.data.creditos_12m)} em créditos. {q.data.premissa}</p>
        <div className="toolbar">{q.data.ultimos.map((c: any) => (
          <Chip key={`${c.id}${c.month}`}>{monthLabel(c.month)} · {c.nome} {brl(c.valor, 0)} em {date(c.date).slice(0, 5)}</Chip>))}</div>
      </>}
    </Panel></div>
  );
}
