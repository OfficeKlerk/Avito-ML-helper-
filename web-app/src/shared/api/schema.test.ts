// @vitest-environment node
import { readFileSync } from "node:fs";
import openapiTS, { astToString } from "openapi-typescript";
import { expect, test } from "vitest";

test("schema.ts совпадает с contracts/a_core_api.yaml (иначе: npm run gen:api)", async () => {
  const fresh = astToString(await openapiTS(new URL("../../../../contracts/a_core_api.yaml", import.meta.url)));
  const actual = readFileSync(new URL("./schema.ts", import.meta.url), "utf8");
  expect(actual.replaceAll("\r\n", "\n")).toContain(fresh.trim());
}, 20_000);
