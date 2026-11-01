import { ChevronLeft, ChevronRight, Search, X } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { type Cat, useCategories } from "./ui";

/**
 * Seletor de categoria em dois passos: escolhe a categoria macro e depois a subcategoria.
 * A busca atravessa as duas camadas (sem acento, por pedaço de palavra) e as últimas escolhas ficam no topo.
 * `onChange("")` limpa, quando `clearLabel` é dado.
 */
type Props = {
  value?: string | null;
  onChange: (id: string) => void;
  placeholder?: string;
  includePatrimonial?: boolean;
  /** "field": botão do tamanho de um select; "inline": discreto, para célula de tabela. */
  variant?: "field" | "inline";
  /** Texto da opção que limpa a escolha (filtro "Todas", "Automático"). Sem ele, não há como limpar. */
  clearLabel?: string;
  /** Em filtro, escolher a macro inclui as subcategorias: o texto da opção muda. */
  mode?: "classify" | "filter";
  ariaLabel?: string;
  disabled?: boolean;
};

const RECENT_KEY = "cfo.categoriasRecentes";
const MAX_RECENT = 6;
const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

function readRecent(): string[] {
  try { const v = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]"); return Array.isArray(v) ? v.filter((x) => typeof x === "string") : []; }
  catch { return []; }
}
function pushRecent(id: string) {
  try { localStorage.setItem(RECENT_KEY, JSON.stringify([id, ...readRecent().filter((x) => x !== id)].slice(0, MAX_RECENT))); }
  catch { /* armazenamento indisponível: só não lembra */ }
}

/** Palavras do dia a dia que levam à categoria certa ("uber" → Apps e táxi). Só para a busca. */
const SYNONYMS: Record<string, string> = {
  "alimentacao.delivery": "ifood rappi ze delivery entrega lanche",
  "alimentacao.mercado": "mercado supermercado atacadao assai carrefour pao de acucar feira hortifruti sacolao",
  "alimentacao.padaria": "padaria cafe cafeteria starbucks",
  "alimentacao.restaurantes": "restaurante bar lanchonete almoco jantar pizzaria hamburguer boteco",
  "assinaturas.musica": "spotify deezer apple music youtube music",
  "assinaturas.software": "google one icloud dropbox chatgpt claude microsoft office adobe github",
  "assinaturas.streaming": "netflix prime video disney max hbo globoplay",
  "compras.eletronicos": "celular notebook fone apple samsung kabum",
  "compras.online": "amazon mercado livre shopee shein aliexpress magalu",
  "compras.vestuario": "roupa sapato tenis renner riachuelo zara",
  "compras.presentes": "presente aniversario",
  "educacao.cursos": "curso udemy alura certificacao",
  "educacao.faculdade": "faculdade escola mensalidade pos graduacao",
  "findesp.tarifas": "tarifa pacote anuidade cesta",
  "findesp.juros": "juros encargos rotativo cheque especial",
  "finrec.dividendos": "dividendo jcp provento",
  "finrec.juros": "rendimento remuneracao conta",
  "impostos.ir": "darf irpf imposto de renda carne leao",
  "lazer.eventos": "cinema show ingresso teatro sympla",
  "lazer.hobbies": "esporte hobby",
  "lazer.viagens": "viagem hotel airbnb passagem aerea latam gol azul booking",
  "moradia.agua": "agua sabesp saneamento",
  "moradia.aluguel": "aluguel locacao quintoandar imobiliaria",
  "moradia.casa": "casa utensilios cama mesa banho decoracao",
  "moradia.eletro": "eletrodomestico movel moveis colchao geladeira fogao",
  "moradia.energia": "luz energia eletricidade enel cemig cpfl light",
  "moradia.gas": "gas botijao comgas",
  "moradia.internet": "internet tv vivo claro tim net fibra",
  "moradia.manutencao": "reparo reforma conserto encanador eletricista",
  "pat.aporte": "aplicacao investimento cdb tesouro",
  "pat.fatura": "fatura cartao pagamento de fatura",
  "pat.resgate": "resgate",
  "pat.transferencia": "transferencia entre contas mesma titularidade",
  "rec.salario": "salario holerite folha pagamento bolsa",
  "rec.beneficios": "vale refeicao alimentacao vr va beneficio auxilio",
  "rec.bonus": "bonus plr participacao",
  "rec.freela": "freela freelance servico prestado",
  "saude.academia": "academia smartfit gympass wellhub esporte",
  "saude.consultas": "medico consulta exame laboratorio clinica",
  "saude.farmacia": "farmacia remedio drogaria drogasil raia pague menos",
  "saude.plano": "plano de saude convenio unimed amil bradesco saude sulamerica",
  "servicos.celular": "celular telefone recarga plano movel",
  "servicos.seguros": "seguro",
  "terceiros.pf": "pix pessoa fisica ted amigo familia",
  "terceiros.pj": "boleto empresa pix cnpj",
  "terceiros.racha": "racha dividir conta splitwise",
  "transporte.apps": "uber 99 taxi cabify indriver",
  "transporte.combustivel": "posto gasolina etanol combustivel shell ipiranga br",
  "transporte.estacionamento": "estacionamento pedagio sem parar conectcar veloe",
  "transporte.manutencao": "oficina mecanico pneu revisao",
  "transporte.publico": "onibus metro trem bilhete unico sptrans",
  "transporte.seguro_impostos": "ipva licenciamento detran seguro auto multa",
};

