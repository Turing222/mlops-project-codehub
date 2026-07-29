SHELL := /bin/bash

# IMAGE_TAG = immutable build identity. `git describe` yields the semver tag when
# one exists (v2.1.0 / v2.1.0-3-gabcdef0), else a 12-char short SHA. Release
# targets require a clean worktree before using this tag.
IMAGE_TAG ?= $(shell git describe --tags --always --abbrev=12 2>/dev/null || echo dev)
BACKEND_IMAGE_REPOSITORY ?= dewflow-backend
FRONTEND_IMAGE_REPOSITORY ?= dewflow-frontend
RELEASE_DOCKER_IMAGE_NAME_WEB ?= $(BACKEND_IMAGE_REPOSITORY):$(IMAGE_TAG)-web
RELEASE_DOCKER_IMAGE_NAME_AI ?= $(BACKEND_IMAGE_REPOSITORY):$(IMAGE_TAG)-ai
RELEASE_DOCKER_IMAGE_NAME_FRONTEND ?= $(FRONTEND_IMAGE_REPOSITORY):$(IMAGE_TAG)
# Default image names track the immutable tag — no 2.0.0 pseudo-version anywhere.
DOCKER_IMAGE_NAME_WEB ?= $(RELEASE_DOCKER_IMAGE_NAME_WEB)
DOCKER_IMAGE_NAME_AI ?= $(RELEASE_DOCKER_IMAGE_NAME_AI)
DOCKER_IMAGE_NAME_FRONTEND ?= $(RELEASE_DOCKER_IMAGE_NAME_FRONTEND)
explicit_env_override = $(if $(filter command line,$(origin $(1))),1,$(if $(filter environment environment override,$(origin $(1)_EXPLICIT)),$($(1)_EXPLICIT),$(if $(filter environment environment override,$(origin $(1))),1,)))
DOCKER_IMAGE_NAME_WEB_EXPLICIT := $(call explicit_env_override,DOCKER_IMAGE_NAME_WEB)
DOCKER_IMAGE_NAME_AI_EXPLICIT := $(call explicit_env_override,DOCKER_IMAGE_NAME_AI)
DOCKER_IMAGE_NAME_FRONTEND_EXPLICIT := $(call explicit_env_override,DOCKER_IMAGE_NAME_FRONTEND)
# Semantic version for release tagging; single source of truth is base.yaml.
RELEASE_VERSION ?= $(shell awk -F': *' '/^VERSION:/{print $$2}' configs/app/base.yaml 2>/dev/null)
SMOKE_COMPOSE_FILE ?= docker-compose.db.yml
SMOKE_ENV_FILE ?= .env.smoke
SMOKE_ENV_TEMPLATE ?= .env.smoke.template
SMOKE_BASE_URL ?= http://localhost:8000
SMOKE_LIVE_PATH ?= /api/v1/health_check/live
SMOKE_READY_PATH ?= /api/v1/health_check/db_ready
DEPLOY_COMPOSE_FILE ?= deploy/docker-compose.yml
DEPLOY_ENV_FILE ?= deploy/.env.ec2
DEPLOY_BASE_URL ?= http://localhost
DEPLOY_FRONTEND_BASE_URL ?=
DEPLOY_FRONTEND_HEALTH_PATH ?= /healthz
DEPLOY_API_LIVE_PATH ?= /api/v1/health_check/live
DEPLOY_API_READY_PATH ?= /api/v1/health_check/db_ready
DEPLOY_ENABLE_BIFROST ?= false
DEPLOY_LOG_TAIL ?= 200
DEPLOY_SECRET_DIR ?= secrets/ec2
DEPLOY_RUNTIME_SECRET_ID ?= dewflow-prod-runtime
DEPLOY_AWS_REGION ?= us-west-2
DEPLOY_POSTGRES_PARAMETER ?= /dewflow/prod/postgres_password
DEPLOY_COMPOSE_FILE_EXPLICIT := $(call explicit_env_override,DEPLOY_COMPOSE_FILE)
DEPLOY_EXTRA_COMPOSE_FILES_EXPLICIT := $(call explicit_env_override,DEPLOY_EXTRA_COMPOSE_FILES)
DEPLOY_BASE_URL_EXPLICIT := $(call explicit_env_override,DEPLOY_BASE_URL)
DEPLOY_FRONTEND_BASE_URL_EXPLICIT := $(call explicit_env_override,DEPLOY_FRONTEND_BASE_URL)
DEPLOY_FRONTEND_HEALTH_PATH_EXPLICIT := $(call explicit_env_override,DEPLOY_FRONTEND_HEALTH_PATH)
DEPLOY_API_LIVE_PATH_EXPLICIT := $(call explicit_env_override,DEPLOY_API_LIVE_PATH)
DEPLOY_API_READY_PATH_EXPLICIT := $(call explicit_env_override,DEPLOY_API_READY_PATH)
DEPLOY_ENABLE_BIFROST_EXPLICIT := $(call explicit_env_override,DEPLOY_ENABLE_BIFROST)
DEPLOY_ENABLE_FRONTEND_FALLBACK_EXPLICIT := $(call explicit_env_override,DEPLOY_ENABLE_FRONTEND_FALLBACK)
DEPLOY_CHECK_FRONTEND_HEALTH_EXPLICIT := $(call explicit_env_override,DEPLOY_CHECK_FRONTEND_HEALTH)
DEPLOY_PULL_IMAGES_EXPLICIT := $(call explicit_env_override,DEPLOY_PULL_IMAGES)
DEPLOY_LOG_TAIL_EXPLICIT := $(call explicit_env_override,DEPLOY_LOG_TAIL)
DEPLOY_SECRET_DIR_EXPLICIT := $(call explicit_env_override,DEPLOY_SECRET_DIR)
DEPLOY_RUNTIME_SECRET_ID_EXPLICIT := $(call explicit_env_override,DEPLOY_RUNTIME_SECRET_ID)
DEPLOY_AWS_REGION_EXPLICIT := $(call explicit_env_override,DEPLOY_AWS_REGION)
DEPLOY_SMOKE_PYTEST_TARGETS_EXPLICIT := $(call explicit_env_override,DEPLOY_SMOKE_PYTEST_TARGETS)
LOCAL_PROD_DEPLOY_EXTRA_COMPOSE_FILES ?= deploy/docker-compose.local-postgres.yml deploy/docker-compose.local-s3.yml deploy/docker-compose.local-logging.yml
LOCAL_PROD_DEPLOY_ENV := \
	DEPLOY_ENV_FILE=deploy/.env.local-prod.template \
	DEPLOY_EXTRA_COMPOSE_FILES="$(LOCAL_PROD_DEPLOY_EXTRA_COMPOSE_FILES)" DEPLOY_EXTRA_COMPOSE_FILES_EXPLICIT=1 \
	FRONTEND_PUBLIC_PORT=8080 \
	DOCKER_IMAGE_NAME_WEB_EXPLICIT=1 DOCKER_IMAGE_NAME_AI_EXPLICIT=1 DOCKER_IMAGE_NAME_FRONTEND_EXPLICIT=1
