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

FROM ghcr.io/astral-sh/uv:0.11.32 AS uv-bin

# ──────────────────────────────────────────
# Stage 1: Base builder —— 只装共享依赖
# ──────────────────────────────────────────
FROM python:3.14-slim AS builder-base

COPY --from=uv-bin /uv /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ──────────────────────────────────────────
# Stage 2a: Web builder —— 装 web extras
# ──────────────────────────────────────────
FROM builder-base AS builder-web

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra web --no-install-project

COPY alembic.ini .
COPY alembic/ ./alembic/
COPY configs/ ./configs/
COPY backend/ ./backend/


# ──────────────────────────────────────────
# Stage 2b: Worker builder —— 装 ai + worker extras
# ──────────────────────────────────────────
FROM builder-base AS builder-worker

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra ai --extra worker --no-install-project

COPY configs/ ./configs/
COPY backend/ ./backend/


# ──────────────────────────────────────────
# Stage 3a: Web Runtime (api + migrator)
# ──────────────────────────────────────────
FROM python:3.14-slim AS web

RUN apt-get update \
    && apt-get -y upgrade --no-install-recommends \
        libssl3t64 openssl openssl-provider-legacy \
    && rm -rf /var/lib/apt/lists/*

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

# FORWARDED_ALLOW_IPS must be set at runtime; the previous image default of "*"
# let any client forge X-Real-IP. Loopback fallback keeps `docker run` safe.
CMD ["sh", "-c", "exec uvicorn backend.main:app \
    --host 0.0.0.0 --port 8000 \
    --proxy-headers \
    --forwarded-allow-ips ${FORWARDED_ALLOW_IPS:-127.0.0.1} \
    --timeout-graceful-shutdown ${UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN:-30}"]

# ──────────────────────────────────────────
# Stage 3b: Worker Runtime (taskiq)
# ──────────────────────────────────────────
FROM python:3.14-slim AS worker

RUN apt-get update \
    && apt-get -y upgrade --no-install-recommends \
        libssl3t64 openssl openssl-provider-legacy \
    && rm -rf /var/lib/apt/lists/*

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

# Task modules are driven by TASKIQ_MODULES so a single image serves the
# standard task list and any future scheduled tasks without code changes.
CMD ["sh", "-c", "exec taskiq worker backend.infra.task_broker:broker \
    ${TASKIQ_MODULES:-backend.worker.tasks.llm_tasks backend.worker.tasks.knowledge_tasks backend.worker.tasks.repo_analysis_tasks backend.worker.tasks.credit_tasks backend.worker.tasks.chat_recovery_tasks backend.worker.tasks.operability_tasks} \
    --workers ${TASKIQ_WORKERS:-2} \
    --wait-tasks-timeout ${TASKIQ_WAIT_TASKS_TIMEOUT:-105} \
    --shutdown-timeout ${TASKIQ_SHUTDOWN_TIMEOUT:-10}"]
