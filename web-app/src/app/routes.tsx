import type { RouteObject } from "react-router";
import { LoginPage } from "./LoginPage";
import { ProfilePage } from "./ProfilePage";
import { RequireAuth } from "./session";

// Модули H, O, R добавляют свои страницы в children защищённой ветки; навигация и 404 — задача F5.
export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  { element: <RequireAuth />, children: [{ index: true, element: <ProfilePage /> }] },
];
