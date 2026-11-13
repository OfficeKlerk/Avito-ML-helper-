FROM node:22-alpine AS deps
WORKDIR /srv
COPY package.json package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY . .

# Тесты: docker build --target test -t <имя> . && docker run --rm <имя>
FROM deps AS test
CMD ["sh", "-c", "npm run typecheck && npm test"]

# Production-сборка в /srv/dist. Отдачу статики и прокси /api добавляют D1/D2.
FROM deps AS build
ARG VITE_API_URL=
RUN npm run build