FRONTEND_DIR ?= frontend
FRONTEND_APP ?= admin
E2E_SMOKE_USER ?= seed_admin
E2E_SMOKE_PASS ?= SeedPass123!
UNIT_TARGETS ?= tests/unit
COMPONENT_TARGETS ?= tests/component
INTEGRATION_TARGETS ?= tests/integration
EVAL_DATASET ?= evals/dataset.sample.jsonl
EVAL_OUTPUT ?= evals/reports/answer_report.json
EVAL_API_OUTPUT ?= evals/reports/api_answer_report.json
EVAL_RETRIEVAL_OUTPUT ?= evals/reports/retrieval_report.json
PERF_USERS ?= 5
PERF_SPAWN_RATE ?= 1
PERF_RUN_TIME ?= 1m
PERF_PROFILE ?= perf/profiles/enterprise_smoke.json
PERF_OUTPUT ?= perf/reports/chat_api_load_report.json
PYTEST_ARGS ?=

export DOCKER_IMAGE_NAME_WEB DOCKER_IMAGE_NAME_AI DOCKER_IMAGE_NAME_FRONTEND
export DOCKER_IMAGE_NAME_WEB_EXPLICIT DOCKER_IMAGE_NAME_AI_EXPLICIT DOCKER_IMAGE_NAME_FRONTEND_EXPLICIT
export IMAGE_TAG BACKEND_IMAGE_REPOSITORY FRONTEND_IMAGE_REPOSITORY
export RELEASE_DOCKER_IMAGE_NAME_WEB RELEASE_DOCKER_IMAGE_NAME_AI RELEASE_DOCKER_IMAGE_NAME_FRONTEND
export SMOKE_COMPOSE_FILE
export SMOKE_ENV_FILE
export SMOKE_ENV_TEMPLATE
export SMOKE_BASE_URL
export SMOKE_LIVE_PATH
export SMOKE_READY_PATH
export DEPLOY_COMPOSE_FILE DEPLOY_ENV_FILE DEPLOY_BASE_URL
export DEPLOY_EXTRA_COMPOSE_FILES
export DEPLOY_FRONTEND_BASE_URL DEPLOY_FRONTEND_HEALTH_PATH DEPLOY_API_LIVE_PATH DEPLOY_API_READY_PATH
export DEPLOY_ENABLE_BIFROST DEPLOY_LOG_TAIL
export DEPLOY_SECRET_DIR DEPLOY_RUNTIME_SECRET_ID DEPLOY_AWS_REGION
export DEPLOY_COMPOSE_FILE_EXPLICIT DEPLOY_EXTRA_COMPOSE_FILES_EXPLICIT DEPLOY_BASE_URL_EXPLICIT
export DEPLOY_FRONTEND_BASE_URL_EXPLICIT DEPLOY_FRONTEND_HEALTH_PATH_EXPLICIT DEPLOY_API_LIVE_PATH_EXPLICIT DEPLOY_API_READY_PATH_EXPLICIT
export DEPLOY_ENABLE_BIFROST_EXPLICIT DEPLOY_ENABLE_FRONTEND_FALLBACK_EXPLICIT DEPLOY_CHECK_FRONTEND_HEALTH_EXPLICIT
export DEPLOY_PULL_IMAGES_EXPLICIT DEPLOY_LOG_TAIL_EXPLICIT DEPLOY_SECRET_DIR_EXPLICIT
export DEPLOY_RUNTIME_SECRET_ID_EXPLICIT DEPLOY_AWS_REGION_EXPLICIT DEPLOY_SMOKE_PYTEST_TARGETS_EXPLICIT
export E2E_SMOKE_USER E2E_SMOKE_PASS
export EVAL_DATASET EVAL_OUTPUT EVAL_API_OUTPUT EVAL_RETRIEVAL_OUTPUT
export PERF_USERS PERF_SPAWN_RATE PERF_RUN_TIME PERF_PROFILE PERF_OUTPUT
QA_STANDARDS_FAST_TARGETS ?= .codex docs work-items backend tests

