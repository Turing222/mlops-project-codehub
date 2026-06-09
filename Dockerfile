# ==========================================
# Multi-target Dockerfile: 一个文件出两个镜像
#
#   make image-build                                  # tags via immutable IMAGE_TAG (git describe)
#   docker build --target web    -t "$DOCKER_IMAGE_NAME_WEB" .
#   docker build --target worker -t "$DOCKER_IMAGE_NAME_AI" .
#
#   web    → api + db_migrator (base + web extras)
#   worker → task_worker         (base + ai + worker extras)
# ==========================================

FROM ghcr.io/astral-sh/uv:0.10.7 AS uv-bin

# ──────────────────────────────────────────
# Stage 1: Base builder —— 只装共享依赖
# ──────────────────────────────────────────
FROM python:3.12-slim AS builder-base

COPY --from=uv-bin /uv /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY alembic.ini .
COPY alembic/ ./alembic/
COPY configs/ ./configs/
COPY backend/ ./backend/

# ──────────────────────────────────────────
# Stage 2a: Web builder —— 装 web extras
# ──────────────────────────────────────────
FROM builder-base AS builder-web

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra web


# ──────────────────────────────────────────
# Stage 2b: Worker builder —— 装 ai + worker extras
# ──────────────────────────────────────────
FROM builder-base AS builder-worker

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra ai --extra worker


# ──────────────────────────────────────────
# Stage 3a: Web Runtime (api + migrator)
# ──────────────────────────────────────────
FROM python:3.12-slim AS web

RUN groupadd -g 10001 appgroup && \
    useradd -r -u 10001 -g appgroup appuser

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

COPY --from=builder-web --chown=appuser:appgroup /app/.venv /app/.venv
COPY --from=builder-web --chown=appuser:appgroup /app/alembic.ini .
COPY --from=builder-web --chown=appuser:appgroup /app/alembic ./alembic
COPY --from=builder-web --chown=appuser:appgroup /app/configs ./configs
COPY --from=builder-web --chown=appuser:appgroup /app/backend ./backend

USER appuser

RUN /app/.venv/bin/python -c "import backend.main; print('✅ Web image: backend.main OK')"

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health_check/live', timeout=5)" \
    || exit 1

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", \
    "--host", "0.0.0.0", "--port", "8000", \
    "--proxy-headers", "--forwarded-allow-ips", "*"]

# ──────────────────────────────────────────
# Stage 3b: Worker Runtime (taskiq)
# ──────────────────────────────────────────
FROM python:3.12-slim AS worker

RUN groupadd -g 10001 appgroup && \
    useradd -r -u 10001 -g appgroup appuser

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

COPY --from=builder-worker --chown=appuser:appgroup /app/.venv /app/.venv
COPY --from=builder-worker --chown=appuser:appgroup /app/configs ./configs
COPY --from=builder-worker --chown=appuser:appgroup /app/backend ./backend

USER appuser

RUN /app/.venv/bin/python -c "import backend; print('✅ Worker image: backend module OK')"

CMD ["taskiq", "worker", "backend.infra.task_broker:broker", \
    "backend.worker.tasks.llm_tasks", \
    "backend.worker.tasks.knowledge_tasks", \
    "backend.worker.tasks.repo_analysis_tasks", \
    "--workers", "2"]
