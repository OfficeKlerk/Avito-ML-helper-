import { useEffect, useRef, useState } from "react";
import { isRouteErrorResponse, Link, NavLink, Outlet, useLocation, useRouteError } from "react-router";
import { Button, ErrorMessage } from "../shared/ui/controls";
import { Icon } from "../shared/ui/icons";
import { sections } from "./navigation";
import { useSession } from "./session";

export function Brand() {
  return <Link to="/" className="brand"><span className="brand-mark"><Icon name="spark" /></span>AI-buddy</Link>;
}

export function OfflineNotice() {
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    function update() { setOnline(navigator.onLine); }
    window.addEventListener("offline", update);
    window.addEventListener("online", update);
    return () => {
      window.removeEventListener("offline", update);
      window.removeEventListener("online", update);
    };
  }, []);
  return <div className="offline" role="status" hidden={online}>Нет подключения к интернету. После восстановления сети можно повторить запрос.</div>;
}

export function Shell() {
  const { user, logout } = useSession();
  const { pathname } = useLocation();
  const content = useRef<HTMLElement>(null);
  const previousPath = useRef(pathname);
  useEffect(() => {
    const section = sections.find(({ path }) => pathname === path || pathname.startsWith(path + "/"));
    document.title = `${section?.label ?? (pathname === "/" ? "Профиль" : "Страница не найдена")} · AI-buddy`;
    if (previousPath.current !== pathname) {
      previousPath.current = pathname;
      content.current?.focus();
    }
  }, [pathname]);

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content" onClick={(event) => {
        event.preventDefault();
        content.current?.focus();
      }}>К содержанию</a>
      <aside className="sidebar">
        <Brand />
        <nav className="primary-nav" aria-label="Основная навигация">
          <NavLink to="/" end><Icon name="home" /><span>Профиль</span></NavLink>
          {sections.map(({ path, label, icon }) => <NavLink key={path} to={path}><Icon name={icon} /><span>{label}</span></NavLink>)}
        </nav>
        <div className="account">
          <span className="avatar" aria-hidden="true">{user?.name.trim().charAt(0).toUpperCase() || "A"}</span>
          <div className="account-text"><strong>{user?.name}</strong><span>{user?.team?.name}</span></div>
          <Button tone="quiet" className="sign-out" onClick={logout} aria-label="Выйти из аккаунта" title="Выйти из аккаунта"><Icon name="logout" /></Button>
        </div>
      </aside>
      <div className="workspace">
        <OfflineNotice />
        <main id="main-content" ref={content} tabIndex={-1}><Outlet /></main>
      </div>
    </div>
  );
}

export function PageNotFound() {
  return (
    <section className="panel state-page">
      <h1>Страница не найдена</h1>
      <p className="muted">Проверьте адрес или вернитесь в профиль.</p>
      <Link className="button button--primary" to="/">В профиль</Link>
    </section>
  );
}

export function RouteError() {
  const error = useRouteError();
  if (isRouteErrorResponse(error) && error.status === 404) return <PageNotFound />;
  return (
    <section className="panel state-page">
      <h1>Не удалось открыть страницу</h1>
      <ErrorMessage>Обновите страницу или вернитесь в профиль.</ErrorMessage>
      <div className="button-row">
        <Button onClick={() => window.location.reload()}>Обновить страницу</Button>
        <Link className="button button--secondary" to="/">В профиль</Link>
      </div>
    </section>
  );
}
