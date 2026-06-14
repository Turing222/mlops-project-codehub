#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd docker
require_cmd curl
require_cmd python3
require_deploy_env_file

deploy_env_path="$(resolve_project_path "$DEPLOY_ENV_FILE")"
deploy_compose_path="$(resolve_project_path "$DEPLOY_COMPOSE_FILE")"

log_section "Running EC2 deploy preflight checks"

if ! docker compose version >/dev/null 2>&1; then
    log_error "Docker Compose plugin is required"
    exit 1
fi

load_deploy_env

raw_deploy_env_file_value() {
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

    if value="$(raw_deploy_env_file_value "$var_name")" && [[ -n "$value" ]]; then
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
        *change-me*|*replace-me*|your-domain.example.com*|*your-domain.example.com*)
            log_error "Required deploy secret file still uses placeholder value: $secret_name"
            exit 1
            ;;
    esac
}

is_deploy_true() {
    local value="${1,,}"
    [[ "$value" == "1" || "$value" == "true" || "$value" == "yes" || "$value" == "on" ]]
}

selfhost_postgres_enabled() {
    local extra_compose_file
    local extra_compose_path

    for extra_compose_file in $DEPLOY_EXTRA_COMPOSE_FILES; do
        extra_compose_path="$(resolve_project_path "$extra_compose_file")"
        case "$extra_compose_file:$extra_compose_path" in
            *deploy/docker-compose.local-postgres.yml*)
                return 0
                ;;
        esac
    done
    return 1
}

compose_config_services_use_awslogs() {
    compose_deploy config --format json \
        | python3 -c '
import json
import sys

config = json.load(sys.stdin)
for service in (config.get("services") or {}).values():
    if (service.get("logging") or {}).get("driver") == "awslogs":
        sys.exit(0)
sys.exit(1)
'
}

postgres_server_is_ip_address() {
    local host="$1"

    [[ "$host" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]
}

require_rds_hostname_for_verified_ssl() {
    local postgres_server="$1"
    local postgres_ssl_mode

    postgres_ssl_mode="$(deploy_control_env_value "POSTGRES_SSL_MODE" "verify-full")"
    postgres_ssl_mode="${postgres_ssl_mode,,}"

    if [[ "$postgres_ssl_mode" != "verify-full" && "$postgres_ssl_mode" != "verify-ca" ]]; then
        return 0
    fi
    if postgres_server_is_ip_address "$postgres_server"; then
        log_error "POSTGRES_SERVER must be the RDS endpoint hostname for POSTGRES_SSL_MODE=${postgres_ssl_mode}"
        log_info "verify-ca/verify-full validate the server certificate against the configured host name; do not use an IP address"
        exit 1
    fi
}

require_cloudwatch_log_group() {
    local region
    local log_group
    local existing_log_group

    region="$(deploy_control_env_value "DEPLOY_AWS_REGION" "us-east-1")"
    log_group="$(deploy_control_env_value "DEPLOY_CW_LOG_GROUP" "/dewflow/prod")"

    require_cmd aws
    if ! existing_log_group="$(
        aws logs describe-log-groups \
            --region "$region" \
            --log-group-name-prefix "$log_group" \
            --query "logGroups[?logGroupName=='${log_group}'].logGroupName" \
            --output text
    )"; then
        log_error "Unable to verify CloudWatch log group: $log_group"
        log_info "Run 'make deploy-cloudwatch-setup' after confirming AWS credentials and region"
        exit 1
    fi

    if ! grep -qx "$log_group" <<<"$existing_log_group"; then
        log_error "CloudWatch log group does not exist: $log_group"
        log_info "Run 'make deploy-cloudwatch-setup' before starting the EC2 deploy stack"
        exit 1
    fi
}

