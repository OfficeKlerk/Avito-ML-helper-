FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

# Тесты из корня репозитория: make test-knowledge-service (передаёт build contexts).
FROM base AS test
COPY requirements-dev.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests ./tests
COPY evals ./evals
# Same named build contexts already supplied by Makefile to every test image.
COPY --from=data . ./data
COPY --from=contracts . ./contracts
COPY --from=fixtures . ./fixtures
ENV KB_DIR=/srv/data/kb CONTRACTS_DIR=/srv/contracts FIXTURES_DIR=/srv/fixtures DATA_DIR=/srv/data
CMD ["python", "-m", "pytest", "-p", "no:cacheprovider"]

FROM base AS runtime
RUN useradd --create-home app
USER app
ENV PORT=8060
EXPOSE 8060
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 2 --timeout 60 'app:create_app()'"]
