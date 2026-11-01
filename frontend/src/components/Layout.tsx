import { createContext, ReactNode, useContext, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiMutation } from "../hooks/useApiMutation";
import { reviewSummary } from "./reviewBadge";
import { useOnboarding } from "../hooks/useOnboarding";
import {
  ArrowLeftRight, BookOpen, ClipboardList, CalendarRange, ChevronLeft, ChevronRight, CreditCard, Download, Eye, EyeOff, FileSpreadsheet, Gauge,
  Inbox, Landmark, Layers, LineChart, ListTree, LogOut, Menu, PieChart, PlugZap, Receipt, RefreshCw, Scale, Settings2, ShieldCheck, Store, Wand2, X,
} from "lucide-react";
import { api } from "../api";
import { addMonth, dateTime, monthLabel, monthLong, thisMonth } from "../format";
import { useToast } from "./ui";
import { togglePrivate, usePrivacy } from "../privacy";
import { DEMO } from "../demo";

/** Janela de leitura: quantos meses terminando no mês escolhido ("ano" = do início do ano até ele). */
export type Win = "1" | "3" | "6" | "12" | "ano";
export const WINDOWS: [Win, string, string][] = [["1", "Mês", "só o mês"], ["3", "3m", "últimos 3 meses"],
  ["6", "6m", "últimos 6 meses"], ["12", "12m", "últimos 12 meses"], ["ano", "Ano", "do início do ano até o mês"]];
export const winMonths = (w: Win, month: string) => (w === "ano" ? Number(month.slice(5, 7)) : Number(w));

type PeriodState = { month: string; setMonth: (m: string) => void; win: Win; setWin: (w: Win) => void; months: number; start: string };
const MonthCtx = createContext<PeriodState>({ month: thisMonth(), setMonth: () => {}, win: "1", setWin: () => {}, months: 1, start: thisMonth() });
export const useMonth = () => useContext(MonthCtx);
export const usePeriod = useMonth;

const WIN_KEY = "cfo.janela";
function readWin(): Win {
  try { const v = localStorage.getItem(WIN_KEY); return WINDOWS.some(([k]) => k === v) ? (v as Win) : "1"; } catch { return "1"; }
}

export function MonthProvider({ children }: { children: ReactNode }) {
  const [month, setMonth] = useState(thisMonth());
  const [win, setWinState] = useState<Win>(readWin);
  const setWin = (w: Win) => { setWinState(w); try { localStorage.setItem(WIN_KEY, w); } catch { /* armazenamento indisponível */ } };
  const months = winMonths(win, month);
  return <MonthCtx.Provider value={{ month, setMonth, win, setWin, months, start: addMonth(month, -(months - 1)) }}>{children}</MonthCtx.Provider>;
}

// ordem pensada para o uso diário: primeiro o que pede ação (Revisão), depois os números, por fim a configuração
const NAV: { group: string; items: { to: string; label: string; icon: any; badge?: boolean; hint?: string }[] }[] = [
  { group: "Visão", items: [{ to: "/", label: "Painel", icon: Gauge }, { to: "/revisao", label: "Revisão", icon: Inbox, badge: true },
    { to: "/gastos", label: "Gastos", icon: PieChart, hint: "Para onde vai o dinheiro: categorias, calendário, comerciantes" },
    { to: "/razao", label: "Lançamentos", icon: Layers }] },
  { group: "Resultados", items: [
    { to: "/dre", label: "Resultado do mês", icon: BookOpen, hint: "DRE: receitas menos despesas, mês a mês" },
    { to: "/dre-gerencial", label: "Resultado gerencial", icon: ClipboardList, hint: "DRE gerencial: mês contra média, orçamento e acumulado do ano" },
    { to: "/dfc", label: "Fluxo de caixa", icon: ArrowLeftRight, hint: "DFC: o dinheiro que entrou e saiu das contas" },
    { to: "/balanco", label: "Balanço", icon: Scale, hint: "O que você tem e o que deve, mês a mês" } ] },
  { group: "Organização", items: [
    { to: "/categorias", label: "Categorias e orçamento", icon: ListTree },
    { to: "/comerciantes", label: "Comerciantes", icon: Store }, { to: "/regras", label: "Regras", icon: Wand2 } ] },
  { group: "Patrimônio", items: [
    { to: "/carteira", label: "Carteira", icon: LineChart }, { to: "/cartoes", label: "Cartões", icon: CreditCard },
    { to: "/planejamento", label: "Planejamento", icon: CalendarRange }, { to: "/imposto-de-renda", label: "Imposto de renda", icon: Receipt } ] },
  { group: "Sistema", items: [
    { to: "/conexoes", label: "Conexões", icon: PlugZap }, { to: "/saude", label: "Saúde dos dados", icon: ShieldCheck }, { to: "/config", label: "Configurações", icon: Settings2 } ] },
];

