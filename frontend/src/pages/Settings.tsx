import { useQuery } from "@tanstack/react-query";
import { useApiMutation } from "../hooks/useApiMutation";
import { QueryState } from "../components/QueryState";
import { AutoSaveCheck, AutoSaveSelect, AutoSaveText, IntInput, MoneyInput, NumberInput } from "../components/MoneyInput";
import { parseIntStrict, validateNumber } from "../format";
import { useState } from "react";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Trash2 } from "lucide-react";
import { api } from "../api";
import { Chip, Money, Panel, useToast } from "../components/ui";
import { EmailForm, PluggyForm } from "../components/Integrations";
import { DEMO } from "../demo";
import { brl, date, dateTime, parseBRL, pct } from "../format";

const CLASSES = ["RF Pós", "RF Pré", "RF IPCA+", "Tesouro Selic", "Tesouro Prefixado", "Tesouro IPCA+", "ETF Renda Fixa",
  "Ações BR", "ETF Ações BR", "FIIs", "ETF Internacional", "Fundos", "Previdência", "Cripto", "COE", "Outros"];

export default function SettingsPage() {
  const conns = useQuery({ queryKey: ["connections"], queryFn: () => api<any>("/api/connections") });
  const assets = useQuery({ queryKey: ["assets"], queryFn: () => api<any[]>("/api/assets") });
  const manual = useQuery({ queryKey: ["manual"], queryFn: () => api<any[]>("/api/manual-assets") });
  const [m, setM] = useState({ kind: "asset", name: "", asset_class: "", value: "", acquired_at: "", growth: "" });
  const saveAcc = (id: number, body: any) => api(`/api/accounts/${id}`, { method: "PATCH", body });
  const saveAsset = (id: number, body: any) => api(`/api/assets/${id}`, { method: "PATCH", body });
  const ASSET_MSG = "Ativo atualizado. Rode “Atualizar cotações” em Conexões se trocou o ticker";
  const vValue = validateNumber(m.value, { required: true, allowNegative: false });
  const [assetToDelete, setAssetToDelete] = useState<any>(null);
  const vGrowth = validateNumber(m.growth, { min: -50, max: 50 });
  const addManual = useApiMutation({ mutationFn: () => api("/api/manual-assets", { method: "POST", body: { kind: m.kind, name: m.name,
      asset_class: m.asset_class || null, value: vValue.value, acquired_at: m.acquired_at || null,
      growth_aa: vGrowth.value === null ? null : vGrowth.value / 100 } }),
    successMessage: "Item salvo no balanço", invalidate: "all", onSuccess: () => setM({ ...m, name: "", value: "", acquired_at: "", growth: "" }) });
  const delManual = useApiMutation({ mutationFn: (id: number) => api(`/api/manual-assets/${id}`, { method: "DELETE" }), invalidate: "all", successMessage: "Item removido" });
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: () => api<any>("/api/alerts/status") });
  const toast = useToast();
  const [editMail, setEditMail] = useState(false);
  const testMail = useApiMutation({ mutationFn: () => api<any>("/api/alerts/test", { method: "POST" }), invalidate: [["alerts"]],
    onSuccess: (r) => toast(r.ok ? "E-mail de teste enviado" : `Falhou: ${r.erro}`, !r.ok) });
  const accounts = (conns.data?.items ?? []).flatMap((i: any) => i.accounts.map((a: any) => ({ ...a, inst: i.institution })));
  return (
    <>
      {assetToDelete && (
        <ConfirmDialog title="Excluir este item?" itemName={assetToDelete.name} confirmLabel="Excluir item" danger
          onCancel={() => setAssetToDelete(null)} onConfirm={() => { delManual.mutate(assetToDelete.id); setAssetToDelete(null); }}>{null}</ConfirmDialog>
      )}
      {!conns.data && <QueryState q={conns} what="as contas" layout="panel">{() => null}</QueryState>}
      {!assets.data && <QueryState q={assets} what="os ativos" layout="panel">{() => null}</QueryState>}
      {!manual.data && <QueryState q={manual} what="os ativos manuais" layout="panel">{() => null}</QueryState>}
      <Panel title="Conexão com os bancos (Pluggy)" hint="chave de leitura do Open Finance; fica só neste computador">
        <PluggyForm />
      </Panel>

      <Panel title="Alertas por e-mail" hint="resumo diário de alertas novos e fechamento do mês no dia 1">
        {alerts.data?.configurado && !editMail ? (
          <p style={{ margin: 0 }}>Enviando para <b>{alerts.data.para}</b> às {alerts.data.horario}h.{" "}
            <button className="btn sm" onClick={() => testMail.mutate()}>Enviar teste</button>{" "}
            <button className="btn sm ghost" onClick={() => setEditMail(true)}>Alterar</button></p>
        ) : (
          <>
            {!alerts.data?.configurado && <p className="note" style={{ marginTop: 0 }}>Opcional. Sem e-mail, os alertas continuam na tela de Revisão.</p>}
            <EmailForm />
          </>
        )}
        {alerts.data?.ultimos?.length > 0 && <table className="table" style={{ marginTop: 8 }}><tbody>{alerts.data.ultimos.map((n: any, i: number) => (
          <tr key={i}><td className="soft small">{dateTime(n.em)}</td><td>{n.assunto}</td><td>{n.status === "sent" ? <Chip tone="green">enviado</Chip> : <Chip tone="red">erro</Chip>}</td></tr>))}</tbody></table>}
      </Panel>

      <Panel title="Contas" hint="apelidos e o que entra no patrimônio" flush>
        <table className="table"><thead><tr><th>Conta</th><th>Apelido</th><th>Finalidade</th><th>No patrimônio</th></tr></thead>
          <tbody>{accounts.map((a: any) => (
            <tr key={a.id}><td>{a.name} <span className="muted small">{a.inst}</span></td>
              <td><AutoSaveText value={a.nickname ?? ""} placeholder={a.name} ariaLabel={`Apelido de ${a.name}`} onSave={(v) => saveAcc(a.id, { nickname: v })} /></td>
              <td><AutoSaveSelect value={a.purpose ?? ""} onSave={(v) => saveAcc(a.id, { purpose: v })}>
                <option value="">—</option><option value="corrente">Dia a dia</option><option value="reserva">Reserva</option><option value="cartao">Cartão principal</option><option value="outro">Outro</option></AutoSaveSelect></td>
              <td><AutoSaveCheck checked={!!a.include_in_net_worth} ariaLabel="Incluir no patrimônio" onSave={(v) => saveAcc(a.id, { include_in_net_worth: v })} /></td>
            </tr>))}</tbody></table>
      </Panel>
      <Panel title="Ativos e classificação" hint="corrija classe, ticker ou proxy de risco; sua escolha não é sobrescrita" flush>
        <div className="table-wrap"><table className="table"><thead><tr><th>Ativo</th><th>Classe</th><th>Ticker Yahoo</th><th>Proxy de risco</th><th>FGC</th><th /></tr></thead>
          <tbody>{(assets.data ?? []).map((a) => (
            <tr key={a.id}><td><div className="strong" style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</div><div className="small muted">{a.key}</div></td>
              <td><AutoSaveSelect value={a.asset_class} successMessage={ASSET_MSG} onSave={(v) => saveAsset(a.id, { asset_class: v })}>
                {CLASSES.map((c) => <option key={c}>{c}</option>)}</AutoSaveSelect></td>
              <td><AutoSaveText width={120} ariaLabel="Ticker Yahoo" value={a.yahoo_symbol ?? ""} onSave={(v) => saveAsset(a.id, { yahoo_symbol: v || null })} /></td>
              <td><AutoSaveText width={120} ariaLabel="Proxy de risco" value={a.risk_proxy ?? ""} onSave={(v) => saveAsset(a.id, { risk_proxy: v || null })} /></td>
              <td><AutoSaveCheck checked={!!a.fgc_covered} ariaLabel="Coberto pelo FGC" onSave={(v) => saveAsset(a.id, { fgc_covered: v })} /></td>
              <td>{a.origin === "user" && <Chip tone="green">ajustado</Chip>}</td></tr>))}</tbody></table></div>
      </Panel>
      <Panel title="Ativos e passivos fora do Open Finance" hint="imóvel, veículo, conta não conectada, dívida informal">
        {(manual.data ?? []).map((x) => <ManualRow key={x.id} x={x} onDelete={() => setAssetToDelete(x)} />)}
        <div className="toolbar" style={{ marginTop: 10 }}>
          <select className="select" value={m.kind} onChange={(e) => setM({ ...m, kind: e.target.value })}><option value="asset">Ativo</option><option value="liability">Passivo</option></select>
          <input className="input" placeholder="Nome" value={m.name} onChange={(e) => setM({ ...m, name: e.target.value })} />
          <input className="input" placeholder="Classe (opcional)" value={m.asset_class} onChange={(e) => setM({ ...m, asset_class: e.target.value })} />
          <MoneyInput width={130} placeholder="Valor" ariaLabel="Valor" allowNegative={false} value={m.value} onChange={(v) => setM({ ...m, value: v })} />
          <input className="input" type="date" value={m.acquired_at} onChange={(e) => setM({ ...m, acquired_at: e.target.value })} aria-label="Data de aquisição" title="Data de aquisição (antes dela o item não entra no patrimônio)" />
          <NumberInput width={72} min={-50} max={50} placeholder="% a.a." ariaLabel="Atualização anual em %" value={m.growth} onChange={(v) => setM({ ...m, growth: v })} />
          <button className="btn primary" disabled={!m.name || !!vValue.error || !!vGrowth.error || addManual.isPending} onClick={() => addManual.mutate()}>Adicionar</button>
        </div>
        <p className="note">Data de aquisição: antes dela o item não entra no histórico do patrimônio. % a.a.: valorização (imóvel, ex.: 5) ou depreciação (veículo, ex.: −10) aplicada entre as atualizações.</p>
      </Panel>
      {!DEMO && <Panel title="Exportação">
        <div className="toolbar">
          <a className="btn" href="/api/export.xlsx">Excel com razão, DRE, DFC, balanço e carteira</a>
          <a className="btn" href="/api/export.csv">Razão em CSV</a>
        </div>
        <p className="note">O Excel é bom para puxar na sua planilha via Power Query (Dados &gt; Obter dados &gt; De arquivo).</p>
      </Panel>}
    </>
  );
}

