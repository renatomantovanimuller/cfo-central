import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, Circle, Flame, Lock, Star, Trophy } from "lucide-react";
import { api } from "../api";
import { QueryState } from "../components/QueryState";
import { Chip, Money, Panel } from "../components/ui";
import { useApiMutation } from "../hooks/useApiMutation";
import { brl, date, pct, prettyName } from "../format";

const WEEKDAY = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"];
const KIND_LABEL: Record<string, string> = { diaria: "do dia", mensal: "do mês", extra: "bônus" };
const TIER: Record<string, string> = { saudavel: "saudável", equilibrando: "equilibrando", vulneravel: "vulnerável" };
const UP_TONE: Record<string, "green" | "ochre" | "red" | "blue"> = { entrada: "green", fatura: "red", anual: "ochre", "conta fixa": "blue" };

export default function Today() {
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["today"], queryFn: () => api<any>("/api/today") });
  const ack = useApiMutation({ mutationFn: (missao: string) => api("/api/today/ack", { method: "POST", body: { missao } }), invalidate: [["today"]] });
  const done = useApiMutation({
    mutationFn: () => api<any>("/api/today/checkin", { method: "POST" }),
    successMessage: (r: any) => r.xp_ganho ? `Dia concluído: +${r.xp_ganho} XP · ${r.sequencia} ${r.sequencia === 1 ? "dia" : "dias"} seguidos` : "Dia concluído",
    invalidate: [["today"]],
  });
  const d = q.data;
  if (!d) return <QueryState q={q} what="o seu dia">{() => null}</QueryState>;
  const inv = d.inventario;
  const dt = new Date(`${d.data}T12:00:00`);
  const pending = d.missoes.filter((m: any) => !m.feito);
  const open = (m: any) => {
    if (m.acao === "ver") { ack.mutate(m.id); document.getElementById(`hoje-${m.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }); }
    else if (m.link) nav(m.link);
  };
  return (
    <>
      <section className="panel hud" aria-label="Seu dia">
        <div className="hud-main">
          <div className="hud-hello">{d.saudacao}! <span className="soft">Hoje é {WEEKDAY[dt.getDay()]}, {date(d.data)}.</span></div>
          <div className="hud-stats">
            <span className="hud-stat" title="Dias seguidos com o dia concluído"><Flame size={16} /> {d.sequencia} {d.sequencia === 1 ? "dia" : "dias"}</span>
            <span className="hud-stat" title={`${d.xp_total} XP no total`}><Star size={16} /> Nível {d.nivel}</span>
            <div className="hud-xp" title={`${d.xp_no_nivel} de ${d.xp_por_nivel} XP para o próximo nível`}><i style={{ width: `${(d.xp_no_nivel / d.xp_por_nivel) * 100}%` }} /></div>
            <span className="soft small">{pending.length ? `${pending.length} ${pending.length === 1 ? "missão" : "missões"} pela frente` : "tudo em dia"}</span>
          </div>
        </div>
        {d.concluido_hoje
          ? <div className="hud-done"><CheckCircle2 size={18} /> Dia concluído</div>
          : <button className="btn primary" disabled={done.isPending} onClick={() => done.mutate()}>Concluir o dia{d.xp_disponivel ? ` (+${d.xp_disponivel} XP)` : ""}</button>}
      </section>

      <div className="grid g-wide">
        <Panel title="Missões" hint="cumpra e conclua o dia para ganhar XP" flush>
          {d.missoes.map((m: any) => (
            <div key={m.id} className={`quest ${m.feito ? "done" : ""}`}>
              {m.feito ? <CheckCircle2 size={18} className="pos" /> : <Circle size={18} className="soft" />}
              <div className="grow">
                <div className="t">{m.titulo} <span className="soft small">· {KIND_LABEL[m.tipo] ?? m.tipo}</span></div>
                <div className="s">{m.detalhe}</div>
                {m.progresso != null && <div className="bar" style={{ marginTop: 4, maxWidth: 260 }}><i style={{ width: `${m.progresso * 100}%` }} /></div>}
              </div>
              <Chip tone={m.feito ? "green" : undefined}>+{m.xp} XP</Chip>
              {!m.feito && (m.link || m.acao) && <button className="btn sm" onClick={() => open(m)}>{m.acao === "ver" ? "Ver" : "Ir"}</button>}
            </div>))}
        </Panel>

        <Panel title="Inventário" hint="o que você tem hoje">
          <div className="inv">
            <Slot label="Pode gastar hoje" value={inv.pode_gastar_hoje != null ? brl(inv.pode_gastar_hoje, 0) : "—"}
              sub={inv.pode_gastar_mes != null ? `${brl(inv.pode_gastar_mes, 0)} até o fim do mês (${inv.dias_restantes} dias)` : ""} tone={inv.pode_gastar_hoje < 0 ? "neg" : ""} onClick={() => nav("/painel")} />
            <Slot label="Disponível em 1 dia" value={brl(inv.disponivel_1_dia, 0)} sub="caixa e liquidez diária" onClick={() => nav("/patrimonio")} />
            <Slot label="Patrimônio" value={brl(inv.patrimonio_liquido, 0)} sub="tudo menos dívidas" onClick={() => nav("/patrimonio")} />
            <Slot label="Reserva" value={inv.reserva.meses != null ? `${inv.reserva.meses.toFixed(1).replace(".", ",")} meses` : "—"}
              sub={inv.reserva.proximo ? `próximo degrau: ${inv.reserva.proximo.nome}` : "completa"} onClick={() => nav("/patrimonio")}
              steps={inv.reserva.degraus?.map((g: any) => g.atingido)} />
            {inv.saude && <Slot label="Saúde financeira" value={`${inv.saude.nota}/100`} sub={TIER[inv.saude.faixa] ?? inv.saude.faixa} onClick={() => nav("/planejamento")} />}
            {inv.aporte_mes?.meta ? <Slot label="Aporte do mês" value={brl(inv.aporte_mes.realizado, 0)} sub={`de ${brl(inv.aporte_mes.meta, 0)}`}
              bar={Math.min(1, inv.aporte_mes.realizado / inv.aporte_mes.meta)} onClick={() => nav("/planejamento")} /> : null}
          </div>
          <div className="inv-bolsos">{inv.bolsos.map((b: any) => (
            <div key={b.nome} className="bar-row" style={{ gridTemplateColumns: "minmax(0,1fr) 110px 90px" }}>
              <span>{b.nome}</span>{b.alvo ? <div className="bar"><i style={{ width: `${Math.min(100, (b.progresso ?? 0) * 100)}%` }} /></div> : <span />}
              <span className="num small">{brl(b.valor, 0)}</span></div>))}</div>
        </Panel>
      </div>

      <div className="grid g3">
        <Panel title="Desde a última vez" hint={`desde ${new Date(d.novidades.desde).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}`}>
          <div id="hoje-novidades" />
          {d.novidades.quantidade === 0 ? <p className="muted">Nada novo. Os bancos atualizam cerca de uma vez por dia.</p> : <>
            <p className="small">{d.novidades.quantidade} lançamentos · entrou {brl(d.novidades.entradas, 0)} · saiu {brl(d.novidades.gastos, 0)}
              {d.novidades.salario && <> · <Chip tone="green">salário caiu</Chip></>}</p>
            {d.novidades.destaques.map((x: any) => (
              <div key={x.id} className="bar-row" style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}>
                <span title={x.descricao}>{prettyName(x.descricao)} <span className="muted small">{x.categoria}</span>{x.revisar && <> <Chip tone="ochre">revisar</Chip></>}</span>
                <Money v={x.valor} /></div>))}
            <button className="btn sm ghost" onClick={() => { ack.mutate("novidades"); nav("/razao"); }}>Ver todos</button></>}
        </Panel>
        <Panel title="Ontem" hint={date(d.ontem.data)}>
          <div id="hoje-ontem" />
          <div className="num" style={{ textAlign: "left", fontSize: 28, fontWeight: 720 }}>{brl(d.ontem.gasto, 0)}</div>
          <p className="small">{d.ontem.comparacao == null ? "sem dias suficientes para comparar"
            : d.ontem.comparacao > 0.15 ? `${pct(d.ontem.comparacao, 0)} acima de um dia típico (${brl(d.ontem.dia_tipico, 0)})`
              : d.ontem.comparacao < -0.15 ? `${pct(-d.ontem.comparacao, 0)} abaixo de um dia típico (${brl(d.ontem.dia_tipico, 0)})`
                : `perto de um dia típico (${brl(d.ontem.dia_tipico, 0)})`}</p>
          {d.ontem.maiores.map((x: any, i: number) => <div key={i} className="bar-row" style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}>
            <span>{prettyName(x.descricao)}</span><Money v={x.valor} /></div>)}
        </Panel>
        <Panel title="Próximos 7 dias">
          {d.proximos_7_dias.length === 0 ? <p className="muted">Nenhuma conta fixa, fatura ou entrada prevista.</p> :
            d.proximos_7_dias.map((x: any, i: number) => (
              <div key={i} className="bar-row" style={{ gridTemplateColumns: "52px minmax(0,1fr) auto" }}>
                <span className="soft small">{date(x.data).slice(0, 5)}</span>
                <span title={x.descricao}>{prettyName(x.descricao)} <Chip tone={UP_TONE[x.tipo]}>{x.tipo}</Chip></span>
                <Money v={x.valor} /></div>))}
        </Panel>
      </div>

      <Panel title="Conquistas" hint={`${d.conquistas.filter((b: any) => b.conquistada).length} de ${d.conquistas.length}`}>
        <div className="badges">{d.conquistas.map((b: any) => (
          <div key={b.id} className={`badge ${b.conquistada ? "on" : ""}`} title={b.descricao}>
            {b.conquistada ? <Trophy size={20} /> : <Lock size={20} />}<b>{b.nome}</b><span>{b.descricao}</span></div>))}</div>
      </Panel>
    </>
  );
}

function Slot({ label, value, sub, tone, bar, steps, onClick }: { label: string; value: string; sub?: string; tone?: string; bar?: number;
  steps?: boolean[]; onClick?: () => void }) {
  return (
    <button className="inv-slot" onClick={onClick}>
      <span className="lbl">{label}</span>
      <span className={`val num ${tone ?? ""}`}>{value}</span>
      {bar != null && <span className="bar"><i style={{ width: `${bar * 100}%` }} /></span>}
      {steps && <span className="pips">{steps.map((ok, i) => <i key={i} className={ok ? "on" : ""} />)}</span>}
      {sub && <span className="soft small">{sub}</span>}
    </button>
  );
}
