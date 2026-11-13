import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { expect, test } from "vitest";
import { routes } from "./routes";

test("главная страница открывается через роутер", () => {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: ["/"] })} />);
  expect(screen.getByRole("heading", { name: "AI-buddy" })).toBeInTheDocument();
});
