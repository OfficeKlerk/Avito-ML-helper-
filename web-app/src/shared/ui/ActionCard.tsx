import type { ReactNode } from "react";
import type { Schemas } from "../api/client";
import { Status } from "./controls";

const labels = {
  draft: ["Черновик", "neutral"],
  submitted: ["На согласовании", "active"],
  approved: ["Согласована", "success"],
  rejected: ["Отклонена", "danger"],
  cancelled: ["Отменена", "neutral"],
  failed: ["Ошибка отправки", "danger"],
} as const satisfies Record<Schemas["ActionCard"]["status"], readonly [string, string]>;

// Согласование доступа — ещё не выдача: «выдан» только когда сервер подтвердил fulfilled_at.
type Tone = "neutral" | "active" | "success" | "warning" | "danger";

function statusLabel(action: Schemas["ActionCard"]): readonly [string, Tone] {
  if (action.type === "access_request" && action.status === "approved") {
    return action.fulfilled_at ? ["Доступ выдан", "success"] : ["Согласована, доступ ещё не выдан", "warning"];
  }
  return labels[action.status];
}

export function ActionCard({ action, footer }: { action: Schemas["ActionCard"]; footer?: ReactNode }) {
  const [label, tone] = statusLabel(action);
  return (
    <article className="panel action-card">
      <div className="card-heading">
        <div><p className="muted">{action.type === "access_request" ? "Доступ" : "Отгул или отпуск"}</p><h2>{action.title}</h2></div>
        <Status tone={tone}>{label}</Status>
      </div>
      <dl className="card-fields">
        {Object.entries(action.fields).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}
        {action.external_id && <div><dt>Идентификатор заявки</dt><dd>{action.external_id}</dd></div>}
        {action.result?.external_ref && <div><dt>Номер заявки</dt><dd>{action.result.external_ref}</dd></div>}
      </dl>
      {/* После отмены сохранённый текст отправки («ушла на согласование») уже неправда. */}
      {action.status === "cancelled" ? <p>Заявка отменена.</p> : action.result?.message && <p>{action.result.message}</p>}
      {action.error && <p className="field-error">{action.error}</p>}
      {footer && <div className="card-footer">{footer}</div>}
    </article>
  );
}
