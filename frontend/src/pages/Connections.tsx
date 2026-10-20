import { useQuery } from "@tanstack/react-query";
import { useApiMutation } from "../hooks/useApiMutation";
import { QueryState } from "../components/QueryState";

import { useState } from "react";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { api } from "../api";
import { Chip, Drawer, Money, Panel, useToast } from "../components/ui";
import { date, dateTime } from "../format";

declare global { interface Window { PluggyConnect: any } }

const STATUS_TONE: Record<string, any> = { UPDATED: "green", UPDATING: "ochre", LOGIN_ERROR: "red", OUTDATED: "red", WAITING_USER_INPUT: "ochre" };

export default function Connections() {
  const toast = useToast();
  const [run, setRun] = useState<number | null>(null);
  const [manual, setManual] = useState("");
  const q = useQuery({ queryKey: ["connections"], queryFn: () => api<any>("/api/connections"), refetchInterval: 15_000 });
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
      <Panel title="Conectar bancos" hint="Open Finance pelo MeuPluggy, gratuito para uso pessoal (até 5 bancos)">
        <ol className="assumptions" style={{ marginBottom: 12 }}>
          <li>Autorize cada banco em <a href="https://meu.pluggy.ai" target="_blank" rel="noreferrer">meu.pluggy.ai</a> com o mesmo e-mail do dashboard Pluggy.</li>
          <li>Clique em Conectar e escolha MeuPluggy. O MeuPluggy compartilha um banco por vez: repita Conectar para cada banco (Nubank, Inter…).</li>
        </ol>
        <div className="toolbar">
          <button className="btn primary" onClick={() => connect()}>Conectar</button>
          <input className="input" style={{ width: 320 }} placeholder="ou cole um Item ID do dashboard Pluggy" value={manual} onChange={(e) => setManual(e.target.value)} />
          <button className="btn" disabled={!manual} onClick={() => addItem.mutate(manual.trim())}>Adicionar</button>
          <span style={{ flex: 1 }} />
          <button className="btn" onClick={() => market.mutate()} disabled={market.isPending}>Atualizar cotações</button>
          <button className="btn" onClick={() => setPending({ kind: "rebuild" })} disabled={rebuild.isPending}>Reprocessar razão</button>
        </div>
      </Panel>
      {d?.items.map((it: any) => (
        <Panel key={it.id} title={it.nickname ?? it.institution ?? it.id.slice(0, 8)}
          hint={<>Item {it.id}</>}
          tools={<>
            <Chip tone={STATUS_TONE[it.status]}>{it.status ?? "?"}</Chip>
            <button className="btn sm" onClick={() => setPending({ kind: "full", id: it.id, name: it.nickname ?? it.institution ?? it.id.slice(0, 8) })}>Releitura completa</button>
            {["LOGIN_ERROR", "OUTDATED", "WAITING_USER_INPUT"].includes(it.status) && <button className="btn sm primary" onClick={() => connect(it.id)}>Reconectar</button>}
          </>} flush>
          <dl className="kv" style={{ padding: "0 18px 10px" }}>
            <dt>Pluggy atualizou</dt><dd>{dateTime(it.source_updated_at)}; próxima atualização automática {dateTime(it.next_auto_sync_at)}</dd>
            <dt>Lido aqui</dt><dd>{dateTime(it.last_synced_at)} <Chip tone={it.last_sync_status === "ok" ? "green" : it.last_sync_status ? "ochre" : undefined}>{it.last_sync_status ?? "nunca"}</Chip></dd>
            <dt>Consentimento</dt><dd>válido até {date(it.consent_expires_at)}</dd>
            <dt>Produtos</dt><dd className="small">{(it.products ?? []).join(", ")}</dd>
          </dl>
          <table className="table"><thead><tr><th>Conta</th><th>Tipo</th><th className="num">Saldo</th><th className="num">Limite</th><th>Transações lidas</th></tr></thead>
            <tbody>{it.accounts.map((a: any) => (
              <tr key={a.id}><td>{a.nickname ?? a.name} <span className="muted small">{a.number}</span></td><td><Chip>{a.subtype ?? a.type}</Chip></td>
                <td><Money v={a.type === "CREDIT" ? -(a.balance ?? 0) : a.balance} /></td><td>{a.credit_limit ? <Money v={a.credit_limit} /> : ""}</td>
                <td className="soft">{dateTime(a.last_tx_sync_at)}</td></tr>))}</tbody></table>
        </Panel>
      ))}
      <Panel title="Execuções" hint="log técnico de sincronizações, mercado e razão" flush>
        <table className="table"><thead><tr><th>Início</th><th>Rotina</th><th>Gatilho</th><th>Situação</th><th>Resumo</th></tr></thead>
          <tbody>{d?.runs.map((r: any) => (
            <tr key={r.id} className="clickable" onClick={() => setRun(r.id)}>
              <td className="num" style={{ textAlign: "left" }}>{dateTime(r.started_at)}</td><td>{r.kind}</td><td className="soft">{r.trigger}</td>
              <td><Chip tone={r.status === "ok" ? "green" : r.status === "running" ? "ochre" : "red"}>{r.status}</Chip></td>
              <td className="small soft">{r.error ?? summary(r)}</td></tr>))}</tbody></table>
      </Panel>
      {d && <p className="note">Agendamento: Pluggy a cada {d.config.sync_hours} h; cotações diariamente às 19h45. Webhooks {d.config.webhooks_enabled ? "ativos" : "desativados (sem URL pública)"}.</p>}
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
