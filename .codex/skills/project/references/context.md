# Dewflow Context

## Overview

Dewflow is a monorepo: a Python backend plus a React admin frontend.

Backend is a Python 3.12 FastAPI async web server with TaskIQ workers:

- Web: FastAPI HTTP API at `backend/api/v1/`
- Worker: TaskIQ async tasks at `backend/worker/`
- Database: PostgreSQL + pgvector through SQLAlchemy async
- Cache/Broker: Redis db 0 for app, db 1 for TaskIQ
- Observability: OpenTelemetry to Langfuse
- Storage: local filesystem or S3-compatible storage

Frontend is a React 19 admin app under `frontend/apps/admin`; see [frontend.md](frontend.md).

## Directory Map

```text
backend/
  api/v1/endpoint/    HTTP endpoints
  api/v1/api.py       Router registration
  api/dependencies.py FastAPI dependency injection
  api/deps/           Dependency providers
  ai/                 AI core utilities and external providers
  application/        Workflows grouped by process boundary (chat, knowledge, repo_analysis)
  contracts/          Abstract interfaces
  models/orm/         SQLAlchemy ORM models
  models/schemas/     Pydantic DTOs
  config/             Pydantic settings
  services/           Business logic
  repositories/       Data access
  infra/              DB, Redis, TaskIQ broker
  middleware/         FastAPI middleware
  observability/      OTel/Langfuse telemetry, logging, and trace utils
  worker/             TaskIQ tasks
  core/               Exceptions and constants
  utils/              Generic helpers
  main.py             FastAPI app entry
frontend/             pnpm workspace: admin app and frontend docs (see frontend.md)
tests/                unit, component, integration, smoke, manual tests
scripts/              Shell and Python automation
configs/              Deployment configs
alembic/              Migration chain
```
