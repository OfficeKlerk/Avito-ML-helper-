FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY prompts ./prompts
# Схемы контрактов: docker build --build-context contracts=../contracts (так делают Makefile и Compose).
COPY --from=contracts . ./contracts
ENV CONTRACTS_DIR=/srv/contracts

# Тесты: docker build --target test -t <имя> . && docker run --rm <имя>
FROM base AS test
COPY requirements-dev.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests ./tests
COPY evals ./evals
COPY --from=data . ./data
ENV DATA_DIR=/srv/data EVAL_REPORTS_DIR=/srv/evals/reports
COPY --from=fixtures . ./fixtures
ENV FIXTURES_DIR=/srv/fixtures
CMD ["python", "-m", "pytest", "-p", "no:cacheprovider"]

FROM base AS runtime
RUN useradd --create-home app
USER app
ENV PORT=8090
EXPOSE 8090
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 8 --timeout 60 'app:create_app()'"]