.DEFAULT_GOAL := help

.PHONY: help \
	qa-lint qa-lint-fix qa-boundaries qa-format qa-format-check qa-typecheck qa-layer-deps qa-alembic-check qa-config-check qa-no-while-true qa-no-sensitive-values qa-gitleaks-policy qa-public-content qa-test-markers qa-test-unit qa-test-component qa-test-integration qa-test-local qa-test-ci qa-test-external qa-test-all qa-checks qa-skill-check qa-serena-smoke qa-docs qa-standards-fast qa-claude-fast qa-eval-rag qa-eval-api qa-perf-chat qa-perf-chat-locust qa-agent-flow \
	frontend-lint frontend-typecheck frontend-test frontend-test-coverage frontend-build frontend-bundle-check frontend-build-pages-check frontend-e2e-mock frontend-e2e-smoke frontend-check \
	image-build frontend-image-build image-build-all release-check-clean image-build-release frontend-image-build-release image-build-all-release release-image-env release-tag \
	docker-prune-stale-infra \
		deploy-ec2-secrets-prepare deploy-secrets-status deploy-secrets-aws-status deploy-secrets-import deploy-secrets-materialize deploy-secrets-compare-postgres deploy-ec2-check deploy-ec2-up deploy-ec2-wait deploy-ec2-verify deploy-ec2-logs deploy-ec2-down deploy-cloudwatch-setup deploy-cloudwatch-verify-delivery deploy-bootstrap-prod \
	deploy-local-prod-secrets-prepare deploy-local-prod-check deploy-local-prod-up deploy-local-prod-wait deploy-local-prod-verify deploy-local-prod-logs deploy-local-prod-down \
	env-smoke-prepare env-smoke-check env-smoke-up env-smoke-up-debug env-smoke-wait env-smoke-down env-smoke-logs \
	set-llm seed-dev seed-prod-bootstrap \
	pr-report ci-bootstrap-github-gate \
	verify-smoke verify-pages \
	security-scan-deps security-scan-images security-scan-fast security-scan-full \
	flow-static flow-runtime flow-dev-check \
	flow-fast flow-pr-preflight flow-local flow-local-log flow-local-full flow-ci \
	lint format typecheck test check clean-cache

