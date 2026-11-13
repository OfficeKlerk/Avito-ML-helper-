import type { RouteObject } from "react-router";
import { LoginPage } from "./LoginPage";
import { ProfilePage } from "./ProfilePage";
import { ActionPage, ActionsPage, ChatPage, NotificationsPage, OnboardingPage } from "./SectionPages";
import { PageNotFound, RouteError, Shell } from "./Shell";
import { RequireAuth } from "./session";

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage />, errorElement: <main className="standalone"><RouteError /></main> },
  {
    element: <RequireAuth />,
    errorElement: <main className="standalone"><RouteError /></main>,
    children: [{
      element: <Shell />,
      children: [{
        errorElement: <RouteError />,
        children: [
          { index: true, element: <ProfilePage /> },
          { path: "chat", element: <ChatPage /> },
          { path: "onboarding", element: <OnboardingPage /> },
          { path: "onboarding/tasks/:taskId", element: <OnboardingPage /> },
          { path: "actions", element: <ActionsPage /> },
          { path: "actions/:actionId", element: <ActionPage /> },
          { path: "notifications", element: <NotificationsPage /> },
          { path: "notifications/:notificationId", element: <NotificationsPage /> },
          { path: "*", element: <PageNotFound /> },
        ],
      }],
    }],
  },
];
