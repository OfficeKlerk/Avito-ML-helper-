import { useCallback, useEffect, useRef, useState, type SetStateAction } from "react";
import { ApiError, type Api } from "./client";

export type Load<T> = (api: Api, signal: AbortSignal) => Promise<T>;
type State<T> = { status: "loading" } | { status: "error"; message: string } |
  { status: "ready"; data: T; refreshError?: string };

/** При refreshInterval повторяем чтение только на видимой вкладке. */
export function useApiData<T>(api: Api, load: Load<T>, refreshInterval?: number) {
  const [state, setState] = useState<State<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const revision = useRef(0);
  useEffect(() => {
    let request: AbortController | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;

    function read() {
      if (request || (refreshInterval && document.hidden)) return;
      clearTimeout(timer);
      const controller = new AbortController();
      request = controller;
      const startedAt = revision.current;
      void load(api, controller.signal).then(
        (data) => {
          if (!controller.signal.aborted && startedAt === revision.current) setState({ status: "ready", data });
        },
        (error: unknown) => {
          if (controller.signal.aborted || startedAt !== revision.current) return;
          const message = error instanceof ApiError ? error.message : "Не удалось загрузить данные.";
          setState((current) => refreshInterval && current.status === "ready"
            ? { ...current, refreshError: message }
            : { status: "error", message });
        },
      ).finally(() => {
        if (controller.signal.aborted) return;
        request = undefined;
        if (refreshInterval && !document.hidden) timer = setTimeout(read, refreshInterval);
      });
    }

    function pause() {
      clearTimeout(timer);
      request?.abort();
      request = undefined;
    }

    function visibilityChanged() {
      if (document.hidden) pause();
      else read();
    }

    read();
    if (refreshInterval) {
      document.addEventListener("visibilitychange", visibilityChanged);
      window.addEventListener("focus", read);
    }
    return () => {
      pause();
      document.removeEventListener("visibilitychange", visibilityChanged);
      window.removeEventListener("focus", read);
    };
  }, [api, load, attempt, refreshInterval]);

  const reload = useCallback(() => {
    setState((current) => current.status === "error" ? { status: "loading" } : current);
    setAttempt((n) => n + 1);
  }, []);
  const replace = useCallback((data: SetStateAction<T>) => {
    revision.current += 1;
    setState((current) => {
      if (typeof data !== "function") return { status: "ready", data };
      if (current.status !== "ready") return current;
      return { ...current, data: (data as (previous: T) => T)(current.data) };
    });
  }, []);
  return { state, reload, replace };
}
