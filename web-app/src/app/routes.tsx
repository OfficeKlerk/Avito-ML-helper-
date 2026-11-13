import type { RouteObject } from "react-router";

// Модули H, O, R добавляют сюда свои маршруты; навигация и 404 — задача F5.
export const routes: RouteObject[] = [
  {
    path: "/",
    element: (
      <main>
        <h1>AI-buddy</h1>
        <p>Помощник стажёра. Интерфейс в разработке.</p>
      </main>
    ),
  },
];
