import { useId, type ComponentProps, type ReactNode } from "react";

type ButtonProps = ComponentProps<"button"> & {
  tone?: "primary" | "secondary" | "quiet";
  busy?: boolean;
  busyLabel?: string;
};

export function Button({ tone = "primary", busy = false, busyLabel, disabled, type = "button", className, children, ...props }: ButtonProps) {
  return (
    <button {...props} type={type} className={`button button--${tone}${className ? " " + className : ""}`}
      disabled={disabled || busy} aria-busy={busy || undefined}>
      {busy && <span className="spinner" aria-hidden="true" />}
      {busy && busyLabel ? busyLabel : children}
    </button>
  );
}

type FieldProps = ComponentProps<"input"> & { label: string; hint?: string; error?: string };

export function Field({ label, hint, error, id: suppliedId, "aria-describedby": describedBy, "aria-invalid": invalid, ...props }: FieldProps) {
  const generated = useId();
  const id = suppliedId ?? generated;
  const description = [describedBy, hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ");
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input {...props} id={id} aria-invalid={error ? true : invalid} aria-describedby={description || undefined} />
      {hint && <small id={`${id}-hint`}>{hint}</small>}
      {error && <small className="field-error" id={`${id}-error`}>{error}</small>}
    </div>
  );
}

export function Loading({ children = "Загружаем данные…" }: { children?: ReactNode }) {
  return <p className="loading" role="status"><span className="spinner" aria-hidden="true" />{children}</p>;
}

export function ErrorMessage({ children, onRetry }: { children: ReactNode; onRetry?: () => void }) {
  return (
    <div className="error-message">
      <p role="alert">{children}</p>
      {onRetry && <Button tone="secondary" onClick={onRetry}>Повторить</Button>}
    </div>
  );
}

export function Status({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "active" | "success" | "warning" | "danger" }) {
  return <span className={`status status--${tone}`}>{children}</span>;
}