help:
	@printf '%s\n' \
		'Available targets:' \
		'  qa-lint              Run Ruff lint checks' \
		'  qa-lint-fix          Run Ruff lint fixes' \
		'  qa-boundaries        Check Web/Worker import boundaries' \
		'  qa-format            Run Ruff formatter' \
		'  qa-format-check      Check Ruff formatter without writing files' \
		'  qa-typecheck         Run type checking' \
			'  qa-layer-deps        Verify each extras layer can import independently' \
			'  qa-alembic-check     Validate migration chain integrity' \
			'  qa-config-check      Validate config/env for deployment contexts' \
			'  qa-no-while-true     Reject bare Python while True loops' \
			'  qa-no-sensitive-values  Reject real deployment identifiers in tracked files' \
			'  qa-gitleaks-policy   Reject broad Gitleaks exemptions' \
			'  qa-public-content    Run fast public-content safety checks' \
			'  qa-test-markers      Audit pytest dependency markers' \
			'  qa-test-unit         Run unit tests (UNIT_TARGETS=...)' \
			'  qa-test-component    Run component tests (COMPONENT_TARGETS=...)' \
			'  qa-test-integration  Run integration tests (INTEGRATION_TARGETS=...)' \
			'  qa-test-local        Run local default pytest profile' \
		'  qa-test-ci           Run CI-safe pytest profile' \
		'  qa-test-external     Run tests that need external dependencies' \
		'  qa-test-all          Run all pytest suites except excluded markers' \
		'  qa-eval-rag          Run opt-in RAG retrieval and answer evals' \
		'  qa-eval-api          Run opt-in RAG answer eval through HTTP API' \
		'  qa-perf-chat         Run opt-in chat load profile with HTTP runner' \
		'  qa-perf-chat-locust  Run exploratory chat load test with Locust' \
		'  qa-agent-flow        Reserved entrypoint for agent/C2C flow tests' \
		'  qa-checks            Run lint and typecheck via scripts' \
		'  qa-skill-check       Validate local Codex skill contracts' \
		'  qa-serena-smoke      Check Serena symbols for fixed Python/TypeScript files' \
		'  qa-docs              Validate documentation naming, links, index, and layout' \
		'  qa-standards-fast    Run fast standards checks for files or default project paths' \
		'  qa-claude-fast       Alias for qa-standards-fast (kept for Claude hook wiring)' \
		'  frontend-lint        Run frontend ESLint checks' \
		'  frontend-typecheck   Run frontend TypeScript checks' \
		'  frontend-test        Run the frontend unit/smoke tests' \
		'  frontend-test-coverage  Run frontend unit tests with v8 coverage report' \
		'  frontend-build       Build the frontend app bundle' \
		'  frontend-bundle-check  Check gzip bundle size against bundle-baseline.json' \
		'  frontend-build-pages-check  Build in Pages prod form and verify dist/_headers CSP' \
		'  frontend-e2e-mock    Run frontend Playwright tests with mocked API routes' \
		'  frontend-e2e-smoke   Run frontend Playwright smoke tests against a real backend' \
		'  frontend-check        Run frontend lint, typecheck, tests, build, and bundle check' \
		'  frontend-check-full  frontend-check + mock e2e' \
		'  image-build          Build the backend Docker image' \
		'  frontend-image-build  Build the frontend Docker image' \
		'  image-build-all       Build all Docker images (backend + frontend)' \
		'  image-build-release  Build backend images tagged with IMAGE_TAG' \
		'  frontend-image-build-release  Build frontend fallback image tagged with IMAGE_TAG' \
		'  image-build-all-release       Build all release-tagged images' \
		'  docker-prune-stale-infra Remove superseded infra and ephemeral local images' \
		'  release-image-env    Print DOCKER_IMAGE_NAME_* values for deploy/.env.ec2' \
		'  release-tag          Tag current commit v<VERSION> from configs/app/base.yaml' \
		'  deploy-ec2-secrets-prepare  Create EC2 deploy secret files under secrets/ec2' \
		'  deploy-secrets-status       Show file presence without printing values' \
		'  deploy-secrets-aws-status   Show AWS bundle key presence without values' \
		'  deploy-secrets-import       Dry-run runtime bundle import; pass ARGS=--apply explicitly' \
		'  deploy-secrets-materialize  Fetch the configured AWS bundle into DEPLOY_SECRET_DIR' \
		'  deploy-secrets-compare-postgres  Compare file and SSM DB passwords without values' \
		'  deploy-ec2-check     Validate EC2 deploy env and compose config' \
		'  deploy-ec2-up        Pull pinned infra images and start the EC2 deploy stack' \
		'  deploy-ec2-wait      Wait until the EC2 deploy endpoints are reachable' \
			'  deploy-ec2-verify    Run remote-safe smoke checks against the EC2 deploy stack' \
			'  deploy-ec2-logs      Show recent EC2 deploy logs' \
			'  deploy-ec2-down      Stop the EC2 deploy stack' \
			'  deploy-cloudwatch-setup  Create/update CloudWatch log alarms and SNS topic' \
			'  deploy-cloudwatch-verify-delivery  Emit and observe the controlled T1-Lite Alarm signal' \
		'  deploy-bootstrap-prod  Orchestrate first prod bootstrap (ARGS=ec2-stack|github-gate|verify-pages)' \
			'  deploy-local-prod-up Start local production-shape rehearsal stack with MinIO S3' \
		'  deploy-local-prod-down Stop local production-shape rehearsal stack' \
		'  env-smoke-prepare    Generate the smoke env file from template' \
		'  env-smoke-check      Run preflight checks for smoke environment (API keys)' \
		'  env-smoke-up         Start the smoke environment' \
		'  env-smoke-up-debug   Start the smoke environment with debug logs' \
		'  env-smoke-wait       Wait until the smoke environment is reachable' \
		'  set-llm              Advanced: configure smoke LLM secrets/env' \
		'  seed-dev             Seed fixed local data for admin/permission testing' \
		'  seed-prod-bootstrap  Bootstrap one manual-test user for deployed environments' \
		'  pr-report            Generate a local PR readiness Markdown report' \
		'  ci-bootstrap-github-gate  Bootstrap GitHub secrets/vars and optional branch protection (needs gh)' \
		'  verify-smoke         Run smoke HTTP checks against the running stack' \
		'  verify-pages         Run Cloudflare Pages release checks against public origins' \
		'  security-scan-deps   Audit Python + frontend lockfiles (mirrors security-ci deps)' \
		'  security-scan-images Build release images and run Trivy HIGH/CRITICAL scan' \
		'  security-scan-fast   Alias for security-scan-deps (~1 min)' \
		'  security-scan-full   security-scan-deps + security-scan-images' \
		'  env-smoke-down       Stop the smoke environment' \
		'  env-smoke-logs       Show recent smoke logs' \
		'  flow-static          Run L1 static checks and deterministic tests' \
		'  flow-runtime         Run runtime checks (build+smoke up+smoke tests+smoke down)' \
		'  flow-dev-check       Run the full dev verification flow (static + runtime)' \
		'  flow-pr-preflight    Pre-PR check mirroring static-ci + pr-gate (no Docker smoke)' \
		'  flow-fast            Quick feedback: backend static + unit + component; frontend check' \
		'  flow-local           Full local verify with per-step logs under logs/flow-local/' \
		'  flow-local-log       Alias for flow-local (same script, log artifacts enabled)' \
		'  flow-local-full      flow-local + security-scan-full + performance/LLM suites' \
		'  flow-ci              PR gate baseline: flow-fast + integration (CI env) + e2e-mock'

