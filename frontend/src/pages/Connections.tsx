import { useQuery } from "@tanstack/react-query";
import { useApiMutation } from "../hooks/useApiMutation";
import { QueryState } from "../components/QueryState";

import { useState } from "react";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { api } from "../api";
import { Chip, Drawer, Empty, Money, Panel, useToast } from "../components/ui";
import { AutoSaveText } from "../components/MoneyInput";
import { PluggyForm, useIntegrations } from "../components/Integrations";
import { date, dateTime } from "../format";

declare global { interface Window { PluggyConnect: any } }

const STATUS_TONE: Record<string, any> = { UPDATED: "green", UPDATING: "ochre", LOGIN_ERROR: "red", OUTDATED: "red", WAITING_USER_INPUT: "ochre" };
const STATUS_LABEL: Record<string, string> = { UPDATED: "atualizado", UPDATING: "atualizando", LOGIN_ERROR: "precisa reconectar",
  OUTDATED: "desatualizado", WAITING_USER_INPUT: "aguardando você" };
const ACCOUNT_TYPE: Record<string, string> = { CHECKING_ACCOUNT: "conta corrente", SAVINGS_ACCOUNT: "poupança", CREDIT_CARD: "cartão de crédito",
  BANK: "conta", CREDIT: "cartão" };
const RUN_KIND: Record<string, string> = { pluggy: "bancos", market: "cotações", ledger: "razão", alerts: "alertas", health: "saúde" };

