import { QueryState } from "../components/QueryState";
import { DEMO } from "../demo";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { FileSpreadsheet } from "lucide-react";
import { api } from "../api";
import { Chip, Panel } from "../components/ui";
import { brl, date, today } from "../format";

/** Valores neutros; `result` pinta de vermelho só prejuízo (resultado desfavorável), nunca valores de bens, rendimentos ou despesas. */
const M = ({ v, result = false }: { v: number | null | undefined; result?: boolean }) => <span className={`num ${result && v !== null && v !== undefined && v < 0 ? "neg" : ""}`}>{v === null || v === undefined ? "—" : brl(v)}</span>;

export default function ImpostoRenda() {
  const now = today();
  const [ano, setAno] = useState(now.getMonth() >= 2 ? now.getFullYear() : now.getFullYear() - 1);
  const q = useQuery({ queryKey: ["ir", ano], queryFn: () => api<any>(`/api/ir?ano=${ano}`) });
  const r = q.data;
  if (!r) return <QueryState q={q} what="o imposto de renda">{() => null}</QueryState>;
  const ap = r.tributacao_exclusiva.aplicacoes;
  const rvMonths = r.renda_variavel.meses.filter((m: any) => m.resultado_acoes || m.resultado_etf || m.resultado_fii || m.nao_apuravel || m.darf);

  return (
    <>
      <section className="panel strip" aria-label="Resumo">
        <div><div className="lbl">Ano-base</div><div className="val">
          <select value={ano} onChange={(e) => setAno(Number(e.target.value))} style={{ font: "inherit", fontSize: 20, border: 0, background: "transparent" }}>
            {[0, 1, 2].map((k) => <option key={k} value={now.getFullYear() - k}>{now.getFullYear() - k}</option>)}
          </select></div>
          <div className="sub">declaração {r.exercicio} {r.parcial && <Chip tone="ochre">ano em andamento</Chip>}</div></div>
        <div><div className="lbl">Bens e direitos em 31/12</div><div className="val num" style={{ textAlign: "left" }}>{brl(r.total_bens, 0)}</div>
          <div className="sub">{r.bens_e_direitos.length} itens</div></div>
        <div><div className="lbl">Aplicações (cód. 06)</div><div className="val num" style={{ textAlign: "left" }}>{brl(ap.total_liquido, 0)}</div>
          <div className="sub">IR já retido {brl(ap.total_ir_retido)}</div></div>
        <div><div className="lbl">Deduções</div><div className="val num" style={{ textAlign: "left" }}>{brl(r.deducoes.saude + r.deducoes.instrucao, 0)}</div>
          <div className="sub">saúde {brl(r.deducoes.saude, 0)} · instrução {brl(r.deducoes.instrucao, 0)}</div></div>
        <div><div className="lbl">DARF renda variável</div><div className="val num" style={{ textAlign: "left" }}>{brl(r.renda_variavel.total_darf, 0)}</div>
          <div className="sub">código 6015</div></div>
      </section>

      <Panel title="Pendências para completar" tools={DEMO ? undefined : <a className="btn sm" href={`/api/ir.xlsx?ano=${ano}`}><FileSpreadsheet size={14} /> Excel</a>}>
        <ul className="assumptions" style={{ margin: 0 }}>{r.pendencias.map((p: string, i: number) => <li key={i}>{p}</li>)}</ul>
        <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>{r.aviso}</p>
      </Panel>

      <Panel title="Bens e direitos" flush hint="valores do ano anterior: copie da declaração passada">
        <div className="table-wrap" style={{ maxHeight: "none" }}>
          <table className="table"><thead><tr><th>Grupo/Cód.</th><th>Bem</th><th>Discriminação</th><th>CNPJ</th><th className="num">31/12/{ano - 1}</th><th className="num">31/12/{ano}</th><th>Origem</th></tr></thead>
            <tbody>{r.bens_e_direitos.map((b: any, i: number) => (
              <tr key={i}><td title={b.tipo}>{b.grupo}.{b.codigo}</td><td><b>{b.bem}</b>{!b.obrigatorio && <div className="muted" style={{ fontSize: 11 }}>opcional</div>}</td>
                <td className="soft" style={{ maxWidth: 380, whiteSpace: "normal" }}>{b.discriminacao}</td><td>{b.cnpj ?? <span className="muted">conferir</span>}</td>
                <td><M v={b.situacao_anterior} /></td><td>{b.pendente ? <Chip tone="ochre">custo pendente</Chip> : <M v={b.situacao_atual} />}
                  {b.valor_de_mercado != null && <div className="muted" style={{ fontSize: 11 }}>mercado {brl(b.valor_de_mercado, 0)}</div>}</td>
                <td className="muted" style={{ fontSize: 12 }}>{b.origem}</td></tr>
            ))}</tbody></table>
        </div>
      </Panel>

      <div className="grid g2">
        <Panel title="Tributação exclusiva — aplicações (cód. 06)" flush hint="declare o rendimento líquido">
          <table className="table"><thead><tr><th>Fonte pagadora</th><th>CNPJ</th><th className="num">Rend. bruto</th><th className="num">IR retido</th><th className="num">Líquido</th></tr></thead>
            <tbody>{ap.fontes.map((f: any, i: number) => (
              <tr key={i}><td>{f.fonte_pagadora}{f.estimado && <div className="muted" style={{ fontSize: 11 }}>parte estimada</div>}</td><td>{f.cnpj ?? "—"}</td>
                <td><M v={f.rendimento_bruto} /></td><td><M v={f.ir_retido} /></td><td><b><M v={f.rendimento_liquido} /></b></td></tr>
            ))}{r.tributacao_exclusiva.outros.map((o: any, i: number) => (
              <tr key={`o${i}`}><td>{o.fonte} (cód. {o.codigo})</td><td>—</td><td /><td /><td><M v={o.valor} /></td></tr>))}
            {!ap.fontes.length && <tr><td colSpan={5} className="muted">Nenhum resgate no ano.</td></tr>}</tbody></table>
        </Panel>
        <Panel title="Rendimentos isentos" flush>
          <table className="table"><thead><tr><th>Cód.</th><th>Tipo</th><th>Fonte / doador</th><th className="num">Valor</th></tr></thead>
            <tbody>{r.isentos.map((i: any, k: number) => (
              <tr key={k}><td>{i.codigo}</td><td>{i.tipo}</td><td>{i.fonte}{i.cpf_cnpj ? <div className="muted" style={{ fontSize: 11 }}>{i.cpf_cnpj}</div> : <div style={{ fontSize: 11 }}><Chip tone="ochre">CPF pendente</Chip></div>}</td><td><M v={i.valor} /></td></tr>
            ))}{!r.isentos.length && <tr><td colSpan={4} className="muted">Nenhum no ano.</td></tr>}</tbody></table>
        </Panel>
      </div>

      <div className="grid g2">
        <Panel title="Pagamentos efetuados (dedutíveis)" flush hint="farmácia e academia não deduzem">
          <table className="table"><thead><tr><th>Prestador</th><th>CPF/CNPJ</th><th className="num">Pago</th><th className="num">Reembolsado</th><th className="num">Dedutível</th></tr></thead>
            <tbody>{r.pagamentos.map((p: any, i: number) => (
              <tr key={i}><td>{p.prestador}<div className="muted" style={{ fontSize: 11 }}>{p.categoria}{p.reembolso_rateado ? " · reembolso rateado" : ""}</div></td>
                <td>{p.cpf_cnpj ?? <Chip tone="ochre">pendente</Chip>}</td><td><M v={p.pago} /></td><td><M v={p.reembolsado} /></td><td><b><M v={p.dedutivel} /></b></td></tr>
            ))}{!r.pagamentos.length && <tr><td colSpan={5} className="muted">Nenhum no ano.</td></tr>}</tbody></table>
        </Panel>
        <Panel title="Renda variável — operações comuns" flush>
          <table className="table"><thead><tr><th>Mês</th><th className="num">Resultado</th><th className="num">Base</th><th className="num">Imposto</th><th>DARF 6015</th></tr></thead>
            <tbody>{rvMonths.map((m: any) => (
              <tr key={m.mes}><td>{m.mes}</td><td><M result v={m.resultado_acoes + m.resultado_etf + m.resultado_fii} />{m.nao_apuravel > 0 && <div style={{ fontSize: 11 }}><Chip tone="ochre">custo pendente</Chip></div>}</td>
                <td><M v={m.base_tributavel} /></td><td><M v={m.imposto} /></td><td>{m.darf ? `${brl(m.darf.valor)} até ${date(m.darf.vencimento)}` : "—"}</td></tr>
            ))}{!rvMonths.length && <tr><td colSpan={5} className="muted">Sem vendas de ações/ETFs no ano.</td></tr>}</tbody></table>
          <p className="muted" style={{ fontSize: 12, padding: "8px 18px 12px", margin: 0 }}>{r.renda_variavel.nota}</p>
        </Panel>
      </div>

      {r.tributaveis_conferencia.length > 0 && (
        <Panel title="Rendimentos tributáveis recebidos (para conferir com o informe)" flush>
          <table className="table"><thead><tr><th>Fonte pagadora</th><th>CPF/CNPJ</th><th className="num">Salário líquido</th><th className="num">Bônus líquido</th><th className="num">Outros</th></tr></thead>
            <tbody>{r.tributaveis_conferencia.map((t: any, i: number) => (
              <tr key={i}><td>{t.fonte_pagadora}</td><td>{t.cpf_cnpj ?? "—"}</td><td><M v={t.salario_liquido} /></td><td><M v={t.bonus_liquido} /></td><td><M v={t.outros} /></td></tr>
            ))}</tbody></table>
        </Panel>
      )}
    </>
  );
}
