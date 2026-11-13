import { useState, type FormEvent } from "react";
import { Navigate, useLocation, type Location } from "react-router";
import { ApiError } from "../shared/api/client";
import { Button, ErrorMessage, Field } from "../shared/ui/controls";
import { Brand, OfflineNotice } from "./Shell";
import { useSession } from "./session";

export function LoginPage() {
  const { user, login } = useSession();
  // Весь адрес, а не только путь: ссылка вида /actions?id=… должна открыться целиком.
  const location = useLocation();
  const previous = (location.state as { from?: Location } | null)?.from;
  const fallback = new URLSearchParams(location.search).get("returnTo");
  const target = previous ? previous.pathname + previous.search + previous.hash : fallback;
  const from = target?.startsWith("/") && !target.startsWith("//") && !target.includes("\\") &&
    !/^\/login(?:[/?#]|$)/i.test(target) ? target : "/";
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
    <main className="standalone">
      <Brand />
      <OfflineNotice />
      <section className="panel login-panel">
        <h1>Вход в AI-buddy</h1>
        <form onSubmit={submit}>
          <Field label="Логин" name="login" autoComplete="username" required disabled={busy} />
          <Field label="Пароль" name="password" type="password" autoComplete="current-password" required disabled={busy} />
          {error && <ErrorMessage>{error}</ErrorMessage>}
          <Button type="submit" busy={busy} busyLabel="Входим…">Войти</Button>
        </form>
      </section>
    </main>
  );
}
