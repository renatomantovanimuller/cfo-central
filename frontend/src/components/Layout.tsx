import { createContext, ReactNode, useContext, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiMutation } from "../hooks/useApiMutation";
import { actionableReviewCount } from "./reviewBadge";
import {
  ArrowLeftRight, BookOpen, ClipboardList, CalendarRange, ChevronLeft, ChevronRight, CreditCard, Download, Eye, EyeOff, FileSpreadsheet, Gauge,
  Inbox, Landmark, Layers, LineChart, ListTree, LogOut, PlugZap, Receipt, RefreshCw, Scale, Settings2, ShieldCheck, Store, Wand2,
} from "lucide-react";
import { api } from "../api";
import { addMonth, dateTime, monthLabel, monthLong, thisMonth } from "../format";
import { useToast } from "./ui";
import { togglePrivate, usePrivacy } from "../privacy";

const MonthCtx = createContext<{ month: string; setMonth: (m: string) => void }>({ month: thisMonth(), setMonth: () => {} });
export const useMonth = () => useContext(MonthCtx);

export function MonthProvider({ children }: { children: ReactNode }) {
  const [month, setMonth] = useState(thisMonth());
  return <MonthCtx.Provider value={{ month, setMonth }}>{children}</MonthCtx.Provider>;
}

const NAV: { group: string; items: { to: string; label: string; icon: any; badge?: boolean }[] }[] = [
  { group: "Visão", items: [{ to: "/", label: "Painel", icon: Gauge }] },
  { group: "Demonstrativos", items: [
    { to: "/dre", label: "DRE", icon: BookOpen }, { to: "/dre-gerencial", label: "DRE gerencial", icon: ClipboardList },
    { to: "/dfc", label: "Fluxo de caixa", icon: ArrowLeftRight },
    { to: "/balanco", label: "Balanço", icon: Scale } ] },
  { group: "Razão", items: [
    { to: "/razao", label: "Lançamentos", icon: Layers }, { to: "/categorias", label: "Categorias e orçamento", icon: ListTree },
    { to: "/comerciantes", label: "Comerciantes", icon: Store }, { to: "/regras", label: "Regras", icon: Wand2 },
    { to: "/revisao", label: "Revisão", icon: Inbox, badge: true } ] },
  { group: "Patrimônio", items: [
    { to: "/carteira", label: "Carteira", icon: LineChart }, { to: "/cartoes", label: "Cartões", icon: CreditCard },
    { to: "/planejamento", label: "Planejamento", icon: CalendarRange }, { to: "/imposto-de-renda", label: "Imposto de renda", icon: Receipt } ] },
  { group: "Sistema", items: [
    { to: "/conexoes", label: "Conexões", icon: PlugZap }, { to: "/saude", label: "Saúde dos dados", icon: ShieldCheck }, { to: "/config", label: "Configurações", icon: Settings2 } ] },
];

const TITLES: Record<string, string> = {
  "/": "Painel", "/dre": "Demonstração do resultado", "/dre-gerencial": "DRE gerencial", "/dfc": "Fluxo de caixa", "/balanco": "Balanço patrimonial",
  "/razao": "Lançamentos", "/categorias": "Categorias e orçamento", "/comerciantes": "Comerciantes", "/regras": "Regras de classificação",
  "/revisao": "Revisão", "/carteira": "Carteira", "/cartoes": "Cartões", "/planejamento": "Planejamento",
  "/conexoes": "Conexões", "/config": "Configurações", "/saude": "Saúde dos dados", "/imposto-de-renda": "Imposto de renda",
};
const MONTHLESS = new Set(["/balanco", "/regras", "/revisao", "/carteira", "/cartoes", "/planejamento", "/conexoes", "/config", "/comerciantes", "/saude", "/imposto-de-renda"]);