qa-lint:
	uv run ruff check .

qa-lint-fix:
	uv run ruff check . --fix

qa-boundaries:
	uv run python scripts/check_import_boundaries.py

qa-format:
	uv run ruff format .

qa-format-check:
	uv run ruff format --check .

qa-typecheck:
	uv run ty check .

qa-layer-deps:
	bash scripts/qa/layer_deps_check.sh

qa-alembic-check:
	bash scripts/qa/alembic_check.sh

qa-config-check:
	uv run python scripts/qa/config_check.py $(ARGS)

qa-no-while-true:
	uv run python scripts/qa/check_no_while_true.py

qa-no-sensitive-values:
	uv run --no-project python scripts/qa/check_no_sensitive_values.py

qa-gitleaks-policy:
	uv run --no-project python scripts/qa/check_gitleaks_policy.py

qa-public-content:
	$(MAKE) qa-no-sensitive-values
	$(MAKE) qa-gitleaks-policy

qa-test-markers:
	uv run python scripts/qa/check_test_markers.py

qa-test-unit:
	DEWFLOW_TEST_PROFILE=unit bash scripts/qa/run_unit.sh $(PYTEST_ARGS) $(UNIT_TARGETS)

qa-test-component:
	DEWFLOW_TEST_PROFILE=unit uv run pytest $(PYTEST_ARGS) $(COMPONENT_TARGETS)

qa-test-integration:
	DEWFLOW_TEST_PROFILE=local bash scripts/qa/run_integration.sh $(PYTEST_ARGS) $(INTEGRATION_TARGETS)

qa-test-local:
	DEWFLOW_TEST_PROFILE=local uv run pytest -m "not performance" $(PYTEST_ARGS)

qa-test-ci:
	DEWFLOW_TEST_PROFILE=ci uv run pytest -m "not performance and not local_only and not requires_llm and not requires_s3" $(PYTEST_ARGS)

qa-test-external:
	DEWFLOW_TEST_PROFILE=external uv run pytest -m "requires_llm or requires_s3 or requires_taskiq" $(PYTEST_ARGS)

qa-test-all:
	uv run pytest $(PYTEST_ARGS)

qa-eval-rag:
	uv run python -m evals.eval_retrieval --dataset "$(EVAL_DATASET)" --output "$(EVAL_RETRIEVAL_OUTPUT)" $(ARGS)
	uv run python -m evals.eval_answer --dataset "$(EVAL_DATASET)" --output "$(EVAL_OUTPUT)" $(ARGS)

qa-eval-api:
	uv run python -m evals.eval_api_answer --dataset "$(EVAL_DATASET)" --output "$(EVAL_API_OUTPUT)" --base-url "$(SMOKE_BASE_URL)" $(ARGS)

qa-perf-chat:
	uv run python -m perf.chat_api_load --profile "$(PERF_PROFILE)" --output "$(PERF_OUTPUT)" --base-url "$(SMOKE_BASE_URL)" $(ARGS)

