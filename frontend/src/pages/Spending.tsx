import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Chart, colorFor, cssVar, inkOn, kTick, seqRamp } from "../components/Chart";
import { EventDrawer } from "../components/EventDrawer";
import { usePeriod } from "../components/Layout";
import { QueryState } from "../components/QueryState";
import { Empty, Money, Panel } from "../components/ui";
import { isPrivate, MASK } from "../privacy";
import { brl, compact, date, monthAxisLabel, monthLabel, monthLong, pct, prettyName } from "../format";

type Cat = { id: string; name: string; value: number; prev: number; count: number; share: number | null; budget: number | null;
  children: { id: string; name: string; value: number; prev: number; count: number }[] };

/** Variação contra o período anterior; gasto maior é desfavorável. */
function Var({ cur, prev }: { cur: number; prev: number }) {
  if (!prev || Math.abs(prev) < 1) return <span className="muted small">novo</span>;
  const d = (cur - prev) / Math.abs(prev);
  if (Math.abs(d) < 0.005) return <span className="muted small">=</span>;
  return <span className={`small ${d > 0 ? "neg" : "pos"}`}>{d > 0 ? "+" : "−"}{Math.abs(d * 100).toFixed(0)}%</span>;
}

export default function Spending() {
  const { month, months, start, win } = usePeriod();
  const nav = useNavigate();
  const [account, setAccount] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [drill, setDrill] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["spending", month, months, account],
    queryFn: () => api<any>(`/api/spending?end=${month}&months=${months}${account ? `&account=${encodeURIComponent(account)}` : ""}`) });
  const d = q.data;

  const color = useMemo(() => colorFor((d?.categories ?? []).filter((c: Cat) => c.value > 0).slice(0, 8).map((c: Cat) => c.name)),
    [d?.categories]);

  if (!d) return <QueryState q={q} what="os gastos">{() => null}</QueryState>;
  const t = d.totals;
  const label = months === 1 ? monthLong(month) : `${monthLabel(start)} a ${monthLabel(month)}`;
  const prevLabel = months === 1 ? "mês anterior" : `${months} meses anteriores`;
  const range = months === 1 ? `month=${month}` : `start=${d.range.start}&end=${d.range.end}`;
  const toLedger = (extra: string) => nav(`/razao?${range}${extra}${account ? `&account=${encodeURIComponent(account)}` : ""}`);
  const cats: Cat[] = d.categories;
  const positive = cats.filter((c) => c.value > 0);
  const drilled = drill ? cats.find((c) => c.id === drill) : null;

  const toolbar = (
    <div className="toolbar filters">
      <select className="select" value={account} onChange={(e) => setAccount(e.target.value)} aria-label="Conta ou cartão">
        <option value="">Todas as contas e cartões</option>
        {d.accounts.map((a: any) => <option key={a.id} value={a.id}>{a.name}{a.type === "CREDIT" ? " (cartão)" : ""}</option>)}
        {account && !d.accounts.some((a: any) => a.id === account) && <option value={account}>Conta selecionada</option>}
      </select>
      <span className="small soft">{label}{d.range.partial ? ` (até ${date(d.range.last_day)})` : ""}</span>
      <div className="spacer" />
      <button className="btn sm" onClick={() => toLedger("&direction=out")}>Ver lançamentos</button>
    </div>
  );

  if (!positive.length) return <>{toolbar}<Panel><Empty title={`Sem gastos em ${label}`}>
    Escolha outro mês ou uma janela maior no topo da tela.</Empty></Panel></>;

  const usedBudget = t.budget ? t.value / t.budget : null;
  return (
    <>
      {toolbar}
      <section className="panel strip" aria-label={`Resumo de gastos, ${label}`}>
        <div><div className="lbl">Total gasto</div><div className="val num" style={{ textAlign: "left" }}>{brl(t.value)}</div>
          <div className="sub"><Var cur={t.value} prev={t.prev} /> contra {prevLabel} ({compact(t.prev)})</div></div>
        <div><div className="lbl">{months > 1 ? "Média por mês" : "Média por dia"}</div>
          <div className="val num" style={{ textAlign: "left" }}>{brl(months > 1 ? t.per_month : t.per_day, 0)}</div>
          <div className="sub">{months > 1 ? `${brl(t.per_day, 0)} por dia` : `${t.count} lançamentos`}</div></div>
        <div><div className="lbl">Essencial</div>
          <div className="val">{pct((d.groups.find((g: any) => g.name === "Essencial")?.value ?? 0) / t.value, 0)}</div>
          <div className="sub">do total; estilo de vida {pct((d.groups.find((g: any) => g.name === "Estilo de vida")?.value ?? 0) / t.value, 0)}</div></div>
        <div><div className="lbl">Parcelado</div><div className="val num" style={{ textAlign: "left" }}>{brl(t.installments, 0)}</div>
          <div className="sub">{pct(t.installments / t.value, 0)} do gasto veio de parcelas</div></div>
        {usedBudget !== null
          ? <div><div className="lbl">Orçamento</div><div className={`val ${usedBudget > 1 ? "neg" : ""}`}>{pct(usedBudget, 0)}</div>
              <div className="sub">usado de {brl(t.budget, 0)}</div></div>
          : <div><div className="lbl">Comerciantes novos</div><div className="val">{t.new_merchants}</div>
              <div className="sub">sem compra no período anterior</div></div>}
      </section>

      <div className="grid g-wide">
        <Panel title="Para onde foi o dinheiro" hint={drilled ? <>dentro de <b>{drilled.name}</b></> : "toque numa categoria para abrir as subcategorias"}
          tools={drilled ? <button className="btn sm" onClick={() => setDrill(null)}>← Todas</button> : undefined}>
          <Treemap cats={positive} drill={drilled} color={color}
            onPick={(id) => { const c = cats.find((x) => x.id === id); if (c && !drilled && c.children.length > 1) setDrill(id); else toLedger(`&category=${id}`); }} />
        </Panel>
        <Panel title="Categorias" hint={`contra ${prevLabel}`} flush>
          <div className="cat-list">
            {(drilled ? drilled.children : positive).map((c: any) => {
              const budget = !drilled ? (c as Cat).budget : null;
              return (
                <button key={c.id + c.name} className="cat-row" onClick={() => toLedger(`&category=${c.id}`)}>
                  <i className="sw" style={{ background: color(drilled ? drilled.name : c.name) }} />
                  <span className="nm" title={c.name}>{c.name}</span>
                  <span className="num">{brl(c.value, 0)}</span>
                  <span className="num soft small">{pct(c.value / (drilled ? drilled.value : t.value), 0)}</span>
                  <Var cur={c.value} prev={c.prev} />
                  {budget ? <span className="bud" title={`orçamento ${brl(budget, 0)}`}>
                    <i style={{ width: `${Math.min(100, (c.value / budget) * 100)}%`, background: c.value > budget ? "var(--debit)" : undefined }} /></span>
                    : <span />}
                </button>);
            })}
          </div>
        </Panel>
      </div>

      <div className="grid g2">
        {months > 1
          ? <Panel title="Mês a mês" hint="categorias que mais pesam; o resto em Outras">
              <Chart height={280} onClick={(p) => p.dataIndex !== undefined && nav(`/razao?month=${d.series[p.dataIndex].month}&direction=out`)} option={{
                tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v, 0) },
                legend: { type: "scroll" },
                grid: { top: 40 },
                xAxis: { type: "category", data: d.series.map((s: any) => monthAxisLabel(s.month)) },
                yAxis: { type: "value", axisLabel: { formatter: kTick } },
                series: [...positive.map((c) => c.name).filter((n) => d.series.some((s: any) => n in s.by)),
                  ...(d.series.some((s: any) => "Outras" in s.by) ? ["Outras"] : [])].map((name: string) => ({
                  name, type: "bar", stack: "g", barMaxWidth: 38,
                  itemStyle: { color: color(name), borderColor: cssVar("--sheet"), borderWidth: 1 },
                  data: d.series.map((s: any) => Math.round(s.by[name] ?? 0)),
                })),
              }} />
            </Panel>
          : <Panel title="Tipo de gasto" hint={`contra ${prevLabel}`}>
              {d.groups.map((g: any) => (
                <div key={g.name} className="bar-row cmp">
                  <span title={g.name}>{g.name}</span>
                  <div className="bars2"><div className="bar"><i style={{ width: `${(g.value / d.groups[0].value) * 100}%` }} /></div>
                    <div className="bar prior"><i style={{ width: `${Math.max(0, g.prev / d.groups[0].value) * 100}%` }} /></div></div>
                  <span className="num">{brl(g.value, 0)}<div className="small muted">{compact(g.prev)} antes</div></span>
                </div>))}
              <p className="note">Barra cheia: {label}. Barra fina: {prevLabel}.</p>
            </Panel>}
        <Panel title="Calendário" hint="quanto saiu em cada dia; toque para ver os lançamentos">
          <Calendar daily={d.daily} onPick={(day) => nav(`/razao?start=${day}&end=${day}&direction=out`)} />
        </Panel>
      </div>

      <div className="grid g2">
        <Panel title="Dia da semana" hint="média por dia no período">
          <Chart height={220} option={{
            legend: false,
            tooltip: { trigger: "axis", valueFormatter: (v: number) => brl(v, 0) },
            xAxis: { type: "category", data: d.weekday.map((w: any) => w.dia) },
            yAxis: { type: "value", axisLabel: { formatter: kTick } },
            series: [{ name: "Média por dia", type: "bar", barMaxWidth: 30, itemStyle: { color: cssVar("--cat-1"), borderRadius: [4, 4, 0, 0] },
              data: d.weekday.map((w: any) => Math.round(w.media ?? 0)) }],
          }} />
        </Panel>
        <Panel title="Por conta e cartão">
          {d.accounts.map((a: any) => (
            <button key={a.id} className={`bar-row plain ${account === a.id ? "sel" : ""}`} onClick={() => setAccount(account === a.id ? "" : a.id)}
              title="Filtrar a tela por esta conta">
              <span title={a.name}>{a.name}{a.type === "CREDIT" ? " · cartão" : ""}</span>
              <div className="bar"><i style={{ width: `${(a.total / d.accounts[0].total) * 100}%`, background: "var(--cat-1)" }} /></div>
              <Money v={a.total} digits={0} />
            </button>))}
          <p className="note">Toque numa conta para filtrar a tela inteira.</p>
        </Panel>
      </div>

      <div className="grid g-wide">
        <Panel title="Comerciantes" hint={`onde mais gastou; ${t.new_merchants} sem compra no período anterior`} flush>
          <div className="table-wrap" style={{ maxHeight: "none" }}>
            <table className="table cards-sm">
              <thead><tr><th>Comerciante</th><th className="hide-sm">Categoria</th><th className="num">Total</th>
                <th className="num">Compras</th><th className="num hide-sm">Ticket médio</th><th className="num">Variação</th></tr></thead>
              <tbody>{d.merchants.map((m: any) => (
                <tr key={m.id} className="clickable" onClick={() => toLedger(`&merchant=${m.id}`)}>
                  <td data-label="Comerciante"><div className="strong" title={m.name}>{prettyName(m.name)}</div>
                    <div className="small muted show-sm">{m.category}</div></td>
                  <td className="soft hide-sm">{m.category}</td>
                  <td data-label="Total"><Money v={m.total} digits={0} /><div className="small muted">{pct(m.share, 0)}</div></td>
                  <td className="num" data-label="Compras">{m.count}</td>
                  <td className="hide-sm"><Money v={m.ticket} digits={0} /></td>
                  <td className="num" data-label="Variação"><Var cur={m.total} prev={m.prev} /></td>
                </tr>))}</tbody>
            </table>
          </div>
        </Panel>
        <Panel title="Maiores gastos" hint="toque para ver e reclassificar">
          {d.biggest.map((b: any) => (
            <button key={b.id} className="list-row plain" onClick={() => setOpen(b.id)}>
              <div className="grow"><div className="t" title={b.description}>{prettyName(b.merchant ?? b.description)}</div>
                <div className="s">{date(b.date)} · {b.category}</div></div>
              <Money v={b.value} digits={0} />
            </button>))}
        </Panel>
      </div>
      {win !== "1" && <p className="note">Período anterior para comparação: {date(d.previous_range.start)} a {date(d.previous_range.end)}.</p>}
      {open && <EventDrawer id={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function Treemap({ cats, drill, color, onPick }: { cats: Cat[]; drill: Cat | null | undefined; color: (n: string) => string; onPick: (id: string) => void }) {
  const items = drill
    ? drill.children.filter((c) => c.value > 0).map((c) => ({ id: c.id, name: c.name, value: Math.round(c.value), base: drill.name }))
    : cats.map((c) => ({ id: c.id, name: c.name, value: Math.round(c.value), base: c.name }));
  const total = items.reduce((a, x) => a + x.value, 0) || 1;
  const surface = cssVar("--sheet");
  return (
    <Chart height={320} onClick={(p) => p.data?.id && onPick(p.data.id)} option={{
      legend: false,
      tooltip: { trigger: "item", formatter: (p: any) => `${p.name}<br/>${isPrivate() ? MASK : brl(p.value, 0)} · ${pct(p.value / total, 0)}` },
      series: [{
        type: "treemap", roam: false, nodeClick: false, breadcrumb: { show: false }, width: "100%", height: "100%", top: 0, left: 0, right: 0, bottom: 0,
        itemStyle: { borderColor: surface, borderWidth: 2, gapWidth: 2, borderRadius: 4 },
        label: { show: true, formatter: (p: any) => `{n|${p.name}}\n{v|${isPrivate() ? MASK : compact(p.value)} · ${pct(p.value / total, 0)}}`,
          rich: { n: { fontSize: 12, fontWeight: 600 }, v: { fontSize: 11, padding: [3, 0, 0, 0] } }, overflow: "truncate" },
        upperLabel: { show: false },
        data: items.map((x, i) => {
          const fill = color(x.base);
          return { ...x, itemStyle: { color: fill, opacity: drill ? Math.max(0.6, 1 - i * 0.07) : 1 },
            label: { color: inkOn(fill), rich: { n: { color: inkOn(fill) }, v: { color: inkOn(fill) } } } };
        }),
      }],
    }} />
  );
}

function Calendar({ daily, onPick }: { daily: { date: string; value: number }[]; onPick: (d: string) => void }) {
  if (!daily.length) return <p className="muted">Sem dias no período.</p>;
  const first = daily[0].date, last = daily[daily.length - 1].date;
  const months = (Number(last.slice(0, 4)) - Number(first.slice(0, 4))) * 12 + Number(last.slice(5, 7)) - Number(first.slice(5, 7)) + 1;
  const vals = daily.map((x) => Math.max(0, x.value)).sort((a, b) => a - b);
  const cap = vals[Math.floor(vals.length * 0.95)] || vals[vals.length - 1] || 1;  // um dia muito caro não apaga o resto
  const vertical = months <= 2;  // um ou dois meses: grade de semanas legível no celular
  const cell = vertical ? 34 : Math.max(9, Math.min(16, Math.floor(620 / (months * 4.6))));
  const weeks = Math.ceil(daily.length / 7) + 1;
  const height = vertical ? weeks * (cell - 6) + 50 : 7 * cell + 40;
  return (
    <>
      <Chart height={Math.max(150, height)} onClick={(p) => p.data?.[0] && onPick(p.data[0])} option={{
        legend: false,
        tooltip: { trigger: "item", formatter: (p: any) => `${date(p.data[0])}<br/>${isPrivate() ? MASK : brl(p.data[1], 0)}` },
        visualMap: { show: false, min: 0, max: cap, inRange: { color: seqRamp() } },
        calendar: {
          range: [first, last], orient: vertical ? "vertical" : "horizontal", cellSize: vertical ? [cell, cell - 6] : cell,
          top: vertical ? 30 : 26, left: vertical ? "center" : 30, right: vertical ? undefined : 8,
          splitLine: { show: false }, itemStyle: { borderColor: cssVar("--sheet"), borderWidth: 2, color: cssVar("--band") },
          yearLabel: { show: false }, dayLabel: { firstDay: 1, nameMap: ["D", "S", "T", "Q", "Q", "S", "S"], color: cssVar("--ink-3"), fontSize: 10 },
          monthLabel: { nameMap: ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"], color: cssVar("--ink-3"), fontSize: 10 },
        },
        series: [{ type: "heatmap", coordinateSystem: "calendar", data: daily.map((x) => [x.date, Math.round(x.value)]) }],
      }} />
      <div className="seq-legend" aria-hidden="true"><span>menos</span>{seqRamp().map((c) => <i key={c} style={{ background: c }} />)}<span>mais</span></div>
    </>
  );
}
