ARG NODE_IMAGE=node:22.16.0-bookworm-slim
ARG RUNTIME_IMAGE=ghcr.io/astral-sh/uv@sha256:ef305979f94d4729707a0fc98444ebf1bc0e63a2d2919a62d28fcc3e42957508
FROM ${NODE_IMAGE} AS web
WORKDIR /web
COPY package.json package-lock.json tsconfig.json vite.config.ts ./
COPY web/ ./web/
RUN npm ci --no-audit --no-fund && npm run build

FROM ${RUNTIME_IMAGE}
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY longlive/ ./longlive/
COPY configs/workers.example.yaml ./configs/workers.example.yaml
COPY --from=web /web/dist/ ./dist/
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"]
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "longlive.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--ws-max-size", "4096"]
