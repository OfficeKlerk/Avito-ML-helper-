import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, test } from "vitest";
import { createApi } from "./client";
import { useApiData } from "./useApiData";

const api = createApi({ baseUrl: "http://test", getToken: () => null, fetch: async () => new Response("{}") });

test("ответ мутации не перезаписывается чтением, начатым до неё", async () => {
  const pending: ((value: string) => void)[] = [];
  const load = () => new Promise<string>((resolve) => pending.push(resolve));
  const { result } = renderHook(() => useApiData(api, load));
  act(() => pending[0]("черновик"));
  await waitFor(() => expect(result.current.state).toEqual({ status: "ready", data: "черновик" }));

  act(() => result.current.reload()); // опрос ушёл
  act(() => result.current.replace("на согласовании")); // а ответ подтверждения пришёл раньше
  await act(async () => pending[1]("черновик")); // старое чтение вернулось последним
  expect(result.current.state).toEqual({ status: "ready", data: "на согласовании" });

  act(() => result.current.reload()); // следующее чтение уже свежее
  await act(async () => pending[2]("согласована"));
  expect(result.current.state).toEqual({ status: "ready", data: "согласована" });
});
