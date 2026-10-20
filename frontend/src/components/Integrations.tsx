import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink } from "lucide-react";
import { api } from "../api";
import { useApiMutation } from "../hooks/useApiMutation";
import { useToast } from "./ui";

export type IntegrationsView = {
  pluggy: { client_id: string; has_secret: boolean; configured: boolean; origin: "app" | "env" | null };
  email: { smtp_user: string; has_password: boolean; alert_email_to: string; configured: boolean; host: string; port: number; origin: "app" | "env" | null };
};

export const useIntegrations = () =>
  useQuery({ queryKey: ["integrations"], queryFn: () => api<IntegrationsView>("/api/integrations") });

/** Chave da Pluggy, digitada na tela (sem editar .env nem reiniciar). Testa antes de dizer que deu certo. */
export function PluggyForm({ compact = false, onDone }: { compact?: boolean; onDone?: () => void }) {
  const toast = useToast();
  const q = useIntegrations();
  const [cid, setCid] = useState<string | null>(null);
  const [secret, setSecret] = useState("");
  const cur = q.data?.pluggy;
  const save = useApiMutation({
    mutationFn: async () => {
      await api("/api/integrations", { method: "PUT", body: { pluggy_client_id: cid ?? cur?.client_id ?? "", pluggy_client_secret: secret || null } });
      return api<{ ok: boolean; erro?: string }>("/api/integrations/pluggy/test", { method: "POST" });
    },
    invalidate: [["integrations"], ["onboarding"]],
    onSuccess: (r) => {
      if (r.ok) { toast("Chave da Pluggy validada"); setSecret(""); setCid(null); onDone?.(); }
      else toast(`A Pluggy recusou a chave: ${r.erro}`, true);
    },
  });
  const id = cid ?? cur?.client_id ?? "";
  const canSave = !!id.trim() && (!!secret.trim() || !!cur?.has_secret);
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (canSave) save.mutate(); }} style={{ display: "grid", gap: 10 }}>
      {!compact && (
        <ol className="assumptions">
          <li>Crie uma conta gratuita em <a href="https://dashboard.pluggy.ai" target="_blank" rel="noreferrer">dashboard.pluggy.ai <ExternalLink size={11} /></a>.</li>
          <li>Em <b>Applications</b>, crie uma aplicação e copie o <b>Client ID</b> e o <b>Client Secret</b>.</li>
          <li>Cole abaixo. A chave fica só neste computador e serve para ler (nunca movimentar) seus dados.</li>
        </ol>
      )}
      <div className="form-grid">
        <label className="field">Client ID
          <input className="input" value={id} onChange={(e) => setCid(e.target.value)} placeholder="ex.: 3f1c…" autoComplete="off" spellCheck={false} /></label>
        <label className="field">Client Secret
          <input className="input" type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="new-password"
            placeholder={cur?.has_secret ? "•••••••• (salvo; preencha só para trocar)" : "cole o segredo"} /></label>
        <div className="toolbar">
          <button className="btn primary" type="submit" disabled={!canSave || save.isPending}>{save.isPending ? "Validando…" : "Salvar e testar"}</button>
          {cur?.configured && <span className="ok-line small"><CheckCircle2 size={14} /> configurada{cur.origin === "env" ? " (pelo .env)" : ""}</span>}
        </div>
      </div>
    </form>
  );
}

/** Alertas por e-mail (Gmail com senha de app). */
export function EmailForm() {
  const toast = useToast();
  const q = useIntegrations();
  const cur = q.data?.email;
  const [user, setUser] = useState<string | null>(null);
  const [pwd, setPwd] = useState("");
  const [to, setTo] = useState<string | null>(null);
  const save = useApiMutation({
    mutationFn: async () => {
      await api("/api/integrations", { method: "PUT", body: { smtp_user: user ?? cur?.smtp_user ?? "", smtp_password: pwd || null, alert_email_to: to ?? cur?.alert_email_to ?? "" } });
      return api<{ ok: boolean; erro?: string }>("/api/alerts/test", { method: "POST" });
    },
    invalidate: [["integrations"], ["alerts"], ["onboarding"]],
    onSuccess: (r) => {
      if (r.ok) { toast("Configurado. Enviamos um e-mail de teste"); setPwd(""); }
      else toast(`O envio de teste falhou: ${r.erro}`, true);
    },
  });
  const u = user ?? cur?.smtp_user ?? "";
  return (
    <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} style={{ display: "grid", gap: 10 }}>
      <p className="note" style={{ margin: 0 }}>
        Use um Gmail com <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">senha de app</a> (exige verificação em 2 etapas).
        A senha normal da conta não funciona.
      </p>
      <div className="form-grid">
        <label className="field">Gmail que envia
          <input className="input" type="email" value={u} onChange={(e) => setUser(e.target.value)} placeholder="voce@gmail.com" /></label>
        <label className="field">Senha de app (16 letras)
          <input className="input" type="password" value={pwd} onChange={(e) => setPwd(e.target.value)} autoComplete="new-password"
            placeholder={cur?.has_password ? "•••••••• (salva)" : "abcd efgh ijkl mnop"} /></label>
        <label className="field">Enviar para (opcional)
          <input className="input" type="email" value={to ?? cur?.alert_email_to ?? ""} onChange={(e) => setTo(e.target.value)} placeholder="o mesmo Gmail" /></label>
        <div className="toolbar">
          <button className="btn primary" type="submit" disabled={!u.trim() || (!pwd && !cur?.has_password) || save.isPending}>
            {save.isPending ? "Enviando teste…" : "Salvar e enviar teste"}</button>
        </div>
      </div>
    </form>
  );
}
