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
import { date, dateTime } from "../format";

const CLASSES = ["RF Pós", "RF Pré", "RF IPCA+", "Tesouro Selic", "Tesouro Prefixado", "Tesouro IPCA+", "ETF Renda Fixa",
  "Ações BR", "ETF Ações BR", "FIIs", "ETF Internacional", "Fundos", "Previdência", "Cripto", "COE", "Outros"];

export default function SettingsPage() {
  const conns = useQuery({ queryKey: ["connections"], queryFn: () => api<any>("/api/connections") });
  const assets = useQuery({ queryKey: ["assets"], queryFn: () => api<any[]>("/api/assets") });
  const manual = useQuery({ queryKey: ["manual"], queryFn: () => api<any[]>("/api/manual-assets") });
  const [m, setM] = useState({ kind: "asset", name: "", asset_class: "", value: "" });
  const saveAcc = (id: number, body: any) => api(`/api/accounts/${id}`, { method: "PATCH", body });
  const saveAsset = (id: number, body: any) => api(`/api/assets/${id}`, { method: "PATCH", body });
  const ASSET_MSG = "Ativo atualizado. Rode “Atualizar cotações” em Conexões se trocou o ticker";
  const vValue = validateNumber(m.value, { required: true, allowNegative: false });
  const [assetToDelete, setAssetToDelete] = useState<any>(null);
  const addManual = useApiMutation({ mutationFn: () => api("/api/manual-assets", { method: "POST", body: { ...m, value: vValue.value } }),
    successMessage: "Item salvo no balanço", invalidate: "all", onSuccess: () => setM({ ...m, name: "", value: "" }) });
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
        {(manual.data ?? []).map((x) => (
          <div key={x.id} className="list-row"><Chip tone={x.kind === "asset" ? "green" : "red"}>{x.kind === "asset" ? "ativo" : "passivo"}</Chip>
            <div className="grow"><div className="t">{x.name}</div><div className="s">{x.asset_class ?? ""} em {date(x.as_of)}</div></div>
            <Money v={x.kind === "asset" ? x.value : -x.value} />
            <button className="btn ghost sm danger" onClick={() => setAssetToDelete(x)} aria-label="Remover"><Trash2 size={14} /></button></div>))}
        <div className="toolbar" style={{ marginTop: 10 }}>
          <select className="select" value={m.kind} onChange={(e) => setM({ ...m, kind: e.target.value })}><option value="asset">Ativo</option><option value="liability">Passivo</option></select>
          <input className="input" placeholder="Nome" value={m.name} onChange={(e) => setM({ ...m, name: e.target.value })} />
          <input className="input" placeholder="Classe (opcional)" value={m.asset_class} onChange={(e) => setM({ ...m, asset_class: e.target.value })} />
          <MoneyInput width={130} placeholder="Valor" ariaLabel="Valor" allowNegative={false} value={m.value} onChange={(v) => setM({ ...m, value: v })} />
          <button className="btn primary" disabled={!m.name || !!vValue.error || addManual.isPending} onClick={() => addManual.mutate()}>Adicionar</button>
        </div>
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
