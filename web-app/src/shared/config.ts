// Попадает в bundle, поэтому здесь только адрес API. Секреты в VITE_* не кладём.
export const apiBaseUrl = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");
