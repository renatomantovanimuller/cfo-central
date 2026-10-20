import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import "./tokens.css";
import "./styles.css";
import { api } from "./api";
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

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1, staleTime: 15_000 } } });

function Login({ setup }: { setup: boolean }) {
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api(setup ? "/api/auth/setup" : "/api/auth/login", { method: "POST", body: { username, password } });
      location.reload();
    } catch (ex: any) { setErr(ex.message); }
  };
  return (
    <div className="login">
      <form onSubmit={submit} className="panel" style={{ padding: 28 }}>
        <div className="brand" style={{ padding: 0 }}><b>CFO Central</b></div>
        <p>{setup ? "Primeiro acesso: crie o usuário que protege seus dados neste computador." : "Entre para ver seus números."}</p>
        <label className="field">Usuário<input className="input" value={username} onChange={(e) => setU(e.target.value)} autoFocus required autoComplete="username" /></label>
        <label className="field">Senha{setup && " (mínimo 8 caracteres)"}
          <input className="input" type="password" value={password} onChange={(e) => setP(e.target.value)} required minLength={setup ? 8 : 1}
            autoComplete={setup ? "new-password" : "current-password"} /></label>
        {err && <span className="neg small">{err}</span>}
        <button className="btn primary" type="submit">{setup ? "Criar usuário e entrar" : "Entrar"}</button>
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
          <Route index element={<Dashboard />} />
          <Route path="dre" element={<Dre />} />
          <Route path="dre-gerencial" element={<DreGerencial />} />
          <Route path="dfc" element={<Dfc />} />
          <Route path="balanco" element={<Balance />} />
          <Route path="razao" element={<Ledger />} />
          <Route path="categorias" element={<Categories />} />
          <Route path="comerciantes" element={<Merchants />} />
          <Route path="regras" element={<Rules />} />
          <Route path="revisao" element={<Reviews />} />
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

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <BrowserRouter><Gate /></BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
