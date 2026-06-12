#!/usr/bin/env bash
# Source .env.smoke and export infrastructure variables, then exec the
# given command.  Used by flow-local so integration tests can connect
# to the Docker smoke stack (postgres, redis) using the same config
# the containers use.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

cd "$PROJECT_ROOT"

smoke_env_path="$(resolve_project_path "$SMOKE_ENV_FILE")"
if [[ ! -f "$smoke_env_path" ]]; then
    log_error "Missing smoke env file: $smoke_env_path"
    log_info "Run 'make env-smoke-prepare' to generate it from $SMOKE_ENV_TEMPLATE"
    exit 1
fi

# Read a value from .env.smoke.
_smoke_env_value() {
    local name="$1"
    awk -F= -v key="$name" '
        $0 !~ /^[[:space:]]*#/ && $1 == key {
            sub(/^[^=]*=/, "")
            print
            exit
        }
    ' "$smoke_env_path" | sed "s/^['\"]//;s/['\"]$//"
}

# Load infrastructure variables from .env.smoke.
for var in POSTGRES_USER POSTGRES_DB POSTGRES_SERVER POSTGRES_PORT \
           REDIS_HOST REDIS_PORT REDIS_HOST_PORT CURRENT_UID CURRENT_GID; do
    val="$(_smoke_env_value "$var")"
    if [[ -n "$val" ]]; then
        export "$var=$val"
    fi
done

# Override container-internal hostnames to localhost for host-side tests.
if [[ "${POSTGRES_SERVER:-}" == "postgres" ]]; then
    export POSTGRES_SERVER=localhost
fi
if [[ "${REDIS_HOST:-}" == "redis" ]]; then
    export REDIS_HOST=localhost
fi

# Read passwords from Docker secret files.
_secret_val() {
    local file_var="$1"
    local default_path="$2"
    local path
    path="$(smoke_env_value "$file_var" "$default_path")"
    path="$(resolve_project_path "$path")"
    if [[ -s "$path" ]]; then
        tr -d '\r\n' < "$path"
    else
        echo ""
    fi
}

pg_pass="$(_secret_val SMOKE_POSTGRES_PASSWORD_FILE ./secrets/smoke/postgres_password.txt)"
redis_pass="$(_secret_val SMOKE_REDIS_PASSWORD_FILE ./secrets/smoke/redis_password.txt)"

# Export derived URLs (passwords URL-encoded).
_url_encode() {
    URL_ENCODE_VALUE="$1" uv run python -c \
        "import os; from urllib.parse import quote; print(quote(os.environ['URL_ENCODE_VALUE'], safe=''))"
}

if [[ -n "$pg_pass" ]]; then
    export POSTGRES_PASSWORD="$pg_pass"
    pg_user="${POSTGRES_USER:-admin}"
    pg_db="${POSTGRES_DB:-postgres}"
    pg_port="${POSTGRES_PORT:-5432}"
    pg_enc="$(_url_encode "$pg_pass")"
    export TEST_DATABASE_URL="postgresql+asyncpg://${pg_user}:${pg_enc}@${POSTGRES_SERVER}:${pg_port}/${pg_db}"
fi

if [[ -n "$redis_pass" ]]; then
    export REDIS_PASSWORD="$redis_pass"
    redis_enc="$(_url_encode "$redis_pass")"
    redis_port="${REDIS_HOST_PORT:-${REDIS_PORT:-6379}}"
    export TEST_REDIS_URL="redis://:${redis_enc}@${REDIS_HOST}:${redis_port}/0"
    export TEST_TASKIQ_REDIS_URL="redis://:${redis_enc}@${REDIS_HOST}:${redis_port}/1"
fi

# S3 / MinIO — compose defaults to minioadmin/minioadmin on port 9000.
s3_endpoint="$(_smoke_env_value S3_ENDPOINT_URL)"
s3_access_key="$(_smoke_env_value S3_ACCESS_KEY_ID)"
s3_secret_key="$(_smoke_env_value S3_SECRET_ACCESS_KEY)"
if [[ -n "$s3_endpoint" ]]; then
    # Override container-internal hostname to localhost.
    s3_endpoint="${s3_endpoint//minio/localhost}"
else
    s3_endpoint="http://localhost:${MINIO_API_PORT:-9000}"
fi
s3_access_key="${s3_access_key:-minioadmin}"
s3_secret_key="${s3_secret_key:-minioadmin}"
s3_enc_user="$(_url_encode "$s3_access_key")"
s3_enc_pass="$(_url_encode "$s3_secret_key")"
export TEST_S3_ENDPOINT_URL="${s3_endpoint}"
export S3_ACCESS_KEY_ID="$s3_access_key"
export S3_SECRET_ACCESS_KEY="$s3_secret_key"

export DEWFLOW_TEST_PROFILE="${DEWFLOW_TEST_PROFILE:-local}"

exec "$@"
