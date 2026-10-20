import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

export type ToastAction = { label: string; onClick: () => void };
type ToastFn = (msg: string, err?: boolean, action?: ToastAction) => void;

const ToastCtx = createContext<ToastFn>(() => {});

const SUCCESS_MS = 3800;
const ACTION_MS = 6000; // toast com "Desfazer"
const ERROR_MS = 7000; // erros ficam mais tempo na tela

export function ToastProvider({ children }: { children: ReactNode }) {
  const [t, setT] = useState<{ msg: string; err: boolean; key: number; action?: ToastAction } | null>(null);
  const timer = useRef<number>();
  const show = useCallback<ToastFn>((msg, err = false, action) => {
    window.clearTimeout(timer.current);
    setT({ msg, err, key: Date.now(), action });
    timer.current = window.setTimeout(() => setT(null), err ? ERROR_MS : action ? ACTION_MS : SUCCESS_MS);
  }, []);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {t && <div key={t.key} className={`toast ${t.err ? "err" : ""}`} role={t.err ? "alert" : "status"}>
        {t.msg}
        {t.action && (
          <button type="button" className="toast-action" onClick={() => { const fn = t.action!.onClick; window.clearTimeout(timer.current); setT(null); fn(); }}>
            {t.action.label}
          </button>
        )}
      </div>}
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);
