# Runner do Sentinela: git + Claude Code + GitHub Copilot CLI.
# Build a partir da raiz do monorepo:  docker build -f sentinela-runner/Dockerfile .
#
# As CLIs de IA são opcionais na imagem (o runner anuncia só o que encontra no PATH):
#   --build-arg INSTALL_CLAUDE_CODE=false   --build-arg INSTALL_COPILOT_CLI=false
# e as versões ficam fixáveis para builds reprodutíveis:
#   --build-arg CLAUDE_CODE_VERSION=2.1.0   --build-arg COPILOT_CLI_VERSION=0.0.400
FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY sentinela-core/pyproject.toml sentinela-core/pyproject.toml
COPY sentinela-api/pyproject.toml sentinela-api/pyproject.toml
COPY sentinela-runner/pyproject.toml sentinela-runner/pyproject.toml
RUN uv sync --frozen --no-dev --no-install-workspace --package sentinela-runner
COPY sentinela-core sentinela-core
COPY sentinela-runner sentinela-runner
RUN uv sync --frozen --no-dev --no-editable --package sentinela-runner

FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm
ARG INSTALL_CLAUDE_CODE=true
ARG INSTALL_COPILOT_CLI=true
ARG CLAUDE_CODE_VERSION=latest
ARG COPILOT_CLI_VERSION=latest
# Node 22 (a Copilot CLI exige 22+), copiado da imagem oficial.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && if [ "$INSTALL_CLAUDE_CODE" = true ]; then \
         npm install -g --no-audit --no-fund "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"; fi \
    && if [ "$INSTALL_COPILOT_CLI" = true ]; then \
         npm install -g --no-audit --no-fund "@github/copilot@${COPILOT_CLI_VERSION}"; fi \
    && npm cache clean --force \
    && useradd --uid 10001 --create-home sentinela \
    && mkdir -p /var/lib/sentinela-runner && chown sentinela /var/lib/sentinela-runner
COPY --from=build /app/.venv /app/.venv
# Sem atualização automática nem telemetria das CLIs dentro do container.
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 \
    SENTINELA_RUNNER_HOME=/var/lib/sentinela-runner \
    DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
USER sentinela
# Identidade do runner (token próprio) e áreas de trabalho das revisões.
VOLUME ["/var/lib/sentinela-runner"]
CMD ["sentinela-runner"]