function ManualRow({ x, onDelete }: { x: any; onDelete: () => void }) {
  const [v, setV] = useState("");
  const upd = useApiMutation({
    mutationFn: (value: number) => api(`/api/manual-assets/${x.id}`, { method: "PUT", body: { kind: x.kind, name: x.name, asset_class: x.asset_class,
      value, as_of: null, notes: x.notes, active: x.active, acquired_at: x.acquired_at, growth_aa: x.growth_aa } }),
    successMessage: "Valor atualizado (o anterior fica no histórico)", invalidate: "all", onSuccess: () => setV(""),
  });
  const parsed = parseBRL(v);
  return (
    <div className="list-row" style={{ flexWrap: "wrap" }}><Chip tone={x.kind === "asset" ? "green" : "red"}>{x.kind === "asset" ? "ativo" : "passivo"}</Chip>
      <div className="grow"><div className="t">{x.name}</div>
        <div className="s">{[x.asset_class, `informado ${brl(x.value, 0)} em ${date(x.as_of)}`, x.acquired_at && `adquirido em ${date(x.acquired_at)}`,
          x.growth_aa ? `${x.growth_aa > 0 ? "+" : ""}${pct(x.growth_aa, 1)} a.a.` : null, x.historico?.length > 1 && `${x.historico.length} atualizações`].filter(Boolean).join(" · ")}</div></div>
      <Money v={x.kind === "asset" ? (x.valor_atual ?? x.value) : -(x.valor_atual ?? x.value)} />
      <MoneyInput width={120} allowNegative={false} placeholder="novo valor" ariaLabel={`Novo valor de ${x.name}`} value={v} onChange={setV} />
      <button className="btn sm" disabled={!parsed || upd.isPending} onClick={() => parsed && upd.mutate(parsed)}>Atualizar</button>
      <button className="btn ghost sm danger" onClick={onDelete} aria-label="Remover"><Trash2 size={14} /></button></div>
  );
}
