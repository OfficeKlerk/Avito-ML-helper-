FROM node:22-alpine AS deps
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
FROM nginx:1.28-alpine AS runtime
COPY nginx/default.conf.template /etc/nginx/templates/
COPY --chmod=755 nginx/15-check-config.sh /docker-entrypoint.d/
COPY --from=build /srv/dist /usr/share/nginx/html
