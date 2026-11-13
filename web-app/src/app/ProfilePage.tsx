import { Link } from "react-router";
import { Icon } from "../shared/ui/icons";
import { Status } from "../shared/ui/controls";
import { sections } from "./navigation";
import { useSession, type User } from "./session";

const ROLE: Record<User["role"], string> = { intern: "Стажёр", mentor: "Наставник", manager: "Руководитель", hr: "HR" };

export function ProfilePage() {
  const { user } = useSession();
  if (!user) return null;
  const rows: [string, string | number | null | undefined][] = [
    ["Команда", user.team?.name],
    ["Неделя стажировки", user.internship_week],
    ["Наставник", user.mentor?.name],
    ["Руководитель", user.manager?.name],
  ];
  return (
    <div className="page-stack">
      <header className="welcome">
        <div>
          <p className="welcome-kicker">Ваш профиль</p>
          <h1>Привет, {user.name}</h1>
        </div>
        <Status tone="active">{ROLE[user.role]}</Status>
      </header>
      <section aria-label="Быстрые переходы" className="quick-links">
        {sections.map(({ path, label, description, icon }) => (
          <Link className="panel quick-link" to={path} key={path}>
            <span className={`quick-icon quick-icon--${icon}`}><Icon name={icon} /></span>
            <span className="quick-label"><strong>{label}</strong><span>{description}</span></span>
            <span className="quick-arrow"><Icon name="arrow" /></span>
          </Link>
        ))}
      </section>
      <section className="panel profile-panel">
        <h2>О вас</h2>
        <dl className="profile-fields">
          {rows.filter(([, value]) => value != null).map(([label, value]) => (
            <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
          ))}
        </dl>
      </section>
    </div>
  );
}
