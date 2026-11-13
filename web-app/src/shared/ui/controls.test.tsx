import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { Button, Field } from "./controls";

test("кнопка сообщает об ожидании и блокирует повторное нажатие", () => {
  const onClick = vi.fn();
  const { rerender } = render(<Button onClick={onClick}>Сохранить</Button>);
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  rerender(<Button busy busyLabel="Сохраняем…" onClick={onClick}>Сохранить</Button>);
  const busyButton = screen.getByRole("button", { name: "Сохраняем…" });
  expect(busyButton).toBeDisabled();
  expect(busyButton).toHaveAttribute("aria-busy", "true");
  fireEvent.click(busyButton);
  expect(onClick).toHaveBeenCalledTimes(1);
});

test("поле связывает подпись, подсказку и ошибку", () => {
  render(<Field label="Комментарий" hint="До 200 символов." error="Заполните поле." required />);
  const input = screen.getByRole("textbox", { name: "Комментарий" });
  expect(input).toBeRequired();
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(input).toHaveAccessibleDescription("До 200 символов. Заполните поле.");
});
