import { QueryState } from "../components/QueryState";
import { useQuery } from "@tanstack/react-query";
import { useApiMutation } from "../hooks/useApiMutation";
import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import { api } from "../api";
import { Chip, Panel } from "../components/ui";
import { brl, date, dateTime, pct, RULE_SOURCE } from "../format";

type Check = { id: string; grupo: string; titulo: string; status: string; resumo: string; detalhes: any[]; n_detalhes: number; metricas: any };

const TONE: Record<string, "green" | "red" | "ochre" | "blue"> = { ok: "green", falha: "red", atencao: "ochre", info: "blue" };
const LABEL: Record<string, string> = { ok: "OK", falha: "Falha", atencao: "Atenção", info: "Info" };
const MONEY = /valor|saldo|total|soma|diferenca|anterior|fatura|aplicado|resgatado|comprado|vendido|lancado|limite/;
const HEAD: Record<string, string> = {
  conexao: "Conexão", problema: "Problema", cartao: "Cartão", conta: "Conta", vencimento: "Vencimento",
  total_fatura: "Total da fatura", anterior: "Fatura anterior", soma_lancamentos: "Soma dos lançamentos", diferenca: "Diferença",
  saldo_informado: "Saldo informado", ultima_fatura: "Última fatura", lancado_depois_do_fechamento: "Depois do fechamento",
  saldo_atual: "Saldo atual", menor_saldo_reconstruido: "Menor saldo reconstruído", em: "Em", limite_cheque_especial: "Cheque especial",
  dias: "Dias", de: "De", ate: "Até", aplicado_no_banco: "Aplicado no banco", comprado_na_corretora: "Comprado na corretora",
  resgatado_no_banco: "Resgatado no banco", vendido_na_corretora: "Vendido na corretora", data: "Data", valor: "Valor",
  descricao: "Descrição", serie: "Série", soma_eventos: "Soma no razão", variacao_saldo: "Variação do saldo",
};

function cell(k: string, v: any) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number" && MONEY.test(k)) return <span className={`num ${v < 0 ? "neg" : ""}`}>{brl(v)}</span>;
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v)) return date(v);
  return String(v);
}

function Details({ rows }: { rows: any[] }) {
  if (!rows.length) return null;
  const cols = Array.from(new Set(rows.flatMap((r) => Object.keys(r))));
  return (
    <div className="table-wrap" style={{ maxHeight: 320 }}>
      <table className="table"><thead><tr>{cols.map((c) => <th key={c}>{HEAD[c] ?? c}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}>{cols.map((c) => <td key={c}>{cell(c, r[c])}</td>)}</tr>)}</tbody></table>
    </div>
  );
}

