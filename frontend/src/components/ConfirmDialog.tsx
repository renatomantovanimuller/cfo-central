import { ReactNode, useEffect, useRef } from "react";

type Props = {
  title: string;
  /** Nome do item afetado, mostrado em destaque. */
  itemName?: string;
  children?: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

/** Diálogo de confirmação acessível: foco no botão de confirmar, Esc cancela, Tab fica dentro do diálogo. */
export function ConfirmDialog({ title, itemName, children, confirmLabel, danger = false, onConfirm, onCancel }: Props) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    confirmRef.current?.focus();
    return () => previous?.focus?.();
  }, []);
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.stopPropagation(); onCancel(); return; }
    if (e.key !== "Tab") return;
    const first = cancelRef.current, last = confirmRef.current;
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
  };
  return (
    <div className="confirm-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" onKeyDown={onKeyDown}>
        <h3 id="confirm-title">{title}</h3>
        <p>{itemName && <strong>{itemName}</strong>}{itemName && children ? " · " : ""}{children}</p>
        <div className="confirm-actions">
          <button ref={cancelRef} type="button" className="btn" onClick={onCancel}>Cancelar</button>
          <button ref={confirmRef} type="button" className={`btn ${danger ? "danger" : "primary"}`} onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
