import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { useSession } from "../../app/session";
import { ApiError, call, newIdempotencyKey, type Api, type Schemas } from "../../shared/api/client";
import { Button, ErrorMessage, Loading, Status } from "../../shared/ui/controls";
import { formatDocumentDate, getDocument, sourceUrl } from "./documents";
import { Markdown } from "./Markdown";
import { clearPendingTurn, readPendingTurn, savePendingTurn } from "./pendingTurn";
import "./chat.css";

const historyLimit = 50;
const messageLimit = 4000;

type Message = Schemas["ChatMessage"];
type Source = Schemas["Source"];
type Metadata = Pick<Schemas["Document"], "updated_at" | "disclaimer">;
type History = { messages: Message[] } | { error: string } | null;

export function ChatPage() {
  const { api, user } = useSession();
  return user && <Chat api={api} userId={user.id} />;
}

function Chat({ api, userId }: { api: Api; userId: string }) {
  const [pending, setPending] = useState(() => readPendingTurn(userId));
  const [draft, setDraft] = useState(pending?.text ?? "");
  const [sendError, setSendError] = useState(pending ? "Результат отправки ещё не подтверждён. Можно повторить тот же запрос." : "");
  const [sending, setSending] = useState(false);
  const activeSend = useRef<AbortController | null>(null);
  const [history, setHistory] = useState<History>(null);
  const [historyAttempt, setHistoryAttempt] = useState(0);
  const sources = useSourceMetadata(api, history && "messages" in history ? history.messages : undefined);
  const messageLength = Array.from(draft.trim()).length;

  useEffect(() => {
    const controller = new AbortController();
    call(api.GET("/api/chat/messages", { params: { query: { limit: historyLimit } }, signal: controller.signal })).then(
      ({ messages }) => { if (!controller.signal.aborted) setHistory({ messages }); },
      (error: unknown) => {
        if (!controller.signal.aborted) setHistory({ error: error instanceof ApiError ? error.message : "Не удалось загрузить историю." });
      },
    );
    return () => controller.abort();
  }, [api, historyAttempt]);

  useEffect(() => () => { activeSend.current?.abort(); }, []);

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (activeSend.current || !history || "error" in history || messageLength === 0 || messageLength > messageLimit) return;

    const turn = pending ?? { key: newIdempotencyKey(), text: draft.trim() };
    const controller = new AbortController();
    activeSend.current = controller;
    savePendingTurn(userId, turn);
    setPending(turn);
    setSending(true);
    setSendError("");
    try {
      const { user_message, assistant_message } = await call(api.POST("/api/chat/messages", {
        params: { header: { "Idempotency-Key": turn.key } },
        body: { text: turn.text },
        signal: controller.signal,
      }));
      if (controller.signal.aborted) return;
      clearPendingTurn();
      setPending(null);
      setDraft("");
      setHistory((current) => {
        if (!current || "error" in current) return current;
        const byId = new Map(current.messages.map((message) => [message.id, message]));
        byId.set(user_message.id, user_message);
        byId.set(assistant_message.id, assistant_message);
        const messages = [...byId.values()].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
        return { messages: messages.slice(-historyLimit) };
      });
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 429) {
        clearPendingTurn();
        setPending(null);
      }
      if (error instanceof ApiError && error.status === 429) {
        setSendError("Сервер ещё обрабатывает сообщение или ограничил частоту запросов. Повтори отправку чуть позже.");
      } else if (error instanceof ApiError && error.code === "timeout") {
        setSendError("Сервер не подтвердил результат вовремя. Повтори отправку, чтобы получить результат того же запроса.");
      } else {
        setSendError(error instanceof ApiError ? error.message : "Не удалось получить результат. Повтори отправку.");
      }
    } finally {
      activeSend.current = null;
      if (!controller.signal.aborted) setSending(false);
    }
  }

  return (
    <section className="page-stack">
      <h1>Чат</h1>
      {!history ? <Loading>Загружаем историю…</Loading> : "error" in history ? (
        <ErrorMessage onRetry={() => {
          setHistory(null);
          setHistoryAttempt((value) => value + 1);
        }}>{history.error}</ErrorMessage>
      ) : history.messages.length ? (
        <ol className="plain-list message-list" aria-label="История диалога">
          {history.messages.map((message) => <ChatMessage key={message.id} message={message} sources={sources} />)}
        </ol>
      ) : (
        <div className="panel empty-state">
          <p>Задай первый вопрос. Например, спроси, что делать дальше или во сколько у команды стендап.</p>
        </div>
      )}
      <form className="panel content-panel chat-form" onSubmit={send}>
        <div className="field">
          <label htmlFor="chat-message">Сообщение</label>
          <textarea id="chat-message" name="message" rows={3} value={draft} readOnly={!!pending}
            onChange={(event) => setDraft(event.target.value)} aria-describedby="chat-message-hint"
            aria-invalid={messageLength > messageLimit || undefined} />
          <small id="chat-message-hint" className={messageLength > messageLimit ? "field-error" : undefined}>
            {messageLength > messageLimit ? "Сократи сообщение до 4000 символов." : "До 4000 символов."}
          </small>
        </div>
        {sendError && <ErrorMessage>{sendError}</ErrorMessage>}
        {sending && <Loading>Ждём ответа помощника…</Loading>}
        <Button type="submit" disabled={!history || "error" in history || messageLength === 0 || messageLength > messageLimit}
          busy={sending} busyLabel="Отправляем…">{pending ? "Повторить отправку" : "Отправить"}</Button>
      </form>
    </section>
  );
}

