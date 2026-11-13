import { useCallback, useEffect, useState } from "react";
import { ApiError, type Api } from "./client";

export type Load<T> = (api: Api, signal: AbortSignal) => Promise<T>;
type State<T> = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: T };

/** Данные с сервера. reload() перечитывает их, не убирая с экрана текущие; replace() ставит ответ мутации. */
export function useApiData<T>(api: Api, load: Load<T>) {
  const [state, setState] = useState<State<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    load(api, controller.signal).then(
      (data) => { if (!controller.signal.aborted) setState({ status: "ready", data }); },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setState({ status: "error", message: error instanceof ApiError ? error.message : "Не удалось загрузить данные." });
        }
      },
    );
    return () => controller.abort();
  }, [api, load, attempt]);
  const reload = useCallback(() => {
    // После ошибки показываем загрузку, чтобы «Повторить» было видно; свежие данные с экрана не убираем.
    setState((current) => current.status === "error" ? { status: "loading" } : current);
    setAttempt((n) => n + 1);
  }, []);
  const replace = useCallback((data: T) => setState({ status: "ready", data }), []);
  return { state, reload, replace };
}
