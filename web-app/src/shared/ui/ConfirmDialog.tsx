import { useEffect, useId, useRef, type ReactNode } from "react";
import { Button, ErrorMessage } from "./controls";

type ConfirmDialogProps = {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel?: string;
  busy?: boolean;
  error?: string;
  onConfirm: () => void;
  onClose: () => void;
};

export function ConfirmDialog({
  open, title, children, confirmLabel = "Подтвердить", busy = false, error, onConfirm, onClose,
}: ConfirmDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const element = dialog.current;
    if (!element || !open) return;
    const previous = document.activeElement;
    element.showModal();
    cancel.current?.focus();
    return () => {
      element.close();
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, [open]);

  useEffect(() => {
    if (open && busy) dialog.current?.focus();
    if (open && error && !busy) cancel.current?.focus();
  }, [open, busy, error]);

  return (
    <dialog ref={dialog} className="dialog" aria-labelledby={titleId} aria-describedby={descriptionId}
      onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
      <h2 id={titleId}>{title}</h2>
      <div id={descriptionId}>{children}</div>
      {error && <ErrorMessage>{error}</ErrorMessage>}
      <div className="dialog-actions">
        <Button ref={cancel} tone="secondary" disabled={busy} onClick={onClose}>Назад</Button>
        <Button busy={busy} busyLabel="Выполняется…" onClick={onConfirm}>{confirmLabel}</Button>
      </div>
    </dialog>
  );
}
