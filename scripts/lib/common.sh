#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DOCKER_IMAGE_NAME="${DOCKER_IMAGE_NAME:-dewflow-backend:2.0.0}"
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

print_smoke_logs() {
    log_warn "Smoke environment status:"
    compose_smoke ps || true
    log_warn "Recent Smoke logs:"
    compose_smoke logs --tail=200 || true
}

wait_for_http_ok() {
    local url="$1"
    local timeout="${2:-$SMOKE_TIMEOUT_SECONDS}"
    local interval="${3:-$SMOKE_POLL_INTERVAL_SECONDS}"
    local elapsed=0
    local status

    require_cmd curl

    while (( elapsed < timeout )); do
        status="$(
            curl \
                --connect-timeout 2 \
                --max-time "$interval" \
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
