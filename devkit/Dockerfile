# Сборка из корня репозитория: docker build -f devkit/Dockerfile .
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 REPO_ROOT=/repo
WORKDIR /repo/devkit
COPY devkit/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY contracts /repo/contracts
COPY fixtures /repo/fixtures
COPY data /repo/data
COPY devkit/devkit ./devkit

# Тесты: docker build -f devkit/Dockerfile --target test -t <имя> . && docker run --rm <имя>
FROM base AS test
COPY devkit/requirements-dev.txt devkit/pyproject.toml ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY devkit/tests ./tests
CMD ["python", "-m", "pytest", "-p", "no:cacheprovider"]

FROM base AS runtime
RUN useradd --create-home app
USER app
ENV PORT=8000
CMD ["python", "-m", "devkit.stub_server"]