deploy_secret_file_allows_runtime_read() {
    local secret_path="$1"
    local mode
    local owner_uid
    local owner_gid
    local perms
    local owner_perm
    local group_perm
    local other_perm

    mode="$(stat -c "%a" "$secret_path")"
    owner_uid="$(stat -c "%u" "$secret_path")"
    owner_gid="$(stat -c "%g" "$secret_path")"
    perms="${mode: -3}"
    owner_perm="${perms:0:1}"
    group_perm="${perms:1:1}"
    other_perm="${perms:2:1}"

    if [[ "$owner_uid" == "10001" ]] && (((10#$owner_perm & 4) != 0)); then
        return 0
    fi
    if [[ "$owner_gid" == "10001" ]] && (((10#$group_perm & 4) != 0)); then
        return 0
    fi
    (((10#$other_perm & 4) != 0))
}

require_deploy_secret_file() {
    local file_env_name="$1"
    local secret_path="${!file_env_name}"

    if [[ ! -f "$secret_path" ]]; then
        log_error "Missing deploy secret file: $file_env_name=$secret_path"
        log_info "Run 'make deploy-ec2-secrets-prepare' to create EC2 deploy secret files"
        exit 1
    fi
    if ! deploy_secret_file_allows_runtime_read "$secret_path"; then
        log_error "Deploy secret file is not readable by container UID 10001: $file_env_name=$secret_path"
        log_info "Run 'make deploy-ec2-secrets-prepare' to refresh file permissions"
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

require_bifrost_api_key_format() {
    local value

    value="$(tr -d '\r\n' <"$DEPLOY_BIFROST_API_KEY_FILE")"
    case "$value" in
        sk-bf-*)
            ;;
        *)
            log_error "BIFROST_API_KEY must start with sk-bf- for Bifrost v1.4.11"
            exit 1
            ;;
    esac
}

require_bifrost_runtime_secrets() {
    local profile_required=false
    local chat_required=false
    local dashscope_required=false
    local provider_var
    local provider_value

    if is_deploy_true "${DEPLOY_ENABLE_BIFROST:-false}"; then
        profile_required=true
    fi

    for provider_var in LLM_PROVIDER LLM_MODEL_ROUTE_FAST_PROVIDER LLM_MODEL_ROUTE_BALANCED_PROVIDER LLM_MODEL_ROUTE_REASONING_PROVIDER RAG_PLANNER_PROVIDER RAG_EMBED_PROVIDER RAG_RERANK_PROVIDER; do
        provider_value="$(deploy_control_env_value "$provider_var" "")"
        if provider_needs_bifrost_profile "$provider_value"; then
            profile_required=true
            case "$provider_var" in
                RAG_EMBED_PROVIDER|RAG_RERANK_PROVIDER)
                    dashscope_required=true
                    ;;
                *)
                    chat_required=true
                    ;;
            esac
        fi
    done

    if [[ "$profile_required" != "true" ]]; then
        return
    fi

    require_non_empty_deploy_secret_file "DEPLOY_BIFROST_API_KEY_FILE" "BIFROST_API_KEY"
    require_bifrost_api_key_format
    require_non_empty_deploy_secret_file "DEPLOY_BIFROST_ENCRYPTION_KEY_FILE" "BIFROST_ENCRYPTION_KEY"

    if [[ "$chat_required" == "true" ]]; then
        require_non_empty_deploy_secret_file "DEPLOY_DEEPSEEK_API_KEY_FILE" "DEEPSEEK_API_KEY"
        require_non_empty_deploy_secret_file "DEPLOY_DEEPSEEK_API_KEY_2_FILE" "DEEPSEEK_API_KEY_2"
    fi

    if [[ "$dashscope_required" == "true" ]]; then
        require_non_empty_deploy_secret_file "DEPLOY_DASHSCOPE_API_KEY_FILE" "DASHSCOPE_API_KEY"
        require_non_empty_deploy_secret_file "DEPLOY_DASHSCOPE_API_KEY_2_FILE" "DASHSCOPE_API_KEY_2"
    fi
}

required_vars=(
    POSTGRES_USER
    POSTGRES_DB
    POSTGRES_SERVER
    POSTGRES_PORT
)

google_oauth_enabled="$(deploy_control_env_value "GOOGLE_OAUTH_ENABLED" "false")"
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
    if [[ -z "$(deploy_control_env_value "$var_name" "")" ]]; then
        log_error "Required deploy variable is missing: $var_name"
        exit 1
    fi
done

storage_backend="$(deploy_control_env_value "STORAGE_BACKEND" "s3")"
case "${storage_backend,,}" in
    s3)
        if [[ -z "$(deploy_control_env_value "S3_BUCKET" "")" ]]; then
            log_error "S3_BUCKET is required when STORAGE_BACKEND=s3"
            exit 1
        fi
        ;;
    local)
        log_error "STORAGE_BACKEND=local is not supported by the EC2 deploy stack"
        log_info "Use STORAGE_BACKEND=s3 for deploy/docker-compose.yml, or docker-compose.db.yml for local/smoke storage tests"
        exit 1
        ;;
    *)
        log_error "Unsupported STORAGE_BACKEND for the EC2 deploy stack: $storage_backend"
        log_info "Use STORAGE_BACKEND=s3 for deploy/docker-compose.yml"
        exit 1
        ;;
esac

postgres_server="$(deploy_control_env_value "POSTGRES_SERVER" "")"
if [[ "$postgres_server" == "postgres" ]] && ! selfhost_postgres_enabled; then
    log_error "POSTGRES_SERVER=postgres requires DEPLOY_EXTRA_COMPOSE_FILES=deploy/docker-compose.local-postgres.yml"
    log_info "For production RDS, set POSTGRES_SERVER to the RDS endpoint and keep POSTGRES_SSL_MODE=verify-full"
    exit 1
fi

if [[ -n "$postgres_server" && "$postgres_server" != "postgres" ]]; then
    require_rds_hostname_for_verified_ssl "$postgres_server"
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
    POSTGRES_SERVER
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
require_bifrost_runtime_secrets

if compose_config_services_use_awslogs; then
    require_cloudwatch_log_group
fi

log_info "Deploy env file: $deploy_env_path"
log_info "Deploy compose file: $deploy_compose_path"
log_info "Deploy base URL: ${DEPLOY_BASE_URL}"
log_info "EC2 deploy preflight check passed."
