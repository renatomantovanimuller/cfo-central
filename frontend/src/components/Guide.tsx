import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { brl, dateTime, today } from "../format";
import { MASK, usePrivacy } from "../privacy";

type Item = { id: string; chave: string; nivel: "importante" | "atencao" | "info" | "bom"; titulo: string; texto: string;
  texto_claude?: string; acao?: { label: string; to: string } | null };
type Lembrete = { data: string; titulo: string; valor: number | null; to?: string; aproximado?: boolean };
export type Guia = {
  em: string; manchete: { texto: string } | null; itens: Item[]; proximos: Lembrete[]; tudo_em_dia: boolean;
  briefing: { resumo: string; gerado_em: string } | null; briefing_ultimo: string | null;
};

const SEEN_KEY = "cfo.guia.vistos";
const VISIBLE = 4;
const NIVEL_LABEL: Record<Item["nivel"], string> = { importante: "Importante", atencao: "Atenção", info: "Para saber", bom: "Boa notícia" };
const BRL_RE = /−?-?R\$\s?[\d.]+(,\d{1,2})?/g;

const readSeen = (): string[] => { try { return JSON.parse(localStorage.getItem(SEEN_KEY) ?? "[]"); } catch { return []; } };
const writeSeen = (v: string[]) => { try { localStorage.setItem(SEEN_KEY, JSON.stringify(v.slice(-200))); } catch { /* armazenamento indisponível */ } };

/** "hoje", "amanhã", "sex 31/10". */
function quando(iso: string) {
  const d = new Date(`${iso}T12:00:00`);
  const t = today();
  t.setHours(12, 0, 0, 0);
  const dias = Math.round((d.getTime() - t.getTime()) / 86_400_000);
  if (dias === 0) return "hoje";
  if (dias === 1) return "amanhã";
  return `${d.toLocaleDateString("pt-BR", { weekday: "short" }).replace(".", "")} ${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
}

/** Guia do CFO: o que importa hoje e o que vem nos próximos dias, em linguagem simples. */
export function Guide() {
  const nav = useNavigate();
  const hidden = usePrivacy();
  const q = useQuery({ queryKey: ["guide"], queryFn: () => api<Guia>("/api/guide"), staleTime: 60_000 });
  const [seen, setSeen] = useState<string[]>(readSeen);
  const [all, setAll] = useState(false);
  const g = q.data;
  if (!g) return null;
  const txt = (s: string) => (hidden ? s.replace(BRL_RE, MASK) : s);
  const itens = g.itens.filter((i) => !seen.includes(i.chave));
  const shown = all ? itens : itens.slice(0, VISIBLE);
  const dismiss = (i: Item) => { const next = [...seen, i.chave]; setSeen(next); writeSeen(next); };
  const lead = g.briefing?.resumo ?? g.manchete?.texto
    ?? (g.tudo_em_dia ? "Tudo em dia. Nada pedindo sua atenção agora." : "Alguns pontos merecem sua atenção.");

  return (
    <section className="panel guide" aria-label="Seu CFO hoje">
      <div className="panel-head">
        <h2>Seu CFO hoje</h2>
        <span className="hint">{g.briefing ? `resumo do Claude · ${dateTime(g.briefing.gerado_em)}` : "a partir dos seus dados conferidos"}</span>
      </div>
      <div className="panel-body">
        <p className="guide-lead">{txt(lead)}</p>
        {g.briefing && g.manchete && <p className="soft small guide-sub">{txt(g.manchete.texto)}</p>}

        {shown.length > 0 && (
          <ul className="guide-items">
            {shown.map((i) => (
              <li key={i.chave} className={`guide-item ${i.nivel}`}>
                <span className="guide-mark" aria-hidden />
                <div className="grow">
                  <div className="t"><span className="sr-only">{NIVEL_LABEL[i.nivel]}: </span>{txt(i.titulo)}</div>
                  <div className="s">{txt(i.texto_claude ?? i.texto)}</div>
                </div>
                <div className="guide-actions">
                  {i.acao && <button className="btn sm" onClick={() => nav(i.acao!.to)}>{i.acao.label}</button>}
                  <button className="btn sm ghost" onClick={() => dismiss(i)} title="Esconder até a situação mudar">Entendi</button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {itens.length > VISIBLE && (
          <button className="btn sm ghost" onClick={() => setAll(!all)}>{all ? "Mostrar menos" : `Mais ${itens.length - VISIBLE}`}</button>
        )}
        {itens.length === 0 && g.itens.length > 0 && <p className="note">Você já viu todos os avisos de hoje.</p>}

        {g.proximos.length > 0 && (
          <div className="guide-next">
            <div className="lbl">Próximos dias</div>
            <ul>
              {g.proximos.map((p, k) => (
                <li key={k} onClick={() => p.to && nav(p.to)} style={{ cursor: p.to ? "pointer" : undefined }}>
                  <span className="when">{quando(p.data)}</span>
                  <span className="grow">{p.titulo}</span>
                  {p.valor !== null && <span className="num">{p.aproximado ? "≈ " : ""}{brl(p.valor)}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}