export default function Connections() {
  const toast = useToast();
  const [run, setRun] = useState<number | null>(null);
  const [manual, setManual] = useState("");
  const q = useQuery({ queryKey: ["connections"], queryFn: () => api<any>("/api/connections"), refetchInterval: 15_000 });
  const integ = useIntegrations();
  const pluggyOk = !!integ.data?.pluggy.configured;
  const sync = useApiMutation({ mutationFn: (body: any) => api<any>("/api/sync", { method: "POST", body }),
    successMessage: (r) => (r.started ? "Sincronização iniciada" : "Já existe uma em andamento") });
  const addItem = useApiMutation({ mutationFn: (itemId: string) => api("/api/items", { method: "POST", body: { itemId } }),
    successMessage: "Conexão adicionada, importando dados", invalidate: "all", onSuccess: () => setManual("") });
  const market = useApiMutation({ mutationFn: () => api<any>("/api/market/sync", { method: "POST" }),
    successMessage: (r) => (r.ok ? "Cotações e índices atualizados" : null), invalidate: "all",
    onSuccess: (r) => { if (!r.ok) toast(`Falhas: ${r.errors?.join("; ")}`, true); } });
  const rebuild = useApiMutation({ mutationFn: () => api("/api/rebuild", { method: "POST" }), successMessage: "Razão reconstruído", invalidate: "all" });

  const [pending, setPending] = useState<{ kind: "rebuild" } | { kind: "full"; id: string; name: string } | null>(null);
  const connect = async (itemId?: string) => {
    if (!window.PluggyConnect) { toast("O widget da Pluggy não carregou. Verifique a internet e recarregue a página.", true); return; }
    try {
      const t = await api<any>("/api/connect-token", { method: "POST", body: itemId ? { itemId } : {} });
      new window.PluggyConnect({
        connectToken: t.accessToken, includeSandbox: t.includeSandbox,
        ...(t.connectorIds.length && !itemId ? { connectorIds: t.connectorIds } : {}),
        ...(itemId ? { updateItem: itemId } : {}),
        onSuccess: (data: any) => addItem.mutate(data.item.id),
        onError: (e: any) => toast(`A conexão falhou: ${e?.message ?? e}`, true),
      }).init();
    } catch (e: any) { toast(e.message, true); }
  };
  const d = q.data;
  return (
    <>
      {pending && (
        <ConfirmDialog title={pending.kind === "rebuild" ? "Reprocessar o razão?" : "Fazer a releitura completa?"}
          itemName={pending.kind === "rebuild" ? "Todo o razão" : pending.name}
          confirmLabel={pending.kind === "rebuild" ? "Reprocessar" : "Reler tudo"} onCancel={() => setPending(null)}
          onConfirm={() => { if (pending.kind === "rebuild") rebuild.mutate(); else sync.mutate({ item_id: pending.id, full: true }); setPending(null); }}>
          {pending.kind === "rebuild" ? "Leva cerca de 1 minuto; os números ficam desatualizados até terminar." : "Busca todo o histórico de novo no banco; pode levar de 2 a 5 minutos."}
        </ConfirmDialog>
      )}
      {!d && <QueryState q={q} what="as conexões" layout="panel">{() => null}</QueryState>}
      {integ.data && !pluggyOk && (
        <Panel title="Passo 1: chave da Pluggy" hint="necessária uma única vez">
          <PluggyForm />
        </Panel>
      )}
      <Panel title={pluggyOk ? "Conectar bancos" : "Passo 2: conectar bancos"} hint="Open Finance pelo MeuPluggy, gratuito para uso pessoal (até 5 bancos)">
        <ol className="assumptions" style={{ marginBottom: 12 }}>
          <li>Em <a href="https://meu.pluggy.ai" target="_blank" rel="noreferrer">meu.pluggy.ai</a>, entre com o <b>mesmo e-mail</b> da sua conta Pluggy e autorize cada banco.</li>
          <li>Volte aqui, clique em <b>Conectar</b> e escolha <b>MeuPluggy</b>. Ele compartilha um banco por vez: repita para cada banco (Nubank, Inter…).</li>
          <li>A primeira importação traz até 12 meses e leva de 1 a 3 minutos por banco. Depois, o app atualiza sozinho a cada {d?.config.sync_hours ?? 4} horas.</li>
        </ol>
        <div className="toolbar">
          <button className="btn primary" onClick={() => connect()} disabled={!pluggyOk} title={pluggyOk ? undefined : "Cadastre a chave da Pluggy primeiro"}>Conectar</button>
        </div>
      </Panel>
      {d && d.items.length === 0 && pluggyOk && <Panel><Empty title="Nenhum banco conectado ainda">Depois de conectar, cada banco aparece aqui com as contas e o saldo lido.</Empty></Panel>}
      {d?.items.map((it: any) => (
        <Panel key={it.id} title={it.nickname ?? it.institution ?? it.id.slice(0, 8)}
          hint={it.institution && it.institution !== it.nickname ? `via ${it.institution}` : undefined}
          tools={<>
            <Chip tone={STATUS_TONE[it.status]}>{STATUS_LABEL[it.status] ?? it.status ?? "?"}</Chip>
            <button className="btn sm" onClick={() => setPending({ kind: "full", id: it.id, name: it.nickname ?? it.institution ?? it.id.slice(0, 8) })}>Releitura completa</button>
            {["LOGIN_ERROR", "OUTDATED", "WAITING_USER_INPUT"].includes(it.status) && <button className="btn sm primary" onClick={() => connect(it.id)}>Reconectar</button>}
          </>} flush>
          <dl className="kv" style={{ padding: "0 18px 10px" }}>
            <dt>Nome do banco</dt><dd><AutoSaveText value={it.nickname ?? ""} placeholder="ex.: Nubank" width={200} ariaLabel="Nome do banco"
              onSave={(v) => api(`/api/items/${it.id}`, { method: "PATCH", body: { nickname: v } })} />
              {!it.nickname && /pluggy/i.test(it.institution ?? "") && <div className="note">Dê o nome do banco: ele aparece na carteira e no imposto de renda no lugar de "MeuPluggy".</div>}</dd>
            <dt>Pluggy atualizou</dt><dd>{dateTime(it.source_updated_at)}; próxima atualização automática {dateTime(it.next_auto_sync_at)}</dd>
            <dt>Lido aqui</dt><dd>{dateTime(it.last_synced_at)} <Chip tone={it.last_sync_status === "ok" ? "green" : it.last_sync_status ? "ochre" : undefined}>{it.last_sync_status ?? "nunca"}</Chip></dd>
            <dt>Consentimento</dt><dd>válido até {date(it.consent_expires_at)}</dd>
            <dt>Produtos</dt><dd className="small">{(it.products ?? []).join(", ")}</dd>
          </dl>
          <div className="table-wrap"><table className="table"><thead><tr><th>Conta</th><th className="hide-sm">Tipo</th><th className="num">Saldo</th><th className="num hide-sm">Limite</th><th className="hide-sm">Transações lidas</th></tr></thead>
            <tbody>{it.accounts.map((a: any) => (
              <tr key={a.id}><td>{a.nickname ?? a.name} <span className="muted small">{a.number}</span></td><td className="hide-sm"><Chip>{ACCOUNT_TYPE[a.subtype ?? a.type] ?? a.subtype ?? a.type}</Chip></td>
                <td><Money v={a.type === "CREDIT" ? -(a.balance ?? 0) : a.balance} /></td><td className="hide-sm">{a.credit_limit ? <Money v={a.credit_limit} /> : ""}</td>
                <td className="soft hide-sm">{dateTime(a.last_tx_sync_at)}</td></tr>))}</tbody></table></div>
        </Panel>
      ))}
      <details className="panel">
        <summary><h2>Avançado</h2><span className="note">ações técnicas e histórico de execuções</span></summary>
        <div className="panel-body" style={{ display: "grid", gap: 14 }}>
          <div className="toolbar">
            <input className="input" style={{ width: 300 }} placeholder="Item ID do dashboard Pluggy" value={manual} onChange={(e) => setManual(e.target.value)} />
            <button className="btn" disabled={!manual} onClick={() => addItem.mutate(manual.trim())}>Adicionar por ID</button>
          </div>
          <div className="toolbar">
            <button className="btn" onClick={() => market.mutate()} disabled={market.isPending}>Atualizar cotações agora</button>
            <button className="btn" onClick={() => setPending({ kind: "rebuild" })} disabled={rebuild.isPending}>Reprocessar razão</button>
            <span className="note">Raramente necessário: o app faz os dois sozinho.</span>
          </div>
          {d && <p className="note" style={{ margin: 0 }}>Agendamento: bancos a cada {d.config.sync_hours} h; cotações diariamente às 19h45. Webhooks {d.config.webhooks_enabled ? "ativos" : "desativados (sem URL pública)"}.</p>}
        </div>
        <div className="table-wrap"><table className="table"><thead><tr><th>Início</th><th>Rotina</th><th className="hide-sm">Gatilho</th><th>Situação</th><th className="hide-sm">Resumo</th></tr></thead>
          <tbody>{d?.runs.map((r: any) => (
            <tr key={r.id} className="clickable" onClick={() => setRun(r.id)}>
              <td className="num" style={{ textAlign: "left" }}>{dateTime(r.started_at)}</td><td>{RUN_KIND[r.kind] ?? r.kind}</td><td className="soft hide-sm">{r.trigger}</td>
              <td><Chip tone={r.status === "ok" ? "green" : r.status === "running" ? "ochre" : "red"}>{r.status}</Chip></td>
              <td className="small soft hide-sm">{r.error ?? summary(r)}</td></tr>))}</tbody></table></div>
      </details>
      {run && <RunDrawer id={run} onClose={() => setRun(null)} />}
    </>
  );
}

