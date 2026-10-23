import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, HashRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import "./tokens.css";
import "./styles.css";
import { api } from "./api";
import { DEMO, installDemo } from "./demo";
import { Layout, MonthProvider } from "./components/Layout";
import { ToastProvider } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import Ledger from "./pages/Ledger";
import Dre from "./pages/Dre";
import DreGerencial from "./pages/DreGerencial";
import Dfc from "./pages/Dfc";
import Balance from "./pages/Balance";
import Categories from "./pages/Categories";
import Merchants from "./pages/Merchants";
import Rules from "./pages/Rules";
import Reviews from "./pages/Reviews";
import Portfolio from "./pages/Portfolio";
import Cards from "./pages/Cards";
import Planning from "./pages/Planning";
import Connections from "./pages/Connections";
import SettingsPage from "./pages/Settings";
import SaudeDados from "./pages/SaudeDados";
import ImpostoRenda from "./pages/ImpostoRenda";
import Patrimony from "./pages/Patrimony";
import Today from "./pages/Today";
import { useOnboarding } from "./hooks/useOnboarding";

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1, staleTime: 15_000 } } });

function Login({ setup }: { setup: boolean }) {
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [confirm, setC] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (setup && password !== confirm) { setErr("As senhas não conferem."); return; }
    setBusy(true);
    try {
      await api(setup ? "/api/auth/setup" : "/api/auth/login", { method: "POST", body: { username, password } });
      location.reload();
    } catch (ex: any) { setErr(ex.status === 401 ? "Usuário ou senha incorretos." : ex.message); setBusy(false); }
  };
  return (
    <div className="login">
      <form onSubmit={submit} className="panel" style={{ padding: 28 }}>
        <div className="brand" style={{ padding: 0 }}><b>CFO Central</b></div>
        <p>{setup
          ? "Bem-vindo! Crie um usuário e uma senha para proteger seus dados neste computador. Em seguida, vamos conectar seus bancos (leva uns 5 minutos)."
          : "Entre para ver seus números."}</p>
        <label className="field">Usuário<input className="input" value={username} onChange={(e) => setU(e.target.value)} autoFocus required autoComplete="username" /></label>
        <label className="field">Senha{setup && " (mínimo 8 caracteres)"}
          <input className="input" type="password" value={password} onChange={(e) => setP(e.target.value)} required minLength={setup ? 8 : 1}
            autoComplete={setup ? "new-password" : "current-password"} /></label>
        {setup && <label className="field">Confirme a senha
          <input className="input" type="password" value={confirm} onChange={(e) => setC(e.target.value)} required minLength={8} autoComplete="new-password" /></label>}
        {err && <span className="neg small" role="alert">{err}</span>}
        <button className="btn primary" type="submit" disabled={busy} style={{ justifyContent: "center" }}>{setup ? "Criar usuário e começar" : "Entrar"}</button>
        {setup && <p className="note" style={{ margin: 0 }}>Não há recuperação de senha por e-mail: anote-a em um lugar seguro.</p>}
      </form>
    </div>
  );
}

function Gate() {
  const status = useQuery({ queryKey: ["auth"], queryFn: () => api<{ setup_required: boolean; user: string | null }>("/api/auth/status") });
  if (status.isError && !status.data) return (
    <div className="boot" role="alert">
      <div className="brand"><b>CFO Central</b></div>
      <p className="neg">Não foi possível falar com o servidor local. Ele está rodando? (rode INICIAR.bat)</p>
      <button className="btn" onClick={() => status.refetch()} disabled={status.isFetching}>Tentar de novo</button>
    </div>
  );
  if (!status.data) return <div className="boot" aria-busy="true"><div className="brand"><b>CFO Central</b></div><span className="spinner" role="status" aria-label="Carregando" /></div>;
  if (!status.data?.user) return <Login setup={!!status.data?.setup_required} />;
  return (
    <MonthProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="painel" element={<Dashboard />} />
          <Route path="dre" element={<Dre />} />
          <Route path="dre-gerencial" element={<DreGerencial />} />
          <Route path="dfc" element={<Dfc />} />
          <Route path="balanco" element={<Balance />} />
          <Route path="razao" element={<Ledger />} />
          <Route path="categorias" element={<Categories />} />
          <Route path="comerciantes" element={<Merchants />} />
          <Route path="regras" element={<Rules />} />
          <Route path="revisao" element={<Reviews />} />
          <Route path="patrimonio" element={<Patrimony />} />
          <Route path="carteira" element={<Portfolio />} />
          <Route path="cartoes" element={<Cards />} />
          <Route path="planejamento" element={<Planning />} />
          <Route path="conexoes" element={<Connections />} />
          <Route path="config" element={<SettingsPage />} />
          <Route path="saude" element={<SaudeDados />} />
          <Route path="imposto-de-renda" element={<ImpostoRenda />} />
          <Route path="*" element={<Dashboard />} />
        </Route>
      </Routes>
    </MonthProvider>
  );
}

// a vitrine roda sem servidor: rotas no hash (funciona em qualquer hospedagem estática)
const Router = DEMO ? HashRouter : BrowserRouter;

/** Início: a tela Hoje quando já há dados; antes disso, o Painel com o passo a passo de configuração. */
function Home() {
  const ob = useOnboarding();
  if (!ob.data) return null;
  return ob.data.events > 0 ? <Today /> : <Dashboard />;
}

const render = () => ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <Router><Gate /></Router>
      </ToastProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);

if (DEMO) installDemo().then(render);
else render();
