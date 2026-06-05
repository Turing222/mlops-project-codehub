#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd docker
require_cmd curl
require_deploy_env_file

deploy_env_path="$(resolve_project_path "$DEPLOY_ENV_FILE")"
deploy_compose_path="$(resolve_project_path "$DEPLOY_COMPOSE_FILE")"

log_section "Running EC2 deploy preflight checks"

if ! docker compose version >/dev/null 2>&1; then
    log_error "Docker Compose plugin is required"
    exit 1
fi

load_deploy_env

deploy_env_file_value() {
    local var_name="$1"

    awk -F= -v key="$var_name" '
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
}

reject_plaintext_secret_env_value() {
    local var_name="$1"
    local value

    if value="$(deploy_env_file_value "$var_name")" && [[ -n "$value" ]]; then
        log_error "$var_name must be stored in secrets/ec2, not in $deploy_env_path"
        log_info "Run 'make deploy-ec2-secrets-prepare' and move the value into the matching secrets/ec2/*.txt file"
        exit 1
    fi
}

reject_placeholder_value() {
    local var_name="$1"
    local value

    value="$(deploy_control_env_value "$var_name" "")"
    case "$value" in
        change-me*|replace-me*|your-domain.example.com*|*your-domain.example.com*)
            log_error "Required deploy variable still uses placeholder value: $var_name"
            exit 1
            ;;
    esac
}

reject_placeholder_secret_file_value() {
    local secret_name="$1"
    local secret_path="$2"
    local value

    value="$(tr -d '\r\n' <"$secret_path")"
    case "$value" in
        change-me*|replace-me*|your-domain.example.com*|*your-domain.example.com*)
            log_error "Required deploy secret file still uses placeholder value: $secret_name"
            exit 1
            ;;
    esac
}

is_deploy_true() {
    local value="${1,,}"
    [[ "$value" == "1" || "$value" == "true" || "$value" == "yes" || "$value" == "on" ]]
}

require_deploy_secret_file() {
    local file_env_name="$1"
    local secret_path="${!file_env_name}"

    if [[ ! -f "$secret_path" ]]; then
        log_error "Missing deploy secret file: $file_env_name=$secret_path"
        log_info "Run 'make deploy-ec2-secrets-prepare' to create EC2 deploy secret files"
        exit 1
    fi
}

require_non_empty_deploy_secret_file() {
    local file_env_name="$1"
    local secret_name="$2"
    local secret_path="${!file_env_name}"

    require_deploy_secret_file "$file_env_name"
    if [[ ! -s "$secret_path" ]]; then
        log_error "Required deploy secret file is empty: $file_env_name=$secret_path"
        exit 1
    fi
    reject_placeholder_secret_file_value "$secret_name" "$secret_path"
}

required_vars=(
    POSTGRES_USER
    POSTGRES_DB
)

google_oauth_enabled="$(deploy_env_value "GOOGLE_OAUTH_ENABLED" "false")"
if is_deploy_true "$google_oauth_enabled"; then
    required_vars+=(
        GOOGLE_CLIENT_ID
        GOOGLE_ALLOWED_REDIRECT_URIS
    )
fi

plaintext_secret_vars=(
    SECRET_KEY
    POSTGRES_PASSWORD
    REDIS_PASSWORD
    OPENAI_API_KEY
    DASHSCOPE_API_KEY
    DASHSCOPE_API_KEY_2
    GEMINI_API_KEY
    GOOGLE_API_KEY
    GOOGLE_CLIENT_SECRET
    GITHUB_TOKEN
    GROWTHBOOK_SDK_KEY
    DEEPSEEK_API_KEY
    DEEPSEEK_API_KEY_2
    COHERE_API_KEY
    COHERE_API_KEY_2
    BIFROST_API_KEY
    BIFROST_ENCRYPTION_KEY
    LLM_API_KEY
    RAG_EMBED_API_KEY
    LANGFUSE_PUBLIC_KEY
    LANGFUSE_SECRET_KEY
    S3_ACCESS_KEY_ID
    S3_SECRET_ACCESS_KEY
    TAVILY_API_KEY
)

for var_name in "${plaintext_secret_vars[@]}"; do
    reject_plaintext_secret_env_value "$var_name"
done

for var_name in "${required_vars[@]}"; do
    if [[ -z "$(deploy_env_value "$var_name" "")" ]]; then
        log_error "Required deploy variable is missing: $var_name"
        exit 1
    fi
done

storage_backend="$(deploy_env_value "STORAGE_BACKEND" "s3")"
if [[ "$storage_backend" == "s3" && -z "$(deploy_env_value "S3_BUCKET" "")" ]]; then
    log_error "S3_BUCKET is required when STORAGE_BACKEND=s3"
    exit 1
fi

if [[ -z "$DOCKER_IMAGE_NAME_WEB" || -z "$DOCKER_IMAGE_NAME_AI" || -z "$DOCKER_IMAGE_NAME_FRONTEND" ]]; then
    log_error "All deploy image variables must be set: DOCKER_IMAGE_NAME_WEB / DOCKER_IMAGE_NAME_AI / DOCKER_IMAGE_NAME_FRONTEND"
    exit 1
fi

if [[ -z "$DEPLOY_BASE_URL" ]]; then
    log_error "DEPLOY_BASE_URL must not be empty"
    exit 1
fi

placeholder_checked_vars=(
)

for var_name in "${placeholder_checked_vars[@]}"; do
    reject_placeholder_value "$var_name"
done

if is_deploy_true "$google_oauth_enabled"; then
    reject_placeholder_value "GOOGLE_ALLOWED_REDIRECT_URIS"
    require_non_empty_deploy_secret_file "DEPLOY_GOOGLE_CLIENT_SECRET_FILE" "GOOGLE_CLIENT_SECRET"
fi

if [[ "$storage_backend" == "s3" ]]; then
    reject_placeholder_value "S3_BUCKET"
fi

for file_env_name in "${DEPLOY_SECRET_FILE_ENV_NAMES[@]}"; do
    require_deploy_secret_file "$file_env_name"
done

require_non_empty_deploy_secret_file "DEPLOY_SECRET_KEY_FILE" "SECRET_KEY"
require_non_empty_deploy_secret_file "DEPLOY_POSTGRES_PASSWORD_FILE" "POSTGRES_PASSWORD"
require_non_empty_deploy_secret_file "DEPLOY_REDIS_PASSWORD_FILE" "REDIS_PASSWORD"

compose_deploy config >/dev/null

log_info "Deploy env file: $deploy_env_path"
log_info "Deploy compose file: $deploy_compose_path"
log_info "Deploy base URL: ${DEPLOY_BASE_URL}"
log_info "EC2 deploy preflight check passed."
