// Попадает в bundle, поэтому здесь только адрес API. Секреты в VITE_* не кладём.
// По умолчанию — адрес самой страницы: /api отдаёт прокси (в разработке — Vite).
export const apiBaseUrl = (import.meta.env.VITE_API_URL || globalThis.location?.origin || "").replace(/\/+$/, "");
