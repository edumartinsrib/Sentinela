# Build a partir da raiz do monorepo:  docker build -f sentinela-api/Dockerfile .
FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv
# O venv é criado no mesmo caminho da imagem final (scripts têm shebang absoluto).
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY sentinela-core/pyproject.toml sentinela-core/pyproject.toml
COPY sentinela-api/pyproject.toml sentinela-api/pyproject.toml
COPY sentinela-runner/pyproject.toml sentinela-runner/pyproject.toml
RUN uv sync --frozen --no-dev --no-install-workspace --package sentinela-api
COPY sentinela-core sentinela-core
COPY sentinela-api sentinela-api
RUN uv sync --frozen --no-dev --no-editable --package sentinela-api

FROM python:3.12-slim-bookworm
RUN useradd --uid 10001 --create-home sentinela
COPY --from=build /app/.venv /app/.venv
COPY sentinela-api/alembic.ini /app/alembic.ini
COPY sentinela-api/migrations /app/migrations
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 SENTINELA_PORT=8000
WORKDIR /app
USER sentinela
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
# Migrações antes de subir (idempotente). Com várias réplicas, rode `alembic upgrade head`
# como job de implantação e suba as réplicas com SENTINELA_SKIP_MIGRATIONS=true.
CMD ["sh", "-c", "if [ \"$SENTINELA_SKIP_MIGRATIONS\" != true ]; then alembic upgrade head || exit 1; fi; exec sentinela-api"]