type Tree = { roots: Cat[]; kids: Map<string, Cat[]>; byId: Map<string, Cat> };

function buildTree(cats: Cat[], includePatrimonial: boolean): Tree {
  const byId = new Map(cats.map((c) => [c.id, c]));
  const roots = cats.filter((c) => !c.parent_id && c.active && (includePatrimonial || c.nature !== "patrimonial"));
  const kids = new Map<string, Cat[]>();
  for (const c of cats) if (c.parent_id && c.active) kids.set(c.parent_id, [...(kids.get(c.parent_id) ?? []), c]);
  for (const v of kids.values()) v.sort((a, b) => a.name.localeCompare(b.name, "pt-BR"));
  return { roots, kids, byId };
}

const colorOf = (t: Tree, c?: Cat | null): string | undefined =>
  c ? c.color ?? (c.parent_id ? t.byId.get(c.parent_id)?.color ?? undefined : undefined) : undefined;

const Dot = ({ color }: { color?: string }) => <span className="cp-dot" style={{ background: color ?? "var(--rule-strong)" }} aria-hidden />;

export function CategoryPicker({ value, onChange, placeholder = "Categoria…", includePatrimonial = true, variant = "field",
  clearLabel, mode = "classify", ariaLabel, disabled }: Props) {
  const { data = [] } = useCategories();
  const tree = useMemo(() => buildTree(data, includePatrimonial), [data, includePatrimonial]);
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const cur = value ? tree.byId.get(value) : undefined;
  const parent = cur?.parent_id ? tree.byId.get(cur.parent_id) : undefined;

  const pick = (id: string) => {
    if (id) pushRecent(id);
    setOpen(false);
    btn.current?.focus();
    if (id !== (value ?? "")) onChange(id);
  };

  return (
    <>
      <button ref={btn} type="button" className={`cp-trigger cp-${variant}`} disabled={disabled} aria-haspopup="dialog" aria-expanded={open}
        aria-label={ariaLabel ?? (cur ? `Categoria: ${parent ? parent.name + ", " : ""}${cur.name}. Trocar` : placeholder)}
        title={cur ? (parent ? `${parent.name} › ${cur.name}` : cur.name) : undefined}
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}>
        {cur ? <><Dot color={colorOf(tree, cur)} />
          <span className="cp-label">{parent && variant === "field" && <span className="cp-parent">{parent.name} › </span>}{cur.name}</span></>
          : <span className="cp-label cp-placeholder">{clearLabel ?? placeholder}</span>}
        <ChevronRight size={14} className="cp-caret" aria-hidden />
      </button>
      {open && <Popover anchor={btn.current} tree={tree} value={value ?? ""} clearLabel={clearLabel} mode={mode}
        onPick={pick} onClose={() => setOpen(false)} />}
    </>
  );
}

type Row = { id: string; label: ReactNode; sub?: string; color?: string; drill?: boolean; key: string };

