#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SMOKE_COMPOSE_FILE="${SMOKE_COMPOSE_FILE:-docker-compose.db.yml}"
SMOKE_ENV_FILE="${SMOKE_ENV_FILE:-.env.smoke}"
SMOKE_ENV_TEMPLATE="${SMOKE_ENV_TEMPLATE:-.env.smoke.template}"
SMOKE_BASE_URL="${SMOKE_BASE_URL:-http://localhost:8000}"
SMOKE_LIVE_PATH="${SMOKE_LIVE_PATH:-/api/v1/health_check/live}"
SMOKE_READY_PATH="${SMOKE_READY_PATH:-/api/v1/health_check/db_ready}"
SMOKE_PYTEST_TARGETS="${SMOKE_PYTEST_TARGETS:-\
tests/smoke/test_core_api_flow_smoke.py \
tests/smoke/test_chat_http_smoke.py \
tests/smoke/test_knowledge_http_smoke.py \
tests/smoke/test_rag_http_smoke.py}"
SMOKE_PYTEST_ARGS="${SMOKE_PYTEST_ARGS:-}"
SMOKE_TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS:-120}"
SMOKE_POLL_INTERVAL_SECONDS="${SMOKE_POLL_INTERVAL_SECONDS:-2}"
SMOKE_REQUIRED_VOLUME_NAMES=(
    prod_db_volume_test
    knowledge_files_volume_test
)
DEPLOY_COMPOSE_FILE_EXPLICIT="${DEPLOY_COMPOSE_FILE+x}"
DEPLOY_EXTRA_COMPOSE_FILES_EXPLICIT="${DEPLOY_EXTRA_COMPOSE_FILES+x}"
DEPLOY_BASE_URL_EXPLICIT="${DEPLOY_BASE_URL+x}"
DEPLOY_FRONTEND_BASE_URL_EXPLICIT="${DEPLOY_FRONTEND_BASE_URL+x}"
DEPLOY_FRONTEND_HEALTH_PATH_EXPLICIT="${DEPLOY_FRONTEND_HEALTH_PATH+x}"
DEPLOY_API_LIVE_PATH_EXPLICIT="${DEPLOY_API_LIVE_PATH+x}"
DEPLOY_API_READY_PATH_EXPLICIT="${DEPLOY_API_READY_PATH+x}"
DEPLOY_ENABLE_BIFROST_EXPLICIT="${DEPLOY_ENABLE_BIFROST+x}"
DEPLOY_ENABLE_OBSERVABILITY_EXPLICIT="${DEPLOY_ENABLE_OBSERVABILITY+x}"
DEPLOY_ENABLE_FRONTEND_FALLBACK_EXPLICIT="${DEPLOY_ENABLE_FRONTEND_FALLBACK+x}"
DEPLOY_CHECK_FRONTEND_HEALTH_EXPLICIT="${DEPLOY_CHECK_FRONTEND_HEALTH+x}"
DEPLOY_PULL_IMAGES_EXPLICIT="${DEPLOY_PULL_IMAGES+x}"
DEPLOY_LOG_TAIL_EXPLICIT="${DEPLOY_LOG_TAIL+x}"
DEPLOY_SECRET_DIR_EXPLICIT="${DEPLOY_SECRET_DIR+x}"
DEPLOY_SMOKE_PYTEST_TARGETS_EXPLICIT="${DEPLOY_SMOKE_PYTEST_TARGETS+x}"
DOCKER_IMAGE_NAME_WEB_EXPLICIT="${DOCKER_IMAGE_NAME_WEB_EXPLICIT-${DOCKER_IMAGE_NAME_WEB+x}}"
DOCKER_IMAGE_NAME_AI_EXPLICIT="${DOCKER_IMAGE_NAME_AI_EXPLICIT-${DOCKER_IMAGE_NAME_AI+x}}"
DOCKER_IMAGE_NAME_FRONTEND_EXPLICIT="${DOCKER_IMAGE_NAME_FRONTEND_EXPLICIT-${DOCKER_IMAGE_NAME_FRONTEND+x}}"
DEPLOY_COMPOSE_FILE="${DEPLOY_COMPOSE_FILE:-deploy/docker-compose.yml}"
DEPLOY_EXTRA_COMPOSE_FILES="${DEPLOY_EXTRA_COMPOSE_FILES:-}"
DEPLOY_ENV_FILE="${DEPLOY_ENV_FILE:-deploy/.env.ec2}"
DEPLOY_BASE_URL="${DEPLOY_BASE_URL:-http://localhost}"
DEPLOY_FRONTEND_BASE_URL="${DEPLOY_FRONTEND_BASE_URL:-}"
DEPLOY_FRONTEND_HEALTH_PATH="${DEPLOY_FRONTEND_HEALTH_PATH:-/healthz}"
DEPLOY_API_LIVE_PATH="${DEPLOY_API_LIVE_PATH:-/api/v1/health_check/live}"
DEPLOY_API_READY_PATH="${DEPLOY_API_READY_PATH:-/api/v1/health_check/db_ready}"
DEPLOY_SMOKE_PYTEST_TARGETS="${DEPLOY_SMOKE_PYTEST_TARGETS:-\
 tests/smoke/test_core_api_flow_smoke.py \
 tests/smoke/test_chat_http_smoke.py \
 tests/smoke/test_rag_http_smoke.py}"
