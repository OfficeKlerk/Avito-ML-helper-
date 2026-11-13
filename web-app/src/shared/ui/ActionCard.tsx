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

export function ActionCard({ action, footer }: { action: Schemas["ActionCard"]; footer?: ReactNode }) {
  const [label, tone] = labels[action.status];
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
      {action.result?.message && <p>{action.result.message}</p>}
      {action.error && <p className="field-error">{action.error}</p>}
      {footer && <div className="card-footer">{footer}</div>}
    </article>
  );
}