function ChatMessage({ message, sources }: { message: Message; sources: ReadonlyMap<string, Metadata | null> }) {
  const assistant = message.role === "assistant";
  return (
    <li className={`panel message message--${message.role}`}>
      <div className="card-heading">
        <strong>{assistant ? "AI-buddy" : "Вы"}</strong>
        {message.status === "degraded" && <Status tone="warning">Упрощённый ответ</Status>}
        {message.status === "error" && <Status tone="danger">Не удалось ответить</Status>}
      </div>
      {assistant ? <Markdown text={message.text} /> : <p className="message-text">{message.text}</p>}
      {assistant && message.sources.length > 0 && <SourceList sources={message.sources} metadata={sources} />}
    </li>
  );
}

function SourceList({ sources, metadata }: { sources: Source[]; metadata: ReadonlyMap<string, Metadata | null> }) {
  return (
    <div className="chat-sources">
      <strong>Источники</strong>
      <ul className="plain-list">
        {sources.map((source) => {
          const details = metadata.get(source.doc_id);
          return (
            <li key={source.chunk_id}>
              <Link to={sourceUrl(source)}>{source.title}{source.section && <span> · {source.section}</span>}</Link>
              {details ? <div className="source-metadata">
                <span>Обновлено <time dateTime={details.updated_at}>{formatDocumentDate(details.updated_at)}</time></span>
                {details.disclaimer && <Status tone="warning">{details.disclaimer}</Status>}
              </div> : details === null ? <small>Дата и пометка источника недоступны.</small> : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function useSourceMetadata(api: Api, messages: Message[] | undefined) {
  const [metadata, setMetadata] = useState<ReadonlyMap<string, Metadata | null>>(() => new Map());
  const ids = new Set(messages?.flatMap((message) => message.sources.map((source) => source.doc_id)));
  const missing = [...ids].filter((id) => !metadata.has(id)).sort().join(",");

  useEffect(() => {
    if (!missing) return;
    const controller = new AbortController();
    // Update once per batch so one completed document does not restart the others.
    void Promise.all(missing.split(",").map(async (id) => {
      try {
        const { updated_at, disclaimer } = await getDocument(api, id, controller.signal);
        return [id, { updated_at, disclaimer }] as const;
      } catch {
        return [id, null] as const;
      }
    })).then((results) => {
      if (!controller.signal.aborted) setMetadata((current) => new Map([...current, ...results]));
    });
    return () => controller.abort();
  }, [api, missing]);

  return metadata;
}
