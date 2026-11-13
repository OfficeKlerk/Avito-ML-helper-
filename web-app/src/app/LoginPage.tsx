import { useState, type FormEvent } from "react";
import { Navigate, useLocation, type Location } from "react-router";
import { ApiError } from "../shared/api/client";
import { useSession } from "./session";

export function LoginPage() {
  const { user, login } = useSession();
  // Весь адрес, а не только путь: ссылка вида /actions?id=… должна открыться целиком.
  const from = (useLocation().state as { from?: Location } | null)?.from ?? "/";
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={from} replace />;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      // После входа user появится, и страница сама уйдёт на from.
      await login(String(form.get("login")).trim(), String(form.get("password")));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не получилось войти. Попробуй ещё раз.");
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>Вход в AI-buddy</h1>
      <form onSubmit={submit}>
        <label>
          Логин
          <input name="login" autoComplete="username" required />
        </label>
        <label>
          Пароль
          <input name="password" type="password" autoComplete="current-password" required />
        </label>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? "Входим…" : "Войти"}</button>
      </form>
    </main>
  );
}
