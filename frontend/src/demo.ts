/**
 * Modo vitrine (`npm run build:demo`): o app roda sem servidor, respondendo a API a partir de um retrato
 * gravado com dados fictícios (demo-data.json, gerado por scripts/demo_snapshot.py). Leitura apenas:
 * qualquer alteração responde com uma mensagem explicando que a demonstração não salva.
 */
import { setToday } from "./format";

export const DEMO = import.meta.env.VITE_DEMO === "1";

type Snapshot = { routes: Record<string, unknown>; events: any[]; categories: { id: string; parent_id: string | null }[]; period: string; today: string };

const READ_ONLY = "Esta é uma demonstração com dados fictícios: alterações não são salvas.";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

/** Chave estável para uma URL: caminho + parâmetros em ordem alfabética. */
export const routeKey = (url: URL) => {
  const p = [...url.searchParams.entries()].sort(([a], [b]) => a.localeCompare(b));
  return url.pathname + (p.length ? `?${new URLSearchParams(p).toString()}` : "");
};

/** Reproduz o filtro de /api/events do servidor sobre a lista completa gravada. */
export function filterEvents(snap: Pick<Snapshot, "events" | "categories">, sp: URLSearchParams) {
  const descendants = (id: string) => {
    const out = new Set([id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const c of snap.categories) if (c.parent_id && out.has(c.parent_id) && !out.has(c.id)) { out.add(c.id); grew = true; }
    }
    return out;
  };
  const month = sp.get("month"), account = sp.get("account"), category = sp.get("category"), type = sp.get("event_type");
  const merchant = sp.get("merchant"), q = sp.get("q")?.toLowerCase(), review = sp.get("review"), direction = sp.get("direction");
  const cats = category ? descendants(category) : null;
  const rows = snap.events.filter((e) =>
    !e.is_removed
    && (!month || String(e.date).startsWith(month))
    && (!account || e.account_id === account)
    && (!cats || cats.has(e.category_id))
    && (!type || type.split(",").includes(e.event_type))
    && (!merchant || String(e.merchant_id) === merchant)
    && (!review || String(e.needs_review) === review)
    && (direction !== "in" || e.amount > 0) && (direction !== "out" || e.amount < 0)
    && (!q || [e.description, e.counterparty, e.note].some((s) => s && String(s).toLowerCase().includes(q))));
  const page = Number(sp.get("page") ?? 1), size = Number(sp.get("page_size") ?? 100);
  return {
    total: rows.length, page, page_size: size,
    inflow: rows.filter((e) => e.amount > 0).reduce((a, e) => a + e.amount, 0),
    outflow: rows.filter((e) => e.amount < 0).reduce((a, e) => a + e.amount, 0),
    items: rows.slice((page - 1) * size, page * size),
  };
}

export async function installDemo() {
  const realFetch = window.fetch.bind(window);
  const snap: Snapshot = await (await realFetch("demo-data.json")).json();
  setToday(snap.today);
  const byPath = new Map<string, unknown>();
  Object.entries(snap.routes).forEach(([k, v]) => { const p = k.split("?")[0]; if (!byPath.has(p)) byPath.set(p, v); });

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, location.href);
    const path = url.pathname.slice(url.pathname.indexOf("/api/"));
    if (!path.startsWith("/api/")) return realFetch(input, init);
    const method = (init?.method ?? "GET").toUpperCase();
    if (path === "/api/auth/status") return json({ setup_required: false, user: "demo" });
    if (method !== "GET") return json({ detail: READ_ONLY }, 403);
    const local = new URL(path + url.search, location.origin);
    if (local.pathname === "/api/events") return json(filterEvents(snap, local.searchParams));
    const hit = snap.routes[routeKey(local)];
    if (hit !== undefined) return json(hit);
    // meses fora do período gravado não existem; para os demais parâmetros (ex.: janela de 3 anos), usa a versão gravada
    if (["month", "end", "ano"].some((k) => local.searchParams.has(k)))
      return json({ detail: `A demonstração tem dados de ${snap.period}.` }, 404);
    const near = byPath.get(local.pathname);
    if (near !== undefined) return json(near);
    return json({ detail: "Indisponível na demonstração." }, 404);
  };
}
