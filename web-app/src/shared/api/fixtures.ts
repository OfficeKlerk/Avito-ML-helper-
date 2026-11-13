// Транспорт по примерам из fixtures/a_core_api: только для тестов, в приложение не подключается.
type Fixture = {
  operation: string;
  method: string;
  path: string;
  cases: { name: string; response: { status: number; body: unknown } }[];
};

const fixtures = Object.values(
  import.meta.glob<Fixture>("../../../../fixtures/a_core_api/*.json", { eager: true, import: "default" }),
);

/** Отвечает первым случаем примера или тем, что выбран: { auth_login: "wrong_password" }. */
export function fixtureFetch(pick: Record<string, string> = {}) {
  return async (request: Request): Promise<Response> => {
    const path = new URL(request.url).pathname;
    const fixture = fixtures.find(
      (f) => f.method === request.method && new RegExp(`^${f.path.replace(/\{[^}]+\}/g, "[^/]+")}$`).test(path),
    );
    if (!fixture) throw new Error(`Нет примера для ${request.method} ${path}`);
    const name = pick[fixture.operation];
    const chosen = name ? fixture.cases.find((c) => c.name === name) : fixture.cases[0];
    if (!chosen) throw new Error(`Нет случая ${name} в ${fixture.operation}`);
    return Response.json(chosen.response.body, { status: chosen.response.status });
  };
}