export default function SaudeDados() {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const q = useQuery({ queryKey: ["data-health"], queryFn: () => api<any>("/api/data-health") });
  const run = useApiMutation({ mutationFn: () => api("/api/data-health/run", { method: "POST" }), invalidate: [["data-health"]], successMessage: "Verificação concluída" });
  const d = q.data;
  if (!d) return <QueryState q={q} what="a saúde dos dados">{() => null}</QueryState>;
  const u = d.ultima;
  const clf = d.classificador || {};
  const checks: Check[] = u?.verificacoes ?? [];
  const groups = Array.from(new Set(checks.map((c) => c.grupo)));
  const cnt = (st: string) => checks.filter((c) => c.status === st).length;

  return (
    <>
      <section className="panel strip" aria-label="Resumo">
        <div><div className="lbl">Situação geral</div><div className="val">{u ? <Chip tone={TONE[u.status]}>{LABEL[u.status]}</Chip> : "—"}</div>
          <div className="sub">{u ? `verificado ${dateTime(u.em)}` : "ainda não rodou"}</div></div>
        <div><div className="lbl">Conferências OK</div><div className="val">{cnt("ok")} / {checks.length}</div>
          <div className="sub">{cnt("falha")} falha(s), {cnt("atencao")} de atenção</div></div>
        <div><div className="lbl">Classificador</div><div className="val">{clf.habilitado ? "ativo" : "inativo"}</div>
          <div className="sub">{clf.validacao?.precisao_no_limiar != null ? `${pct(clf.validacao.precisao_no_limiar, 0)} de acerto na validação` : clf.motivo ?? "—"}</div></div>
        <div><div className="lbl">Reclassificados pelo modelo</div><div className="val">{clf.reclassificados ?? 0}</div>
          <div className="sub">{clf.confirmados ?? 0} confirmados · {clf.amostras ?? 0} exemplos</div></div>
      </section>

      {u?.historico?.length > 1 && (
        <Panel title="Últimas verificações" hint="cada barra é uma rodada (a cada sincronização)">
          <div style={{ display: "flex", gap: 3, alignItems: "flex-end", height: 26 }}>
            {u.historico.map((h: any, i: number) => (
              <span key={i} title={`${dateTime(h.em)} · ${LABEL[h.status] ?? h.status}`} style={{ flex: 1, height: "100%", borderRadius: 2,
                background: h.status === "falha" ? "var(--debit)" : h.status === "atencao" ? "var(--ochre)" : "var(--ledger)" }} />
            ))}
          </div>
        </Panel>
      )}

      {groups.map((g) => (
        <Panel key={g} title={g} flush tools={g === groups[0] ? (
          <button className="btn sm" onClick={() => run.mutate()} disabled={run.isPending}><RefreshCw size={14} /> {run.isPending ? "Verificando…" : "Verificar agora"}</button>) : undefined}>
          <table className="table">
            <tbody>
              {checks.filter((c) => c.grupo === g).map((c) => (
                <Fragment key={c.id}>
                  <tr style={{ cursor: c.detalhes.length ? "pointer" : "default" }} onClick={() => c.detalhes.length && setOpen((o) => ({ ...o, [c.id]: !o[c.id] }))}>
                    <td style={{ width: 22 }}>{c.detalhes.length ? (open[c.id] ? <ChevronDown size={14} /> : <ChevronRight size={14} />) : null}</td>
                    <td style={{ width: 92 }}><Chip tone={TONE[c.status]}>{LABEL[c.status]}</Chip></td>
                    <td><b>{c.titulo}</b><div className="soft" style={{ fontSize: 12.5 }}>{c.resumo}</div></td>
                  </tr>
                  {open[c.id] && <tr><td /><td colSpan={2} style={{ paddingTop: 0 }}><Details rows={c.detalhes} />
                    {c.n_detalhes > c.detalhes.length && <p className="muted" style={{ fontSize: 12 }}>mostrando {c.detalhes.length} de {c.n_detalhes}</p>}</td></tr>}
                </Fragment>
              ))}
            </tbody>
          </table>
        </Panel>
      ))}

      <Panel title="Classificador treinado nas suas decisões" hint={clf.treinado_em ? `treinado ${dateTime(clf.treinado_em)}` : undefined}>
        <p className="soft" style={{ marginTop: 0 }}>
          Aprende com seus ajustes, regras e comerciantes (peso maior) e com palavras-chave de alta confiança. Só age onde a
          classificação atual é fraca (categoria genérica da Pluggy) e quando tem ≥ {pct(clf.limiar ?? 0.8, 0)} de certeza; nunca
          muda ajuste manual, regra, conciliação nem Pix para pessoa física. Só fica ativo se acertar ≥ 90% nos lançamentos que não viu.
        </p>
        {clf.validacao && (
          <p>Validação cruzada: acurácia {pct(clf.validacao.acuracia, 0)}; acima do limiar acerta {pct(clf.validacao.precisao_no_limiar, 0)}
            {" "}e cobre {pct(clf.validacao.cobertura_no_limiar, 0)} dos casos. {clf.classes} categorias, {clf.decisoes_suas} decisões suas.</p>
        )}
        {!clf.habilitado && clf.motivo && <p><Chip tone="ochre">inativo</Chip> {clf.motivo}</p>}
        {clf.exemplos?.length > 0 && (
          <div className="table-wrap" style={{ maxHeight: 360 }}>
            <table className="table"><thead><tr><th>Data</th><th>Descrição</th><th className="num">Valor</th><th>Antes</th><th>Agora</th><th className="num">Certeza</th><th>Termos que pesaram</th></tr></thead>
              <tbody>{clf.exemplos.map((e: any) => (
                <tr key={e.tx_id}><td>{date(e.data)}</td><td>{e.descricao}</td><td className={`num ${e.valor < 0 ? "neg" : ""}`}>{brl(e.valor)}</td>
                  <td className="soft">{e.de}</td><td><b>{e.para}</b></td><td className="num">{pct(e.probabilidade, 0)}</td><td className="soft">{e.termos.join(", ")}</td></tr>
              ))}</tbody></table>
          </div>
        )}
        <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>Lançamentos alterados aparecem com origem “{RULE_SOURCE.modelo}” no razão; corrija qualquer um e o modelo aprende na próxima reconstrução.</p>
      </Panel>
    </>
  );
}