qa-perf-chat-locust:
	uv run locust -f tests/performance/locustfile.py --host "$(SMOKE_BASE_URL)" --headless -u "$(PERF_USERS)" -r "$(PERF_SPAWN_RATE)" -t "$(PERF_RUN_TIME)" $(ARGS)

qa-agent-flow:
	@printf '%s\n' 'Agent/C2C flow tests are reserved for L3 and should reuse tests/smoke helpers.'

qa-checks:
	bash scripts/qa/run_checks.sh

qa-skill-check:
	uv run python scripts/qa/check_skills.py

qa-serena-smoke:
	uv run python scripts/qa/check_serena_mcp.py

qa-docs:
	uv run python scripts/qa/check_docs.py

qa-standards-fast: qa-skill-check qa-docs
	uv run python scripts/qa/check_claude_fast.py $(if $(strip $(FILES)),$(FILES),$(QA_STANDARDS_FAST_TARGETS))

qa-claude-fast: qa-standards-fast

frontend-lint:
	pnpm --dir "$(FRONTEND_DIR)" --filter "$(FRONTEND_APP)" lint

frontend-typecheck:
	pnpm --dir "$(FRONTEND_DIR)" --filter "$(FRONTEND_APP)" typecheck

frontend-test:
	pnpm --dir "$(FRONTEND_DIR)" --filter "$(FRONTEND_APP)" test

frontend-test-coverage:
	pnpm --dir "$(FRONTEND_DIR)" --filter "$(FRONTEND_APP)" test:coverage

frontend-build:
	pnpm --dir "$(FRONTEND_DIR)" --filter "$(FRONTEND_APP)" build

frontend-bundle-check:
	pnpm --dir "$(FRONTEND_DIR)" --filter "$(FRONTEND_APP)" bundle:check

# Exercises the Cloudflare Pages production build form (CF_PAGES=1 + VITE_API_BASE_URL),
# which plain frontend-build never does, then asserts dist/_headers carries a real
# CSP report-only with a concrete report-uri and no placeholder tokens.
frontend-build-pages-check:
	VITE_API_BASE_URL=https://api.example.com CF_PAGES=1 \
		pnpm --dir "$(FRONTEND_DIR)" --filter "$(FRONTEND_APP)" build
	@headers="$(FRONTEND_DIR)/apps/$(FRONTEND_APP)/dist/_headers"; \
		grep -q 'Content-Security-Policy-Report-Only:' "$$headers" || { echo "FAIL: dist/_headers missing CSP report-only"; exit 1; }; \
		grep -q 'report-uri https://api.example.com/api/v1/csp/reports' "$$headers" || { echo "FAIL: dist/_headers missing concrete report-uri"; exit 1; }; \
		! grep -q '<domain>' "$$headers" || { echo "FAIL: dist/_headers contains placeholder token"; exit 1; }; \
		echo "OK: production-form dist/_headers verified"

frontend-e2e-mock:
	pnpm --dir "$(FRONTEND_DIR)" --filter "$(FRONTEND_APP)" test:e2e:mock

frontend-e2e-smoke:
	pnpm --dir "$(FRONTEND_DIR)" --filter "$(FRONTEND_APP)" test:e2e:smoke

frontend-check:
	$(MAKE) frontend-lint
	$(MAKE) frontend-typecheck
	$(MAKE) frontend-test
	$(MAKE) frontend-build
	$(MAKE) frontend-bundle-check

frontend-check-full: frontend-check
	$(MAKE) frontend-e2e-mock

image-build:
	bash scripts/image/build_backend.sh

frontend-image-build:
	docker build -f frontend/apps/admin/Dockerfile -t "$(DOCKER_IMAGE_NAME_FRONTEND)" .

image-build-all: image-build frontend-image-build

release-check-clean:
	@test -z "$$(git status --porcelain)" || { echo "working tree dirty; commit or remove all tracked and untracked changes before releasing"; exit 1; }

image-build-release: release-check-clean
	DOCKER_IMAGE_NAME_WEB="$(RELEASE_DOCKER_IMAGE_NAME_WEB)" DOCKER_IMAGE_NAME_AI="$(RELEASE_DOCKER_IMAGE_NAME_AI)" $(MAKE) image-build

frontend-image-build-release: release-check-clean
	DOCKER_IMAGE_NAME_FRONTEND="$(RELEASE_DOCKER_IMAGE_NAME_FRONTEND)" $(MAKE) frontend-image-build

image-build-all-release: image-build-release frontend-image-build-release

docker-prune-stale-infra:
	bash scripts/image/prune_stale_infra.sh

release-image-env: release-check-clean
	@printf '%s\n' \
		'DOCKER_IMAGE_NAME_WEB=$(RELEASE_DOCKER_IMAGE_NAME_WEB)' \
		'DOCKER_IMAGE_NAME_AI=$(RELEASE_DOCKER_IMAGE_NAME_AI)' \
		'DOCKER_IMAGE_NAME_FRONTEND=$(RELEASE_DOCKER_IMAGE_NAME_FRONTEND)'