DEPLOY_LOG_TAIL="${DEPLOY_LOG_TAIL:-200}"
DEPLOY_SECRET_DIR="${DEPLOY_SECRET_DIR:-secrets/ec2}"
DEPLOY_SECRET_FILE_ENV_NAMES=(
    DEPLOY_SECRET_KEY_FILE
    DEPLOY_POSTGRES_PASSWORD_FILE
    DEPLOY_REDIS_PASSWORD_FILE
    DEPLOY_OPENAI_API_KEY_FILE
    DEPLOY_DASHSCOPE_API_KEY_FILE
    DEPLOY_DASHSCOPE_API_KEY_2_FILE
    DEPLOY_GEMINI_API_KEY_FILE
    DEPLOY_GOOGLE_API_KEY_FILE
    DEPLOY_GOOGLE_CLIENT_SECRET_FILE
    DEPLOY_GITHUB_TOKEN_FILE
    DEPLOY_GROWTHBOOK_SDK_KEY_FILE
    DEPLOY_DEEPSEEK_API_KEY_FILE
    DEPLOY_DEEPSEEK_API_KEY_2_FILE
    DEPLOY_COHERE_API_KEY_FILE
    DEPLOY_COHERE_API_KEY_2_FILE
    DEPLOY_BIFROST_API_KEY_FILE
    DEPLOY_BIFROST_ENCRYPTION_KEY_FILE
    DEPLOY_LLM_API_KEY_FILE
    DEPLOY_RAG_EMBED_API_KEY_FILE
    DEPLOY_LANGFUSE_PUBLIC_KEY_FILE
    DEPLOY_LANGFUSE_SECRET_KEY_FILE
    DEPLOY_S3_ACCESS_KEY_ID_FILE
    DEPLOY_S3_SECRET_ACCESS_KEY_FILE
    DEPLOY_TAVILY_API_KEY_FILE
)
DEPLOY_REQUIRED_SECRET_FILE_ENV_NAMES=(
    DEPLOY_SECRET_KEY_FILE
    DEPLOY_POSTGRES_PASSWORD_FILE
    DEPLOY_REDIS_PASSWORD_FILE
)

log_section() {
    printf '\n==> %s\n' "$1"
}

log_info() {
    printf '[INFO] %s\n' "$1"
}

log_warn() {
    printf '[WARN] %s\n' "$1"
}

log_error() {
    printf '[ERROR] %s\n' "$1" >&2
}

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        log_error "Missing required command: $1"
        exit 1
    fi
}

