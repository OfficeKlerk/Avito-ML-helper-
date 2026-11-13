import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { useSession } from "../../app/session";
import { ApiError, type Schemas } from "../../shared/api/client";
import { ErrorMessage, Loading, Status } from "../../shared/ui/controls";
import { formatDocumentDate, getDocument, splitDocument } from "./documents";
import { Markdown } from "./Markdown";

type DocumentState = { document: Schemas["Document"] } | { error: string; retryable: boolean } | null;

export function DocumentPage() {
  const { docId = "", anchor } = useParams();
  return <DocumentReader key={docId} docId={docId} anchor={anchor} />;
}

function DocumentReader({ docId, anchor }: { docId: string; anchor?: string }) {
  const { api } = useSession();
  const [state, setState] = useState<DocumentState>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getDocument(api, docId, controller.signal).then(
      (document) => { if (!controller.signal.aborted) setState({ document }); },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const status = error instanceof ApiError ? error.status : 0;
        if (status === 403 || status === 404) {
          setState({ error: status === 403 ? "У вас нет доступа к этому документу." : "Документ не найден.", retryable: false });
        } else {
          setState({ error: error instanceof ApiError ? error.message : "Не удалось загрузить документ.", retryable: true });
        }
      },
    );
    return () => controller.abort();
  }, [api, docId, attempt]);

  const back = <Link to="/chat">Вернуться в чат</Link>;
  if (!state || "error" in state) {
    return (
      <section className="page-stack">
        {back}
        <h1>Источник</h1>
        {!state ? <Loading>Загружаем документ…</Loading> : <ErrorMessage onRetry={state.retryable ? () => {
          setState(null);
          setAttempt((value) => value + 1);
        } : undefined}>{state.error}</ErrorMessage>}
      </section>
    );
  }

  const { document } = state;
  const { introduction, sections } = splitDocument(document.text);
  const selected = sections.find((section) => section.anchor === anchor);
  return (
    <section className="page-stack">
      <div className="button-row">
        {back}
        {selected && <Link to={`/chat/sources/${encodeURIComponent(docId)}`}>Весь документ</Link>}
      </div>
      <article className="panel content-panel">
        <h1>{document.title}</h1>
        <p className="muted">Обновлено <time dateTime={document.updated_at}>{formatDocumentDate(document.updated_at)}</time></p>
        {document.disclaimer && <Status tone="warning">{document.disclaimer}</Status>}
        {anchor && !selected && <p role="status">Цитируемого раздела больше нет. Ниже показана текущая версия документа.</p>}
        {!selected && introduction && <Markdown text={introduction} />}
        {(selected ? [selected] : sections).map((section) => (
          <section className="document-section" key={section.anchor} aria-labelledby={`section-${section.anchor}`}>
            <h2 id={`section-${section.anchor}`}>{section.title}</h2>
            <Markdown text={section.lines.join("\n")} />
          </section>
        ))}
      </article>
    </section>
  );
}