release-tag: release-check-clean
	@test -n "$(RELEASE_VERSION)" || { echo "VERSION not found in configs/app/base.yaml"; exit 1; }
	@pyproject_version="$$(awk -F'"' '/^version =/{print $$2; exit}' pyproject.toml)"; \
		test "$$pyproject_version" = "$(RELEASE_VERSION)" || { echo "version drift: pyproject.toml=$$pyproject_version != base.yaml VERSION=$(RELEASE_VERSION); sync them before tagging"; exit 1; }
	git tag -a "v$(RELEASE_VERSION)" -m "release v$(RELEASE_VERSION)"
	@printf 'tagged v%s; push with: git push origin v%s\n' "$(RELEASE_VERSION)" "$(RELEASE_VERSION)"

deploy-ec2-secrets-prepare:
	bash scripts/deploy/ec2-secrets-prepare.sh

deploy-secrets-status:
	uv run --frozen python scripts/deploy/secret_bundle.py status \
		--directory "$(DEPLOY_SECRET_DIR)"

deploy-secrets-aws-status:
	uv run --frozen python scripts/deploy/secret_bundle.py status-aws \
		--secret-id "$(DEPLOY_RUNTIME_SECRET_ID)" \
		--region "$(DEPLOY_AWS_REGION)"

deploy-secrets-import:
	uv run --frozen python scripts/deploy/secret_bundle.py import-directory \
		--directory "$(DEPLOY_SECRET_DIR)" \
		--secret-id "$(DEPLOY_RUNTIME_SECRET_ID)" \
		--region "$(DEPLOY_AWS_REGION)" $(ARGS)

deploy-secrets-materialize:
	bash scripts/deploy/secrets-materialize.sh

deploy-secrets-compare-postgres:
	uv run --frozen python scripts/deploy/secret_bundle.py compare-ssm \
		--secret-file "$(DEPLOY_SECRET_DIR)/postgres_password.txt" \
		--parameter-name "$(DEPLOY_POSTGRES_PARAMETER)" \
		--region "$(DEPLOY_AWS_REGION)"

deploy-ec2-check:
	bash scripts/deploy/ec2-check.sh

deploy-ec2-up:
	bash scripts/deploy/ec2-up.sh

deploy-ec2-wait:
	bash scripts/deploy/ec2-wait.sh

deploy-ec2-verify:
	bash scripts/deploy/ec2-verify.sh

deploy-ec2-logs:
	bash scripts/deploy/ec2-logs.sh $(ARGS)

deploy-ec2-down:
	bash scripts/deploy/ec2-down.sh

deploy-cloudwatch-setup:
	bash deploy/monitoring/cloudwatch-setup.sh

deploy-cloudwatch-verify-delivery:
	bash deploy/monitoring/cloudwatch-verify-delivery.sh

deploy-bootstrap-prod:
	bash scripts/deploy/bootstrap-prod.sh $(ARGS)

deploy-local-prod-secrets-prepare:
	$(LOCAL_PROD_DEPLOY_ENV) bash scripts/deploy/local-prod-secrets-prepare.sh

deploy-local-prod-check:
	$(LOCAL_PROD_DEPLOY_ENV) bash scripts/deploy/ec2-check.sh

deploy-local-prod-up:
	$(LOCAL_PROD_DEPLOY_ENV) bash scripts/deploy/ec2-up.sh

deploy-local-prod-wait:
	$(LOCAL_PROD_DEPLOY_ENV) bash scripts/deploy/ec2-wait.sh

deploy-local-prod-verify:
	$(LOCAL_PROD_DEPLOY_ENV) bash scripts/deploy/ec2-verify.sh

deploy-local-prod-logs:
	$(LOCAL_PROD_DEPLOY_ENV) bash scripts/deploy/ec2-logs.sh $(ARGS)

deploy-local-prod-down:
	$(LOCAL_PROD_DEPLOY_ENV) bash scripts/deploy/ec2-down.sh

env-smoke-prepare:
	bash scripts/smoke/prepare_env.sh

env-smoke-check:
	bash scripts/smoke/check_env.sh

env-smoke-up: env-smoke-check
	bash scripts/smoke/up.sh

env-smoke-up-debug:
	BACKEND_LOG_LEVEL=debug BIFROST_LOG_LEVEL=debug $(MAKE) env-smoke-up

env-smoke-wait:
	bash scripts/smoke/wait.sh

