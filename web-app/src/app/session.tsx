import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router";
import { Button, ErrorMessage, Loading } from "../shared/ui/controls";
import { ApiError, call, createApi, type Api, type Schemas } from "../shared/api/client";

export type User = Schemas["User"];

// JWT лежит в sessionStorage: переживает перезагрузку вкладки, пропадает при её закрытии
// и сам не уходит с запросами, поэтому CSRF не страшен. Скрипты страницы его читают,
// поэтому интерфейс не вставляет чужой HTML. Профиль не храним — после перезагрузки берём /api/me.
const TOKEN_KEY = "ai-buddy.token";

function readToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null; // хранилище запрещено браузером — вход живёт до перезагрузки
  }
}

function writeToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // см. readToken
  }
}

type Session = {
  api: Api;
  token: string | null;
  user: User | null;
  /** Ошибка проверки сохранённого входа, кроме 401. */
  error: string | null;
  login: (login: string, password: string) => Promise<void>;
  logout: () => void;
  retry: () => void;
};

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children, fetch }: { children: ReactNode; fetch?: (r: Request) => Promise<Response> }) {
  const [token, setToken] = useState(readToken);
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const tokenRef = useRef(token);
  tokenRef.current = token;

  const logout = useCallback(() => {
    tokenRef.current = null;
    writeToken(null);
    setToken(null);
    setUser(null);
    setError(null);
  }, []);

  const api = useMemo(() => createApi({ getToken: () => tokenRef.current, onUnauthorized: logout, fetch }), [fetch, logout]);

  useEffect(() => {
    if (!token || user) return;
    const controller = new AbortController();
    setError(null);
    call(api.GET("/api/me", { signal: controller.signal })).then(
      (profile) => { if (!controller.signal.aborted && tokenRef.current === token) setUser(profile); },
      (e: unknown) => {
        if (!controller.signal.aborted && tokenRef.current === token && e instanceof ApiError && e.code !== "unauthorized") {
          setError(e.message);
        }
      },
    );
    return () => controller.abort();
  }, [api, token, user, attempt]);

  const login = useCallback(async (login: string, password: string) => {
    const signedIn = await call(api.POST("/api/auth/login", { body: { login, password } }));
    writeToken(signedIn.token);
    tokenRef.current = signedIn.token;
    setToken(signedIn.token);
    setUser(signedIn.user);
  }, [api]);

  const value = useMemo(
    () => ({ api, token, user, error, login, logout, retry: () => setAttempt((n) => n + 1) }),
    [api, token, user, error, login, logout],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession вне SessionProvider");
  return session;
}

/** Пускает дальше только после проверки входа. Данные страниц пересоздаются при смене пользователя. */
export function RequireAuth() {
  const { token, user, error, logout, retry } = useSession();
  const location = useLocation();
  if (!token) {
    const returnTo = location.pathname + location.search + location.hash;
    return <Navigate to={`/login?${new URLSearchParams({ returnTo })}`} replace state={{ from: location }} />;
  }
  if (error || !user) return (
    <main className="standalone">
      {error ? <>
        <h1>Не удалось проверить вход</h1>
        <ErrorMessage onRetry={retry}>{error}</ErrorMessage>
        <Button tone="quiet" onClick={logout}>Выйти</Button>
      </> : <Loading>Проверяем вход…</Loading>}
    </main>
  );
  return <Outlet key={user.id} />;
}
