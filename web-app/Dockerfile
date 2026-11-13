FROM node:22-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a AS deps
WORKDIR /srv
COPY package.json package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY . .

# Тесты: docker build --target test -t <имя> . && docker run --rm <имя>
FROM deps AS test
# Тесты клиента сверяются с контрактом A и его примерами: --build-context contracts=… fixtures=… (так делает Makefile).
COPY --from=contracts . /contracts
COPY --from=fixtures . /fixtures
CMD ["sh", "-c", "npm run typecheck && npm test"]

# Production-сборка в /srv/dist.
FROM deps AS build
ARG VITE_API_URL=
RUN npm run build

# Статика и прокси /api в core-api на порту 80. Адрес core-api — CORE_API_URL.
FROM nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236 AS runtime
COPY nginx/default.conf.template /etc/nginx/templates/
COPY --chmod=755 nginx/15-check-config.sh /docker-entrypoint.d/
COPY --from=build /srv/dist /usr/share/nginx/html
