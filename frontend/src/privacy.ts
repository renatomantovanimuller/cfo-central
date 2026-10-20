import { useSyncExternalStore } from "react";

const KEY = "cfo.privacy";
export const MASK = "•••";

function read(): boolean {
  try { return localStorage.getItem(KEY) === "1"; } catch { return false; }
}

let hidden = read();
const listeners = new Set<() => void>();

export const isPrivate = () => hidden;

export function setPrivate(next: boolean) {
  hidden = next;
  try { localStorage.setItem(KEY, next ? "1" : "0"); } catch { /* armazenamento indisponível */ }
  listeners.forEach((l) => l());
}

export const togglePrivate = () => setPrivate(!hidden);

const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

/** Estado reativo do modo privacidade. */
export const usePrivacy = () => useSyncExternalStore(subscribe, isPrivate, isPrivate);
