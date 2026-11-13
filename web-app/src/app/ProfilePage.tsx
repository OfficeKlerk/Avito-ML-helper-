import { useSession, type User } from "./session";

const ROLE: Record<User["role"], string> = { intern: "Стажёр", mentor: "Наставник", manager: "Руководитель", hr: "HR" };

export function ProfilePage() {
  const { user, logout } = useSession();
  if (!user) return null; // страница стоит за RequireAuth
  const rows: [string, string | number | null | undefined][] = [
    ["Роль", ROLE[user.role]],
    ["Команда", user.team?.name],
    ["Неделя стажировки", user.internship_week],
    ["Наставник", user.mentor?.name],
    ["Руководитель", user.manager?.name],
  ];
  return (
    <main>
      <h1>Привет, {user.name}</h1>
      <dl>
        {rows.filter(([, value]) => value != null).map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <button type="button" onClick={logout}>Выйти</button>
    </main>
  );
}
