import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Браузер ходит в core-api по /api того же адреса: в разработке путь проксирует Vite,
// в сборке — единый вход (задача D2). CORS не нужен.
const proxy = { "/api": process.env.API_PROXY_TARGET ?? "http://localhost:8080" };

export default defineConfig({
  plugins: [react()],
  server: { proxy },
  preview: { proxy },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    // Файлы без тестов тоже входят в отчёт с 0%, иначе покрытие завышено.
    coverage: { include: ["src/**/*.{ts,tsx}"], exclude: ["src/**/*.test.tsx", "src/test-setup.ts", "src/vite-env.d.ts"] },
  },
});
