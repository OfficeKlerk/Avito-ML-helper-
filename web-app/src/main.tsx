import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { routes } from "./app/routes";
import { SessionProvider } from "./app/session";
import "./app/styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SessionProvider>
      <RouterProvider router={createBrowserRouter(routes)} />
    </SessionProvider>
  </StrictMode>,
);