/** Atalhos do celular: o uso diário em quatro toques; o resto fica no menu "Mais". */
const TABBAR = [{ to: "/", label: "Painel", icon: Gauge }, { to: "/gastos", label: "Gastos", icon: PieChart },
  { to: "/carteira", label: "Carteira", icon: LineChart }, { to: "/revisao", label: "Revisão", icon: Inbox }];

const TITLES: Record<string, string> = {
  "/": "Painel", "/gastos": "Gastos", "/dre": "Resultado do mês (DRE)", "/dre-gerencial": "Resultado gerencial", "/dfc": "Fluxo de caixa", "/balanco": "Balanço patrimonial",
  "/razao": "Lançamentos", "/categorias": "Categorias e orçamento", "/comerciantes": "Comerciantes", "/regras": "Regras de classificação",
  "/revisao": "Revisão", "/carteira": "Carteira", "/cartoes": "Cartões", "/planejamento": "Planejamento",
  "/conexoes": "Conexões", "/config": "Configurações", "/saude": "Saúde dos dados", "/imposto-de-renda": "Imposto de renda",
};
/** Telas que leem uma janela de meses (as demais usam só o mês). */
const WINDOWED = new Set(["/gastos", "/razao"]);
const MONTHLESS = new Set(["/balanco", "/regras", "/revisao", "/carteira", "/cartoes", "/planejamento", "/conexoes", "/config", "/comerciantes", "/saude", "/imposto-de-renda"]);

