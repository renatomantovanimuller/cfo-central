/** Web Push no navegador: registra o service worker e inscreve este aparelho nas notificações do CFO Central. */
import { api } from "./api";

export const pushSupported = () =>
  typeof window !== "undefined" && window.isSecureContext && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

export const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent);
export const isStandalone = () =>
  window.matchMedia?.("(display-mode: standalone)").matches || (navigator as any).standalone === true;

export function registerServiceWorker() {
  if (!pushSupported()) return;
  navigator.serviceWorker.register("/sw.js").catch(() => { /* sem service worker o app funciona igual, só sem push */ });
}

const keyBytes = (b64url: string) => {
  const b64 = (b64url + "=".repeat((4 - (b64url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
};

/** Inscrição atual deste aparelho (ou null). */
export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  const reg = await navigator.serviceWorker.getRegistration();
  return (await reg?.pushManager.getSubscription()) ?? null;
}

export async function subscribeThisDevice(publicKey: string, nome: string) {
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error(perm === "denied" ? "Notificações bloqueadas para este site. Libere nas configurações do navegador." : "Permissão não concedida.");
  const reg = (await navigator.serviceWorker.getRegistration()) ?? (await navigator.serviceWorker.register("/sw.js"));
  await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  const key = keyBytes(publicKey);
  // inscrição feita com outra chave do servidor não recebe nada: refaz
  const same = sub?.options.applicationServerKey &&
    new Uint8Array(sub.options.applicationServerKey as ArrayBuffer).every((b, i) => b === key[i]);
  if (sub && !same) { await sub.unsubscribe(); sub = null; }
  sub = sub ?? await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
  return api<any>("/api/push/subscribe", { method: "POST", body: { subscription: sub.toJSON(), nome } });
}

export async function unsubscribeThisDevice(id: string) {
  const sub = await currentSubscription();
  await sub?.unsubscribe().catch(() => undefined);
  return api<any>(`/api/push/subscribe/${id}`, { method: "DELETE" });
}

export async function endpointId(endpoint: string) {
  const h = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(endpoint));
  return Array.from(new Uint8Array(h)).map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 12);
}