function Popover({ anchor, tree, value, clearLabel, mode, onPick, onClose }: {
  anchor: HTMLElement | null; tree: Tree; value: string; clearLabel?: string; mode: "classify" | "filter";
  onPick: (id: string) => void; onClose: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [root, setRoot] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const [pos, setPos] = useState<{ top?: number; bottom?: number; left: number; width: number; maxH: number } | null>(null);
  const sheet = typeof window !== "undefined" && window.matchMedia("(max-width: 640px)").matches;

  // Posição fixa, presa ao botão: escapa de tabelas com rolagem e do drawer.
  useLayoutEffect(() => {
    if (sheet || !anchor) return;
    const place = () => {
      const r = anchor.getBoundingClientRect();
      const width = Math.min(360, window.innerWidth - 16);
      const left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8));
      const below = window.innerHeight - r.bottom - 12, above = r.top - 12;
      if (below >= 300 || below >= above) setPos({ top: r.bottom + 4, left, width, maxH: Math.min(420, below) });
      else setPos({ bottom: window.innerHeight - r.top + 4, left, width, maxH: Math.min(420, above) });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [anchor, sheet]);

  useEffect(() => {
    // No celular, abrir o teclado esconderia metade da lista: o foco vai para o painel e a busca fica a um toque.
    if (sheet) box.current?.focus({ preventScroll: true }); else input.current?.focus({ preventScroll: true });
    const down = (e: MouseEvent | TouchEvent) => {
      const t = e.target as Node;
      if (box.current?.contains(t) || anchor?.contains(t)) return;
      onClose();
    };
    document.addEventListener("mousedown", down);
    document.addEventListener("touchstart", down);
    return () => { document.removeEventListener("mousedown", down); document.removeEventListener("touchstart", down); };
  }, [anchor, onClose, sheet]);

  const recent = useMemo(() => readRecent().map((id) => tree.byId.get(id)).filter((c): c is Cat => !!c && c.active
    && tree.roots.some((r) => r.id === (c.parent_id ?? c.id))), [tree]);

  const rows: Row[] = useMemo(() => {
    const nq = norm(q.trim());
    const nameOf = (c: Cat) => tree.byId.get(c.parent_id ?? "")?.name;
    if (nq) {
      const terms = nq.split(/\s+/);
      const scored: { c: Cat; s: number }[] = [];
      for (const r of tree.roots) {
        for (const c of [r, ...(tree.kids.get(r.id) ?? [])]) {
          const own = norm(c.name), syn = SYNONYMS[c.id] ?? "", hay = `${own} ${c.parent_id ? norm(r.name) : ""} ${syn}`;
          if (!terms.every((t) => hay.includes(t))) continue;
          // Começo do nome vale mais; nome próprio vale mais que o da macro; sinônimo vale menos.
          const s = (own.startsWith(terms[0]) ? 0 : own.includes(terms[0]) ? 1 : syn.includes(terms[0]) ? 2 : 3) + (c.parent_id ? 0 : 0.5);
          scored.push({ c, s });
        }
      }
      scored.sort((a, b) => a.s - b.s || a.c.name.localeCompare(b.c.name, "pt-BR"));
      return scored.slice(0, 40).map(({ c }) => ({ key: c.id, id: c.id, label: <Highlight text={c.name} q={terms} />,
        sub: c.parent_id ? nameOf(c) : "categoria macro", color: colorOf(tree, c) }));
    }
    if (root) {
      const r = tree.byId.get(root)!;
      const kids = tree.kids.get(root) ?? [];
      return [
        { key: `${root}:self`, id: root, label: mode === "filter" ? `Toda “${r.name}”` : `Só “${r.name}”`,
          sub: mode === "filter" ? "inclui as subcategorias" : kids.length ? "sem subcategoria" : undefined, color: colorOf(tree, r) },
        ...kids.map((c) => ({ key: c.id, id: c.id, label: c.name, color: colorOf(tree, c) })),
      ];
    }
    return [
      ...(clearLabel ? [{ key: ":clear", id: "", label: clearLabel, sub: undefined, color: undefined }] : []),
      ...recent.map((c) => ({ key: `r:${c.id}`, id: c.id, label: c.name, sub: c.parent_id ? nameOf(c) : undefined, color: colorOf(tree, c) })),
      ...tree.roots.map((r) => ({ key: `m:${r.id}`, id: r.id, label: r.name, color: colorOf(tree, r),
        drill: (tree.kids.get(r.id)?.length ?? 0) > 0, sub: tree.kids.get(r.id)?.length ? `${tree.kids.get(r.id)!.length}` : undefined })),
    ];
  }, [q, root, tree, recent, clearLabel, mode]);

  useEffect(() => { setActive(0); }, [q, root]);
  useEffect(() => { box.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" }); }, [active]);

  const choose = (r: Row) => (r.drill ? (setRoot(r.id), setQ(""), sheet ? box.current?.focus() : input.current?.focus()) : onPick(r.id));
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); if (root || q) { setRoot(null); setQ(""); } else onClose(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(rows.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); const r = rows[active]; if (r) choose(r); }
    else if (e.key === "ArrowRight" && !q) { const r = rows[active]; if (r?.drill) { e.preventDefault(); choose(r); } }
    else if ((e.key === "ArrowLeft" || e.key === "Backspace") && !q && root) { e.preventDefault(); setRoot(null); }
  };

  const recentCount = !q && !root ? recent.length : 0;
  const clearCount = !q && !root && clearLabel ? 1 : 0;
  const rootRow = root ? tree.byId.get(root) : null;

  const body = (
    <div ref={box} className={`cp-pop ${sheet ? "sheet" : ""}`} role="dialog" aria-label="Escolher categoria" tabIndex={-1} onKeyDown={onKey}
      onClick={(e) => e.stopPropagation()}
      style={sheet ? undefined : pos ? { top: pos.top, bottom: pos.bottom, left: pos.left, width: pos.width, maxHeight: pos.maxH } : { visibility: "hidden" }}>
      <div className="cp-head">
        {rootRow && !q ? (
          <button type="button" className="btn ghost sm cp-back" onClick={() => { setRoot(null); input.current?.focus(); }}>
            <ChevronLeft size={15} /> <Dot color={colorOf(tree, rootRow)} /> {rootRow.name}</button>
        ) : <span className="cp-step">{q ? "Resultados" : "1. Escolha a categoria macro"}</span>}
        {sheet && <button type="button" className="btn ghost sm" aria-label="Fechar" onClick={onClose}><X size={16} /></button>}
      </div>
      <label className="cp-search"><Search size={14} aria-hidden />
        <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar: mercado, uber, luz, netflix…"
          aria-label="Buscar categoria" role="combobox" aria-expanded aria-controls="cp-list" aria-activedescendant={rows[active] ? `cp-o-${active}` : undefined} />
        {q && <button type="button" className="cp-x" aria-label="Limpar busca" onClick={() => { setQ(""); input.current?.focus(); }}><X size={13} /></button>}
      </label>
      {rootRow && !q && <div className="cp-step" style={{ padding: "2px 12px 4px" }}>2. Escolha a subcategoria</div>}
      <ul id="cp-list" className="cp-list" role="listbox">
        {rows.length === 0 && <li className="cp-empty">Nada com “{q}”. Tente outra palavra ou navegue pelas macros.</li>}
        {rows.map((r, i) => (
          <li key={r.key}>
            {i === clearCount && recentCount > 0 && <div className="cp-group">Usadas por último</div>}
            {i === clearCount + recentCount && !q && !root && <div className="cp-group">Categorias macro</div>}
            <button type="button" id={`cp-o-${i}`} data-i={i} role="option" aria-selected={r.id === value && !r.drill}
              className={`cp-opt ${i === active ? "active" : ""} ${r.id === value || (r.drill && tree.byId.get(value)?.parent_id === r.id) ? "current" : ""}`}
              onMouseMove={() => setActive(i)} onClick={() => choose(r)}>
              {r.key !== ":clear" && <Dot color={r.color} />}
              <span className="cp-name">{r.label}</span>
              {r.sub && <span className="cp-sub">{r.sub}</span>}
              {r.drill && <ChevronRight size={14} className="cp-caret" aria-hidden />}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
  return createPortal(<>{sheet && <div className="cp-backdrop" onClick={onClose} />}{body}</>, document.body);
}

function Highlight({ text, q }: { text: string; q: string[] }) {
  const n = norm(text);
  const t = q.find((x) => n.includes(x));
  if (!t) return <>{text}</>;
  const i = n.indexOf(t);
  return <>{text.slice(0, i)}<mark>{text.slice(i, i + t.length)}</mark>{text.slice(i + t.length)}</>;
}