export function Layout() {
  const { month, setMonth, win, setWin, start } = useMonth();
  const loc = useLocation();
  const qc = useQueryClient();
  const toast = useToast();
  const reviews = useQuery({ queryKey: ["reviews-count"], queryFn: () => api<any[]>("/api/reviews"), refetchInterval: 60_000 });
  const reviewCount = reviewSummary(reviews.data).pending;
  const ob = useOnboarding();
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => setMenuOpen(false), [loc.pathname]);
  const noConnection = !!ob.data && ob.data.items === 0;
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
    if (was.current && !running) { qc.invalidateQueries(); toast(sync.data?.last_error ? `Sincronização terminou com erro: ${sync.data.last_error}` : "Sincronização concluída", !!sync.data?.last_error); }
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
    <div className={`shell ${menuOpen ? "menu-open" : ""}`}>
      <div className="mobilebar">
        <button className="btn ghost" onClick={() => setMenuOpen(true)} aria-label="Abrir menu" aria-expanded={menuOpen}><Menu size={18} /></button>
        <b className="mobile-brand">CFO Central</b>
        {reviewCount > 0 && <NavLink to="/revisao" className="chip ochre" aria-label={`${reviewCount} decisões pendentes`}>{reviewCount} para decidir</NavLink>}
      </div>
      {menuOpen && <div className="nav-backdrop" onClick={() => setMenuOpen(false)} />}
      <nav className="sidebar" aria-label="Navegação">
        <div className="brand"><b>CFO Central</b>
          <button className="btn ghost sm nav-close" onClick={() => setMenuOpen(false)} aria-label="Fechar menu"><X size={16} /></button></div>
        {NAV.map((g) => (
          <div className="nav-group" key={g.group}>
            <h6>{g.group}</h6>
            {g.items.map((it) => (
              <NavLink key={it.to} to={it.to} end={it.to === "/"} title={it.hint}>
                <it.icon size={16} strokeWidth={1.8} /> {it.label}
                {it.badge && reviewCount > 0 && <span className="count" aria-label={`${reviewCount} pendentes`}>{reviewCount}</span>}
              </NavLink>
            ))}
          </div>
        ))}
        {DEMO ? <div className="sidebar-foot"><span>Demonstração com dados fictícios.</span></div> : <div className="sidebar-foot">
          <a href="/api/export.xlsx" className="soft" style={{ display: "flex", gap: 8, alignItems: "center", textDecoration: "none" }}>
            <FileSpreadsheet size={15} /> Exportar Excel</a>
          <a href="/api/export.csv" className="soft" style={{ display: "flex", gap: 8, alignItems: "center", textDecoration: "none" }}>
            <Download size={15} /> Exportar razão (CSV)</a>
          <button className="btn ghost sm" onClick={logout} style={{ justifyContent: "flex-start", padding: 0 }}><LogOut size={14} /> Sair</button>
        </div>}
      </nav>
      <div className="main">
        <header className="topbar">
          <h1>{title}</h1>
          {!MONTHLESS.has(loc.pathname) && (
            <div className="segmented month-picker" role="group" aria-label="Mês">
              <button onClick={() => setMonth(addMonth(month, -1))} aria-label="Mês anterior"><ChevronLeft size={15} /></button>
              <button className="on" style={{ minWidth: 150 }} title="Voltar para o mês atual" onClick={() => setMonth(thisMonth())}>{monthLong(month)}</button>
              <button onClick={() => setMonth(addMonth(month, 1))} aria-label="Próximo mês" disabled={month >= thisMonth()}><ChevronRight size={15} /></button>
            </div>
          )}
          {WINDOWED.has(loc.pathname) && (
            <div className="segmented window-picker" role="group" aria-label="Janela de meses">
              {WINDOWS.map(([k, l, tip]) => <button key={k} className={win === k ? "on" : ""} aria-pressed={win === k} title={tip}
                onClick={() => setWin(k)}>{l}</button>)}
            </div>
          )}
          {WINDOWED.has(loc.pathname) && win !== "1" && <span className="sync-line range-line">{monthLabel(start)} a {monthLabel(month)}</span>}
          <div className="spacer" />
          <span className="sync-line">
            <span className={`dot ${running ? "run" : noConnection ? "idle" : ""}`} />
            {running ? `Sincronizando: ${sync.data?.step ?? ""}` : last ? `Atualizado ${dateTime(last)}` : noConnection ? "Nenhum banco conectado" : "Aguardando primeira sincronização"}
          </span>
          <button className="btn ghost" onClick={togglePrivate} aria-pressed={hidden} title={hidden ? "Mostrar valores (Shift+P)" : "Ocultar valores (Shift+P)"}
            aria-label={hidden ? "Mostrar valores" : "Ocultar valores"}>{hidden ? <EyeOff size={15} /> : <Eye size={15} />}</button>
          {noConnection
            ? <NavLink className="btn primary" to="/conexoes"><PlugZap size={14} /> Conectar banco</NavLink>
            : <button className="btn" onClick={() => startSync.mutate()} disabled={running} title="Buscar novidades nos bancos agora">
                <RefreshCw size={14} className={running ? "spin" : ""} /> <span className="hide-sm">Sincronizar</span></button>}
        </header>
        <main className="content" key={hidden ? "oculto" : "visivel"}>
          {DEMO && <div className="callout info demo-note" role="note"><div className="grow"><b>Demonstração.</b> Pessoa, banco e valores são fictícios.
            Navegue à vontade: botões de alterar respondem que nada é salvo.</div></div>}
          <Outlet />
        </main>
      </div>
      <nav className="tabbar" aria-label="Atalhos">
        {TABBAR.map((t) => (
          <NavLink key={t.to} to={t.to} end={t.to === "/"}>
            <t.icon size={20} strokeWidth={1.8} />
            <span>{t.label}</span>
            {t.to === "/revisao" && reviewCount > 0 && <b className="tab-count" aria-label={`${reviewCount} pendentes`}>{reviewCount}</b>}
          </NavLink>
        ))}
        <button onClick={() => setMenuOpen(true)} aria-label="Mais telas" aria-expanded={menuOpen}><Menu size={20} strokeWidth={1.8} /><span>Mais</span></button>
      </nav>
    </div>
  );
}

export { monthLabel, Landmark };