function summary(r: any) {
  const s = r.stats ?? {};
  if (r.kind === "pluggy") return `${s.accounts ?? 0} contas, ${s.transactions ?? 0} transações (${s.tx_new ?? 0} novas, ${s.tx_removed ?? 0} removidas), ${s.investments ?? 0} investimentos`;
  if (r.kind === "ledger") return s.counts ? `${Object.entries(s.counts).filter(([k]) => k === "changed" || k === "created").map(([k, v]) => `${v} ${k === "changed" ? "alterações" : "novos"}`).join(", ") || "sem mudanças"}` : "";
  if (r.kind === "market") return s.errors?.length ? `${s.errors.length} falhas` : "séries atualizadas";
  return "";
}

function RunDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const q = useQuery({ queryKey: ["run", id], queryFn: () => api<any[]>(`/api/runs/${id}/events`) });
  if (!q.data) return <Drawer title={`Execução ${id}`} onClose={onClose}><QueryState q={q} what="os eventos da execução" layout="panel">{() => null}</QueryState></Drawer>;
  return (
    <Drawer title={`Execução ${id}`} onClose={onClose}>
      {(q.data ?? []).length === 0 && <p className="muted">Sem eventos registrados: execução sem avisos.</p>}
      {(q.data ?? []).map((e, i) => (
        <div key={i} className="list-row"><Chip tone={e.level === "error" ? "red" : e.level === "warn" ? "ochre" : undefined}>{e.level}</Chip>
          <div className="grow"><div className="t">{e.step}</div><div className="s" style={{ whiteSpace: "normal" }}>{e.message}</div></div></div>))}
    </Drawer>
  );
}