set-llm:
	@MODEL_ROUTING="$(or $(MODEL_ROUTING),)" \
		ROUTING_LLM_PROVIDER="$(or $(ROUTING_LLM_PROVIDER),)" \
		FAST_PROVIDER="$(or $(FAST_PROVIDER),)" \
		BALANCED_PROVIDER="$(or $(BALANCED_PROVIDER),)" \
		REASONING_PROVIDER="$(or $(REASONING_PROVIDER),)" \
		MIN_CONFIDENCE="$(or $(MIN_CONFIDENCE),)" \
		bash scripts/smoke/set_llm.sh "$(PROVIDER)" "$(or $(EMBED_PROVIDER),)"

seed-dev:
	uv run python scripts/seed/dev_seed.py $(ARGS)

seed-prod-bootstrap:
	uv run python scripts/seed/prod_bootstrap_user.py $(ARGS)

pr-report:
	uv run python scripts/qa/pr_report.py $(ARGS)

ci-bootstrap-github-gate:
	bash scripts/ci/bootstrap_github_gate.sh $(ARGS)

env-smoke-down:
	bash scripts/smoke/down.sh

env-smoke-logs:
	bash scripts/smoke/logs.sh

verify-smoke:
	bash scripts/smoke/test.sh

verify-pages:
	bash scripts/deploy/pages-verify.sh

security-scan-deps:
	bash scripts/security/scan_deps.sh

security-scan-images:
	bash scripts/security/scan_images.sh

security-scan-fast: security-scan-deps

security-scan-full:
	bash scripts/security/scan.sh full

flow-static:
	$(MAKE) qa-lint
	$(MAKE) qa-format-check
	$(MAKE) qa-boundaries
	$(MAKE) qa-no-while-true
	$(MAKE) qa-public-content
	$(MAKE) qa-test-markers
	$(MAKE) qa-typecheck
	$(MAKE) qa-layer-deps
	$(MAKE) qa-alembic-check
	$(MAKE) qa-config-check
	$(MAKE) qa-standards-fast
	$(MAKE) qa-test-unit
	$(MAKE) qa-test-component

flow-runtime:
	bash scripts/flow/runtime_check.sh

flow-dev-check:
	$(MAKE) flow-static
	$(MAKE) flow-runtime

# Automated test flows
# flow-fast:  no external services needed, ~2min
flow-fast:
	$(MAKE) qa-lint
	$(MAKE) qa-format-check
	$(MAKE) qa-no-while-true
	$(MAKE) qa-public-content
	$(MAKE) qa-typecheck
	$(MAKE) qa-standards-fast
	$(MAKE) qa-test-unit
	$(MAKE) qa-test-component
	$(MAKE) frontend-check

# flow-pr-preflight: mirrors static-ci.yml + pr-gate-ci.yml without Docker smoke (~10 min).
# Requires local Postgres (:5432) and Redis (:6379) for qa-test-ci.
flow-pr-preflight:
	$(MAKE) flow-static
	$(MAKE) frontend-check
	$(MAKE) frontend-build-pages-check
	$(MAKE) qa-test-ci
	$(MAKE) frontend-e2e-mock

# flow-local: requires Docker smoke stack; logs each step under logs/flow-local/
flow-local:
	bash scripts/flow/local_check.sh

flow-local-log: flow-local

# flow-local-full: full local verify plus security scans and optional performance/LLM suites
flow-local-full: flow-local
	$(MAKE) security-scan-full
	bash scripts/qa/run_with_smoke_env.sh uv run pytest -m "requires_llm" $(PYTEST_ARGS); status=$$?; if [ $$status -eq 5 ]; then echo "No requires_llm tests are currently collected; skipping optional LLM suite."; elif [ $$status -ne 0 ]; then exit $$status; fi
	bash scripts/qa/run_with_smoke_env.sh uv run pytest -m "performance" $(PYTEST_ARGS)

# flow-ci: PR gate baseline; Docker smoke/full-stack coverage lives in smoke-ci.
flow-ci: flow-fast
	DEWFLOW_TEST_PROFILE=ci uv run pytest -m "not performance and not local_only and not requires_llm and not requires_s3" $(PYTEST_ARGS)
	$(MAKE) frontend-e2e-mock

lint: qa-lint

format: qa-format

typecheck: qa-typecheck

test: qa-test-all

layer-deps: qa-layer-deps

check: flow-static

clean-cache:
	uv run python -c "import pathlib; [p.unlink() for p in pathlib.Path('.').rglob('*.py[co]')]; [p.rmdir() for p in pathlib.Path('.').rglob('__pycache__')]"

ARGS = $(filter-out $@,$(MAKECMDGOALS))

check-context:
	@echo "上线文变量查询: $(ARGS) : $($(ARGS))"
%:
	@if [ "$@" = "$(firstword $(MAKECMDGOALS))" ]; then \
		printf 'warning: unknown make target: %s\n' "$@" >&2; \
	else \
		printf 'warning: treating extra make goal as positional ARGS value: %s\n' "$@" >&2; \
	fi
