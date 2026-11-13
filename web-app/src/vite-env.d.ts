/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Адрес core-api без завершающего «/». Пусто — тот же адрес, что у страницы. */
  readonly VITE_API_URL?: string;
}