resolve_project_path() {
    local path="$1"
    if [[ "$path" = /* ]]; then
        printf '%s\n' "$path"
        return
    fi
    printf '%s/%s\n' "$PROJECT_ROOT" "$path"
}

smoke_env_value() {
    local name="$1"
    local default_value="$2"
    local smoke_env_path
    local value

    if [[ -n "${!name:-}" ]]; then
        printf '%s\n' "${!name}"
        return
    fi

    smoke_env_path="$(resolve_project_path "$SMOKE_ENV_FILE")"
    if [[ -f "$smoke_env_path" ]]; then
        value="$(
            awk -F= -v key="$name" '
                $0 !~ /^[[:space:]]*#/ && $1 == key {
                    sub(/^[^=]*=/, "")
                    print
                    exit
                }
            ' "$smoke_env_path"
        )"
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"
        if [[ -n "$value" ]]; then
            printf '%s\n' "$value"
            return
        fi
    fi

    printf '%s\n' "$default_value"
}

llm_secret_provider() {
    local provider="$1"
    case "$provider" in
        bifrost|bifrost_pro|bifrost_flash|bifrost_reasoner|bifrost_v4_pro|bifrost_v4_flash)
            echo "bifrost"
            ;;
        deepseek|deepseek_pro|deepseek_v4_pro|deepseek_v4_flash|deepseek-v4-pro|deepseek-v4-flash)
            echo "deepseek"
            ;;
        *)
            echo "${provider%%/*}"
            ;;
    esac
}

llm_needs_bifrost_profile() {
    [[ "$(llm_secret_provider "$1")" == "bifrost" ]]
}

provider_needs_bifrost_profile() {
    local value="${1,,}"
    [[ "$value" == bifrost* || "$value" == gateway-* || "$value" == llm-gateway || "$value" == ai-gateway ]]
}

storage_needs_s3_profile() {
    [[ "${1,,}" == "s3" ]]
}

append_profile_arg() {
    local profile="$1"
    local existing
    for existing in "${profile_args[@]}"; do
        if [[ "$existing" == "$profile" ]]; then
            return
        fi
    done
    profile_args+=(--profile "$profile")
}

generate_smoke_secret() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 48
        return
    fi

    od -An -N48 -tx1 /dev/urandom | tr -d ' \n'
    printf '\n'
}

ensure_smoke_secret_file() {
    local env_name="$1"
    local default_path="$2"
    local mode="${3:-random}"
    local secret_path
    local secret_dir

    secret_path="$(smoke_env_value "$env_name" "$default_path")"
    secret_path="$(resolve_project_path "$secret_path")"
    secret_dir="$(dirname "$secret_path")"

    mkdir -p "$secret_dir"
    
    if [[ -s "$secret_path" ]]; then
        chmod 600 "$secret_path"
        return
    fi
    if [[ -f "$secret_path" && "$mode" == "empty" ]]; then
        chmod 600 "$secret_path"
        return
    fi

    (
        umask 077
        if [[ "$mode" == "empty" ]]; then
            touch "$secret_path"
            log_info "Created empty secret file: $secret_path"
        else
            generate_smoke_secret >"$secret_path"
            log_info "Generated smoke secret: $secret_path"
        fi
        chmod 600 "$secret_path"
    )
}

ensure_smoke_required_secrets() {
    ensure_smoke_secret_file "SMOKE_SECRET_KEY_FILE" "./secrets/smoke/secret_key.txt" "random"
    ensure_smoke_secret_file "SMOKE_POSTGRES_PASSWORD_FILE" "./secrets/smoke/postgres_password.txt" "random"
    ensure_smoke_secret_file "SMOKE_REDIS_PASSWORD_FILE" "./secrets/smoke/redis_password.txt" "random"

    # Auto-touch empty API key files
    ensure_smoke_secret_file "SMOKE_OPENAI_API_KEY_FILE" "./secrets/smoke/openai_api_key.txt" "empty"
    ensure_smoke_secret_file "SMOKE_DASHSCOPE_API_KEY_FILE" "./secrets/smoke/dashscope_api_key.txt" "empty"
    ensure_smoke_secret_file "SMOKE_DASHSCOPE_API_KEY_2_FILE" "./secrets/smoke/dashscope_api_key_2.txt" "empty"
    ensure_smoke_secret_file "SMOKE_GEMINI_API_KEY_FILE" "./secrets/smoke/gemini_api_key.txt" "empty"
    ensure_smoke_secret_file "SMOKE_GOOGLE_API_KEY_FILE" "./secrets/smoke/google_api_key.txt" "empty"
    ensure_smoke_secret_file "SMOKE_GOOGLE_CLIENT_SECRET_FILE" "./secrets/smoke/google_client_secret.txt" "empty"
    ensure_smoke_secret_file "SMOKE_GITHUB_TOKEN_FILE" "./secrets/smoke/github_token.txt" "empty"
    ensure_smoke_secret_file "SMOKE_GROWTHBOOK_SDK_KEY_FILE" "./secrets/smoke/growthbook_sdk_key.txt" "empty"
    ensure_smoke_secret_file "SMOKE_DEEPSEEK_API_KEY_FILE" "./secrets/smoke/deepseek_api_key.txt" "empty"
    ensure_smoke_secret_file "SMOKE_DEEPSEEK_API_KEY_2_FILE" "./secrets/smoke/deepseek_api_key_2.txt" "empty"
    ensure_smoke_secret_file "SMOKE_COHERE_API_KEY_FILE" "./secrets/smoke/cohere_api_key.txt" "empty"
    ensure_smoke_secret_file "SMOKE_COHERE_API_KEY_2_FILE" "./secrets/smoke/cohere_api_key_2.txt" "empty"
    ensure_smoke_secret_file "SMOKE_BIFROST_API_KEY_FILE" "./secrets/smoke/bifrost_api_key.txt" "empty"
    ensure_smoke_secret_file "SMOKE_BIFROST_ENCRYPTION_KEY_FILE" "./secrets/smoke/bifrost_encryption_key.txt" "empty"
    ensure_smoke_secret_file "SMOKE_LLM_API_KEY_FILE" "./secrets/smoke/llm_api_key.txt" "empty"
    ensure_smoke_secret_file "SMOKE_RAG_EMBED_API_KEY_FILE" "./secrets/smoke/rag_embed_api_key.txt" "empty"
    ensure_smoke_secret_file "SMOKE_LANGFUSE_PUBLIC_KEY_FILE" "./secrets/smoke/langfuse_public_key.txt" "empty"
    ensure_smoke_secret_file "SMOKE_LANGFUSE_SECRET_KEY_FILE" "./secrets/smoke/langfuse_secret_key.txt" "empty"
    ensure_smoke_secret_file "SMOKE_S3_ACCESS_KEY_ID_FILE" "./secrets/smoke/s3_access_key_id.txt" "empty"
    ensure_smoke_secret_file "SMOKE_S3_SECRET_ACCESS_KEY_FILE" "./secrets/smoke/s3_secret_access_key.txt" "empty"
    ensure_smoke_secret_file "SMOKE_TAVILY_API_KEY_FILE" "./secrets/smoke/tavily_api_key.txt" "empty"
}

ensure_smoke_volumes() {
    local volume_name

    require_cmd docker

    for volume_name in "${SMOKE_REQUIRED_VOLUME_NAMES[@]}"; do
        if ! docker volume inspect "$volume_name" >/dev/null 2>&1; then
            docker volume create "$volume_name" >/dev/null
            log_info "Created smoke volume: $volume_name"
        fi
    done
}

require_smoke_env_file() {
    local smoke_env_path
    smoke_env_path="$(resolve_project_path "$SMOKE_ENV_FILE")"
    if [[ ! -f "$smoke_env_path" ]]; then
        log_error "Missing smoke env file: $smoke_env_path"
        log_info "Run 'make env-smoke-prepare' to generate it from $SMOKE_ENV_TEMPLATE"
        exit 1
    fi
}

compose_smoke() {
    local smoke_env_path
    smoke_env_path="$(resolve_project_path "$SMOKE_ENV_FILE")"
    require_smoke_env_file
    local profile_args=()
    local subcmd="${1:-}"
    # For down, include optional profiles so profile-gated services are cleaned up.
    if [[ "$subcmd" == "down" ]]; then
        append_profile_arg "bifrost"
        append_profile_arg "s3"
    elif [[ -f "$smoke_env_path" ]]; then
        local llm_provider
        local storage_backend
        llm_provider="$(smoke_env_value "LLM_PROVIDER" "")"
        storage_backend="$(smoke_env_value "STORAGE_BACKEND" "local")"
        if llm_needs_bifrost_profile "$llm_provider"; then
            append_profile_arg "bifrost"
        fi
        if storage_needs_s3_profile "$storage_backend"; then
            append_profile_arg "s3"
        fi
    fi
    SMOKE_ENV_FILE="$smoke_env_path" docker compose --env-file "$smoke_env_path" -f "$SMOKE_COMPOSE_FILE" "${profile_args[@]}" "$@"
}

require_deploy_env_file() {
    local deploy_env_path
    deploy_env_path="$(resolve_project_path "$DEPLOY_ENV_FILE")"
    if [[ ! -f "$deploy_env_path" ]]; then
        log_error "Missing deploy env file: $deploy_env_path"
        log_info "Copy deploy/.env.ec2.template to deploy/.env.ec2 and fill in the required values"
        exit 1
    fi
}

deploy_env_value() {
    local name="$1"
    local default_value="$2"
    local deploy_env_path
    local value

    deploy_env_path="$(resolve_project_path "$DEPLOY_ENV_FILE")"
    if [[ -f "$deploy_env_path" ]]; then
        if value="$(
            awk -F= -v key="$name" '
                $0 !~ /^[[:space:]]*#/ && $1 == key {
                    sub(/^[^=]*=/, "")
                    print
                    found = 1
                    exit
                }
                END {
                    if (!found) {
                        exit 1
                    }
                }
            ' "$deploy_env_path"
        )"; then
            value="${value%\"}"
            value="${value#\"}"
            value="${value%\'}"
            value="${value#\'}"
            printf '%s\n' "$value"
            return
        fi
    fi

    if [[ -n "${!name:-}" ]]; then
        printf '%s\n' "${!name}"
        return
    fi

    printf '%s\n' "$default_value"
}

deploy_control_env_value() {
    local name="$1"
    local default_value="$2"
    local explicit_marker="${name}_EXPLICIT"

    if [[ -n "${!explicit_marker:-}" && -n "${!name:-}" && "${!name}" != "$default_value" ]]; then
        printf '%s\n' "${!name}"
        return
    fi

    deploy_env_file_value "$name" "$default_value"
}

deploy_env_file_value() {
    local name="$1"
    local default_value="$2"
    local deploy_env_path
    local value

    deploy_env_path="$(resolve_project_path "$DEPLOY_ENV_FILE")"
    if [[ -f "$deploy_env_path" ]]; then
        if value="$(
            awk -F= -v key="$name" '
                $0 !~ /^[[:space:]]*#/ && $1 == key {
                    sub(/^[^=]*=/, "")
                    print
                    found = 1
                    exit
                }
                END {
                    if (!found) {
                        exit 1
                    }
                }
            ' "$deploy_env_path"
        )"; then
            value="${value%\"}"
            value="${value#\"}"
            value="${value%\'}"
            value="${value#\'}"
            printf '%s\n' "$value"
            return
        fi
    fi

    printf '%s\n' "$default_value"
}

deploy_secret_file_path() {
    local env_name="$1"
    local file_name="$2"
    local default_path="${DEPLOY_SECRET_DIR%/}/$file_name"

    resolve_project_path "$(deploy_control_env_value "$env_name" "$default_path")"
}

load_deploy_env() {
    require_deploy_env_file

    DEPLOY_SECRET_DIR="$(deploy_control_env_value "DEPLOY_SECRET_DIR" "secrets/ec2")"
    DEPLOY_EXTRA_COMPOSE_FILES="$(deploy_control_env_value "DEPLOY_EXTRA_COMPOSE_FILES" "")"
    DEPLOY_BASE_URL="$(deploy_control_env_value "DEPLOY_BASE_URL" "http://localhost")"
    # 默认值用空串占位:动态默认 ($DEPLOY_BASE_URL) 会让显式传值因等于默认值而被
    # 文件值吞掉;空串默认保证非空显式值永远生效,回退逻辑放在下一行。
    DEPLOY_FRONTEND_BASE_URL="$(deploy_control_env_value "DEPLOY_FRONTEND_BASE_URL" "")"
    DEPLOY_FRONTEND_BASE_URL="${DEPLOY_FRONTEND_BASE_URL:-$DEPLOY_BASE_URL}"
    DEPLOY_FRONTEND_HEALTH_PATH="$(deploy_control_env_value "DEPLOY_FRONTEND_HEALTH_PATH" "/healthz")"
    DEPLOY_API_LIVE_PATH="$(deploy_control_env_value "DEPLOY_API_LIVE_PATH" "/api/v1/health_check/live")"
    DEPLOY_API_READY_PATH="$(deploy_control_env_value "DEPLOY_API_READY_PATH" "/api/v1/health_check/db_ready")"
    DEPLOY_ENABLE_BIFROST="$(deploy_control_env_value "DEPLOY_ENABLE_BIFROST" "false")"
    DEPLOY_ENABLE_OBSERVABILITY="$(deploy_control_env_value "DEPLOY_ENABLE_OBSERVABILITY" "false")"
    DEPLOY_ENABLE_FRONTEND_FALLBACK="$(deploy_control_env_value "DEPLOY_ENABLE_FRONTEND_FALLBACK" "false")"
    DEPLOY_CHECK_FRONTEND_HEALTH="$(deploy_control_env_value "DEPLOY_CHECK_FRONTEND_HEALTH" "false")"
    DEPLOY_PULL_IMAGES="$(deploy_control_env_value "DEPLOY_PULL_IMAGES" "false")"
    DEPLOY_LOG_TAIL="$(deploy_control_env_value "DEPLOY_LOG_TAIL" "200")"
    DEPLOY_SMOKE_PYTEST_TARGETS="$(deploy_control_env_value "DEPLOY_SMOKE_PYTEST_TARGETS" "$DEPLOY_SMOKE_PYTEST_TARGETS")"
    # No 2.0.0 fallback: an unset image variable must fail deploy-ec2-check
    # (see the required-image guard in ec2-check.sh), not silently run a stale
    # placeholder image. Release tags are immutable git-describe values.
    DOCKER_IMAGE_NAME_WEB="$(deploy_control_env_value "DOCKER_IMAGE_NAME_WEB" "")"
    DOCKER_IMAGE_NAME_AI="$(deploy_control_env_value "DOCKER_IMAGE_NAME_AI" "")"
    DOCKER_IMAGE_NAME_FRONTEND="$(deploy_control_env_value "DOCKER_IMAGE_NAME_FRONTEND" "")"
    DEPLOY_SECRET_KEY_FILE="$(deploy_secret_file_path "DEPLOY_SECRET_KEY_FILE" "secret_key.txt")"
    DEPLOY_POSTGRES_PASSWORD_FILE="$(deploy_secret_file_path "DEPLOY_POSTGRES_PASSWORD_FILE" "postgres_password.txt")"
    DEPLOY_REDIS_PASSWORD_FILE="$(deploy_secret_file_path "DEPLOY_REDIS_PASSWORD_FILE" "redis_password.txt")"
    DEPLOY_OPENAI_API_KEY_FILE="$(deploy_secret_file_path "DEPLOY_OPENAI_API_KEY_FILE" "openai_api_key.txt")"
    DEPLOY_DASHSCOPE_API_KEY_FILE="$(deploy_secret_file_path "DEPLOY_DASHSCOPE_API_KEY_FILE" "dashscope_api_key.txt")"
    DEPLOY_DASHSCOPE_API_KEY_2_FILE="$(deploy_secret_file_path "DEPLOY_DASHSCOPE_API_KEY_2_FILE" "dashscope_api_key_2.txt")"
    DEPLOY_GEMINI_API_KEY_FILE="$(deploy_secret_file_path "DEPLOY_GEMINI_API_KEY_FILE" "gemini_api_key.txt")"
    DEPLOY_GOOGLE_API_KEY_FILE="$(deploy_secret_file_path "DEPLOY_GOOGLE_API_KEY_FILE" "google_api_key.txt")"
    DEPLOY_GOOGLE_CLIENT_SECRET_FILE="$(deploy_secret_file_path "DEPLOY_GOOGLE_CLIENT_SECRET_FILE" "google_client_secret.txt")"
    DEPLOY_GITHUB_TOKEN_FILE="$(deploy_secret_file_path "DEPLOY_GITHUB_TOKEN_FILE" "github_token.txt")"
    DEPLOY_GROWTHBOOK_SDK_KEY_FILE="$(deploy_secret_file_path "DEPLOY_GROWTHBOOK_SDK_KEY_FILE" "growthbook_sdk_key.txt")"
    DEPLOY_DEEPSEEK_API_KEY_FILE="$(deploy_secret_file_path "DEPLOY_DEEPSEEK_API_KEY_FILE" "deepseek_api_key.txt")"
    DEPLOY_DEEPSEEK_API_KEY_2_FILE="$(deploy_secret_file_path "DEPLOY_DEEPSEEK_API_KEY_2_FILE" "deepseek_api_key_2.txt")"
    DEPLOY_COHERE_API_KEY_FILE="$(deploy_secret_file_path "DEPLOY_COHERE_API_KEY_FILE" "cohere_api_key.txt")"
    DEPLOY_COHERE_API_KEY_2_FILE="$(deploy_secret_file_path "DEPLOY_COHERE_API_KEY_2_FILE" "cohere_api_key_2.txt")"
    DEPLOY_BIFROST_API_KEY_FILE="$(deploy_secret_file_path "DEPLOY_BIFROST_API_KEY_FILE" "bifrost_api_key.txt")"
    DEPLOY_BIFROST_ENCRYPTION_KEY_FILE="$(deploy_secret_file_path "DEPLOY_BIFROST_ENCRYPTION_KEY_FILE" "bifrost_encryption_key.txt")"
    DEPLOY_LLM_API_KEY_FILE="$(deploy_secret_file_path "DEPLOY_LLM_API_KEY_FILE" "llm_api_key.txt")"
    DEPLOY_RAG_EMBED_API_KEY_FILE="$(deploy_secret_file_path "DEPLOY_RAG_EMBED_API_KEY_FILE" "rag_embed_api_key.txt")"
    DEPLOY_LANGFUSE_PUBLIC_KEY_FILE="$(deploy_secret_file_path "DEPLOY_LANGFUSE_PUBLIC_KEY_FILE" "langfuse_public_key.txt")"
    DEPLOY_LANGFUSE_SECRET_KEY_FILE="$(deploy_secret_file_path "DEPLOY_LANGFUSE_SECRET_KEY_FILE" "langfuse_secret_key.txt")"
    DEPLOY_S3_ACCESS_KEY_ID_FILE="$(deploy_secret_file_path "DEPLOY_S3_ACCESS_KEY_ID_FILE" "s3_access_key_id.txt")"
    DEPLOY_S3_SECRET_ACCESS_KEY_FILE="$(deploy_secret_file_path "DEPLOY_S3_SECRET_ACCESS_KEY_FILE" "s3_secret_access_key.txt")"
    DEPLOY_TAVILY_API_KEY_FILE="$(deploy_secret_file_path "DEPLOY_TAVILY_API_KEY_FILE" "tavily_api_key.txt")"

    export DEPLOY_SECRET_DIR
    export DEPLOY_EXTRA_COMPOSE_FILES
    export DEPLOY_BASE_URL
    export DEPLOY_FRONTEND_BASE_URL
    export DEPLOY_FRONTEND_HEALTH_PATH
    export DEPLOY_API_LIVE_PATH
    export DEPLOY_API_READY_PATH
    export DEPLOY_ENABLE_BIFROST
    export DEPLOY_ENABLE_OBSERVABILITY
    export DEPLOY_ENABLE_FRONTEND_FALLBACK
    export DEPLOY_CHECK_FRONTEND_HEALTH
    export DEPLOY_PULL_IMAGES
    export DEPLOY_LOG_TAIL
    export DEPLOY_SMOKE_PYTEST_TARGETS
    export DOCKER_IMAGE_NAME_WEB
    export DOCKER_IMAGE_NAME_AI
    export DOCKER_IMAGE_NAME_FRONTEND
    export DEPLOY_SECRET_KEY_FILE
    export DEPLOY_POSTGRES_PASSWORD_FILE
    export DEPLOY_REDIS_PASSWORD_FILE
    export DEPLOY_OPENAI_API_KEY_FILE
    export DEPLOY_DASHSCOPE_API_KEY_FILE
    export DEPLOY_DASHSCOPE_API_KEY_2_FILE
    export DEPLOY_GEMINI_API_KEY_FILE
    export DEPLOY_GOOGLE_API_KEY_FILE
    export DEPLOY_GOOGLE_CLIENT_SECRET_FILE
    export DEPLOY_GITHUB_TOKEN_FILE
    export DEPLOY_GROWTHBOOK_SDK_KEY_FILE
    export DEPLOY_DEEPSEEK_API_KEY_FILE
    export DEPLOY_DEEPSEEK_API_KEY_2_FILE
    export DEPLOY_COHERE_API_KEY_FILE
    export DEPLOY_COHERE_API_KEY_2_FILE
    export DEPLOY_BIFROST_API_KEY_FILE
    export DEPLOY_BIFROST_ENCRYPTION_KEY_FILE
    export DEPLOY_LLM_API_KEY_FILE
    export DEPLOY_RAG_EMBED_API_KEY_FILE
    export DEPLOY_LANGFUSE_PUBLIC_KEY_FILE
    export DEPLOY_LANGFUSE_SECRET_KEY_FILE
    export DEPLOY_S3_ACCESS_KEY_ID_FILE
    export DEPLOY_S3_SECRET_ACCESS_KEY_FILE
    export DEPLOY_TAVILY_API_KEY_FILE
}

ensure_deploy_secret_file() {
    local file_env_name="$1"
    local mode="${2:-empty}"
    local secret_path="${!file_env_name}"
    local secret_dir

    secret_dir="$(dirname "$secret_path")"
    mkdir -p "$secret_dir"

    if [[ -s "$secret_path" ]]; then
        chmod 600 "$secret_path"
        return
    fi
    if [[ -f "$secret_path" && "$mode" == "empty" ]]; then
        chmod 600 "$secret_path"
        return
    fi

    (
        umask 077
        if [[ "$mode" == "empty" ]]; then
            touch "$secret_path"
            log_info "Created empty deploy secret file: $secret_path"
        else
            generate_smoke_secret >"$secret_path"
            log_info "Generated deploy secret: $secret_path"
        fi
        chmod 600 "$secret_path"
    )
}

ensure_deploy_secret_files() {
    local file_env_name
    local mode

    load_deploy_env

    for file_env_name in "${DEPLOY_SECRET_FILE_ENV_NAMES[@]}"; do
        mode="empty"
        case "$file_env_name" in
            DEPLOY_SECRET_KEY_FILE|DEPLOY_POSTGRES_PASSWORD_FILE|DEPLOY_REDIS_PASSWORD_FILE)
                mode="random"
                ;;
        esac
        ensure_deploy_secret_file "$file_env_name" "$mode"
    done
}

compose_deploy() {
    local deploy_env_path
    local deploy_compose_path
    local compose_file_args=()
    local extra_compose_file
    local profile_args=()
    local subcmd="${1:-}"
    local provider_var
    local provider_value

    deploy_env_path="$(resolve_project_path "$DEPLOY_ENV_FILE")"
    deploy_compose_path="$(resolve_project_path "$DEPLOY_COMPOSE_FILE")"
    require_deploy_env_file
    compose_file_args=(-f "$deploy_compose_path")
    for extra_compose_file in $DEPLOY_EXTRA_COMPOSE_FILES; do
        compose_file_args+=(-f "$(resolve_project_path "$extra_compose_file")")
    done

    if [[ "$subcmd" == "down" ]]; then
        append_profile_arg "bifrost"
        append_profile_arg "observability"
        append_profile_arg "frontend-fallback"
        append_profile_arg "debug"
    elif [[ "${DEPLOY_ENABLE_OBSERVABILITY:-false}" == "true" ]]; then
        append_profile_arg "observability"
    fi
    if [[ "$subcmd" != "down" ]]; then
        if [[ "${DEPLOY_ENABLE_FRONTEND_FALLBACK:-false}" == "true" ]]; then
            append_profile_arg "frontend-fallback"
        fi
        if [[ "${DEPLOY_ENABLE_BIFROST:-false}" == "true" ]]; then
            append_profile_arg "bifrost"
        else
            for provider_var in LLM_PROVIDER LLM_MODEL_ROUTE_FAST_PROVIDER LLM_MODEL_ROUTE_BALANCED_PROVIDER LLM_MODEL_ROUTE_REASONING_PROVIDER RAG_EMBED_PROVIDER RAG_PLANNER_PROVIDER RAG_RERANK_PROVIDER; do
                provider_value="$(deploy_control_env_value "$provider_var" "")"
                if provider_needs_bifrost_profile "$provider_value"; then
                    append_profile_arg "bifrost"
                    break
                fi
            done
        fi
    fi

    DEPLOY_SERVICE_ENV_FILE="$deploy_env_path" docker compose --env-file "$deploy_env_path" "${compose_file_args[@]}" "${profile_args[@]}" "$@"
}

print_smoke_logs() {
    log_warn "Smoke environment status:"
    compose_smoke ps || true
    log_warn "Recent Smoke logs:"
    compose_smoke logs --tail=200 || true
}

print_deploy_logs() {
    log_warn "Deploy environment status:"
    compose_deploy ps || true
    log_warn "Recent deploy logs:"
    compose_deploy logs --tail="$DEPLOY_LOG_TAIL" || true
}

wait_for_http_ok() {
    local url="$1"
    local timeout="${2:-$SMOKE_TIMEOUT_SECONDS}"
    local interval="${3:-$SMOKE_POLL_INTERVAL_SECONDS}"
    # 单次请求超时与轮询间隔解耦,避免响应慢于 interval 的端点被永久误判失败
    local request_timeout=10
    local elapsed=0
    local status

    require_cmd curl

    while (( elapsed < timeout )); do
        status="$(
            curl \
                --connect-timeout 2 \
                --max-time "$request_timeout" \
                -sS \
                -o /dev/null \
                -w '%{http_code}' \
                "$url" || true
        )"
        if [[ "$status" == "200" ]]; then
            return 0
        fi
        sleep "$interval"
        elapsed=$((elapsed + interval))
    done

    log_error "Timed out waiting for HTTP 200: $url"
    return 1
}