export function Layout() {
  const { month, setMonth } = useMonth();
  const loc = useLocation();
  const qc = useQueryClient();
  const toast = useToast();
  const reviews = useQuery({ queryKey: ["reviews-count"], queryFn: () => api<any[]>("/api/reviews"), refetchInterval: 60_000 });
  const reviewCount = actionableReviewCount(reviews.data);
  const sync = useQuery({ queryKey: ["sync-status"], queryFn: () => api<any>("/api/sync/status"),
    refetchInterval: (q) => (q.state.data?.running ? 1500 : 30_000) });
  const startSync = useApiMutation({
    mutationFn: () => api<any>("/api/sync", { method: "POST", body: {} }),
    successMessage: (r) => (r.started ? "Sincronização iniciada" : "Já existe uma sincronização em andamento"),
    invalidate: [["sync-status"]],
  });
  const running = !!sync.data?.running;
  const was = useRef(running);
  useEffect(() => {
    if (was.current && !running) { qc.invalidateQueries(); toast("Sincronização concluída"); }
    was.current = running;
  }, [running, qc, toast]);

  const hidden = usePrivacy();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable)) return;
      if (e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey && e.key.toLowerCase() === "p") { e.preventDefault(); togglePrivate(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const logout = async () => { await api("/api/auth/logout", { method: "POST" }); location.reload(); };
  const title = TITLES[loc.pathname] ?? "CFO Central";
  const last = sync.data?.last_ok_at ?? null;

  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Navegação">
        <div className="brand"><b>CFO Central</b></div>
        {NAV.map((g) => (
          <div className="nav-group" key={g.group}>
            <h6>{g.group}</h6>
            {g.items.map((it) => (
              <NavLink key={it.to} to={it.to} end={it.to === "/"}>
                <it.icon size={16} strokeWidth={1.8} /> {it.label}
                {it.badge && reviewCount > 0 && <span className="count">{reviewCount}</span>}
              </NavLink>
            ))}
          </div>
        ))}
        <div className="sidebar-foot">
          <a href="/api/export.xlsx" className="soft" style={{ display: "flex", gap: 8, alignItems: "center", textDecoration: "none" }}>
            <FileSpreadsheet size={15} /> Exportar Excel</a>
          <a href="/api/export.csv" className="soft" style={{ display: "flex", gap: 8, alignItems: "center", textDecoration: "none" }}>
            <Download size={15} /> Exportar razão (CSV)</a>
          <button className="btn ghost sm" onClick={logout} style={{ justifyContent: "flex-start", padding: 0 }}><LogOut size={14} /> Sair</button>
        </div>
      </nav>
      <div className="main">
        <header className="topbar">
          <h1>{title}</h1>
          {!MONTHLESS.has(loc.pathname) && (
            <div className="segmented" role="group" aria-label="Mês">
              <button onClick={() => setMonth(addMonth(month, -1))} aria-label="Mês anterior"><ChevronLeft size={15} /></button>
              <button className="on" style={{ minWidth: 132 }} title={monthLong(month)}>{monthLong(month)}</button>
              <button onClick={() => setMonth(addMonth(month, 1))} aria-label="Próximo mês"><ChevronRight size={15} /></button>
            </div>
          )}
          <div className="spacer" />
          <span className="sync-line">
            <span className={`dot ${running ? "run" : ""}`} />
            {running ? `Sincronizando: ${sync.data?.step ?? ""}` : last ? `Atualizado ${dateTime(last)}` : "Aguardando primeira sincronização"}
          </span>
          <button className="btn ghost" onClick={togglePrivate} aria-pressed={hidden} title={hidden ? "Mostrar valores (Shift+P)" : "Ocultar valores (Shift+P)"}
            aria-label={hidden ? "Mostrar valores" : "Ocultar valores"}>{hidden ? <EyeOff size={15} /> : <Eye size={15} />}</button>
          <button className="btn" onClick={() => startSync.mutate()} disabled={running}><RefreshCw size={14} /> Sincronizar</button>
        </header>
        <main className="content" key={hidden ? "oculto" : "visivel"}><Outlet /></main>
      </div>
    </div>
  );
}

export { monthLabel, Landmark };
