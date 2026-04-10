SHELL := /bin/bash

DOCKER_IMAGE_NAME ?= ai-tutor-backend:v1
SMOKE_COMPOSE_FILE ?= docker-compose.db.yml
SMOKE_ENV_FILE ?= .env.smoke
SMOKE_ENV_TEMPLATE ?= .env.smoke.template
SMOKE_BASE_URL ?= http://localhost:8000
SMOKE_LIVE_PATH ?= /api/v1/health_check/live
SMOKE_READY_PATH ?= /api/v1/health_check/db_ready
UNIT_TARGETS ?= tests/unit
INTEGRATION_TARGETS ?= tests/integration
PYTEST_ARGS ?=

export DOCKER_IMAGE_NAME
export SMOKE_COMPOSE_FILE
export SMOKE_ENV_FILE
export SMOKE_ENV_TEMPLATE
export SMOKE_BASE_URL
export SMOKE_LIVE_PATH
export SMOKE_READY_PATH

.DEFAULT_GOAL := help

.PHONY: help \
	qa-lint qa-format qa-typecheck qa-test-unit qa-test-integration qa-test-all qa-checks \
	image-build \
	env-smoke-prepare env-smoke-up env-smoke-wait env-smoke-down env-smoke-logs \
	verify-smoke \
	flow-dev-check flow-ci \
	lint format typecheck test check clean-cache

help:
	@printf '%s\n' \
		'Available targets:' \
		'  qa-lint              Run Ruff lint checks' \
		'  qa-format            Run Ruff formatter' \
		'  qa-typecheck         Run type checking' \
		'  qa-test-unit         Run unit tests (UNIT_TARGETS=...)' \
		'  qa-test-integration  Run integration tests (INTEGRATION_TARGETS=...)' \
		'  qa-test-all          Run all pytest suites except excluded markers' \
		'  qa-checks            Run lint and typecheck via scripts' \
		'  image-build          Build the backend Docker image' \
		'  env-smoke-prepare    Generate the smoke env file from template' \
		'  env-smoke-up         Start the smoke environment' \
		'  env-smoke-wait       Wait until the smoke environment is reachable' \
		'  verify-smoke         Run smoke HTTP checks against the running stack' \
		'  env-smoke-down       Stop the smoke environment' \
		'  env-smoke-logs       Show recent smoke logs' \
		'  flow-dev-check       Run the full dev verification flow' \
		'  flow-ci              Alias for the dev verification flow'

qa-lint:
	uv run ruff check .

qa-format:
	uv run ruff format .

qa-typecheck:
	uv run ty check .

qa-test-unit:
	bash scripts/qa/run_unit.sh $(PYTEST_ARGS) $(UNIT_TARGETS)

qa-test-integration:
	bash scripts/qa/run_integration.sh $(PYTEST_ARGS) $(INTEGRATION_TARGETS)

qa-test-all:
	uv run pytest $(PYTEST_ARGS)

qa-checks:
	bash scripts/qa/run_checks.sh

image-build:
	bash scripts/image/build_backend.sh

env-smoke-prepare:
	bash scripts/smoke/prepare_env.sh

env-smoke-up:
	bash scripts/smoke/up.sh

env-smoke-wait:
	bash scripts/smoke/wait.sh

env-smoke-down:
	bash scripts/smoke/down.sh

env-smoke-logs:
	SMOKE_ENV_FILE="$(SMOKE_ENV_FILE)" docker compose --env-file "$(SMOKE_ENV_FILE)" -f "$(SMOKE_COMPOSE_FILE)" logs --tail=200

verify-smoke:
	bash scripts/smoke/test.sh

flow-dev-check:
	bash scripts/flow/dev_check.sh

flow-ci: flow-dev-check

lint: qa-lint

format: qa-format

typecheck: qa-typecheck

test: qa-test-all

check:
	$(MAKE) qa-lint
	$(MAKE) qa-typecheck
	$(MAKE) qa-test-all

clean-cache:
	uv run python -c "import pathlib; [p.unlink() for p in pathlib.Path('.').rglob('*.py[co]')]; [p.rmdir() for p in pathlib.Path('.').rglob('__pycache__')]"
