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

reject_placeholder_value() {
    local var_name="$1"
    local value

    value="$(deploy_env_value "$var_name" "")"
    case "$value" in
        change-me*|replace-me*|your-domain.example.com*|*your-domain.example.com*)
            log_error "Required deploy variable still uses placeholder value: $var_name"
            exit 1
            ;;
    esac
}

required_vars=(
    SECRET_KEY
    GOOGLE_ALLOWED_REDIRECT_URIS
    POSTGRES_USER
    POSTGRES_PASSWORD
    POSTGRES_DB
    REDIS_PASSWORD
)

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
    SECRET_KEY
    GOOGLE_ALLOWED_REDIRECT_URIS
    POSTGRES_PASSWORD
    REDIS_PASSWORD
)

for var_name in "${placeholder_checked_vars[@]}"; do
    reject_placeholder_value "$var_name"
done

if [[ "$storage_backend" == "s3" ]]; then
    reject_placeholder_value "S3_BUCKET"
fi

compose_deploy config >/dev/null

log_info "Deploy env file: $deploy_env_path"
log_info "Deploy compose file: $deploy_compose_path"
log_info "Deploy base URL: ${DEPLOY_BASE_URL}"
log_info "EC2 deploy preflight check passed."
