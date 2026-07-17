#!/usr/bin/env bash
# Run the T1-4 destructive recovery matrix against disposable infrastructure only.

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

readonly POSTGRES_CONTAINER="dewflow-t1-4-fault-postgres"
readonly CACHE_CONTAINER="dewflow-t1-4-fault-cache"
readonly TASKIQ_CONTAINER="dewflow-t1-4-fault-taskiq"
readonly TASKIQ_VOLUME="dewflow-t1-4-fault-taskiq-data"
readonly POSTGRES_PASSWORD="fault-postgres-password"
readonly REDIS_PASSWORD="fault-redis-password"

cleanup() {
    local exit_code=$?
    trap - EXIT

    if (( exit_code != 0 )); then
        log_warn "T1-4 fault matrix failed; printing disposable service logs"
        for container in "$POSTGRES_CONTAINER" "$CACHE_CONTAINER" "$TASKIQ_CONTAINER"; do
            if docker inspect "$container" >/dev/null 2>&1; then
                log_section "$container logs"
                docker logs --tail 120 "$container" 2>&1 || true
            fi
        done
    fi

    docker rm -f \
        "$POSTGRES_CONTAINER" \
        "$CACHE_CONTAINER" \
        "$TASKIQ_CONTAINER" >/dev/null 2>&1 || true
    docker volume rm "$TASKIQ_VOLUME" >/dev/null 2>&1 || true
    exit "$exit_code"
}

wait_for_postgres() {
    for _ in {1..60}; do
        if docker exec "$POSTGRES_CONTAINER" \
            pg_isready -U fault -d fault >/dev/null 2>&1; then
            return
        fi
        sleep 1
    done
    log_error "Disposable PostgreSQL did not become ready"
    return 1
}

wait_for_redis() {
    local container="$1"
    for _ in {1..60}; do
        if docker exec "$container" \
            redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping 2>/dev/null \
            | grep -qx PONG; then
            return
        fi
        sleep 1
    done
    log_error "Disposable Redis did not become ready: $container"
    return 1
}

require_cmd docker
require_cmd uv
trap cleanup EXIT

log_section "Preparing disposable T1-4 fault environment"

# These names are reserved for this runner. Never discover or remove arbitrary containers.
docker rm -f \
    "$POSTGRES_CONTAINER" \
    "$CACHE_CONTAINER" \
    "$TASKIQ_CONTAINER" >/dev/null 2>&1 || true
docker volume rm "$TASKIQ_VOLUME" >/dev/null 2>&1 || true
docker volume create "$TASKIQ_VOLUME" >/dev/null

# Docker reallocates an anonymous host port after container restart. Reserve three
# distinct ports up front so the Redis restart checks keep a stable endpoint.
read -r postgres_port cache_port taskiq_port < <(
    uv run python -c '
import socket
sockets = [socket.socket() for _ in range(3)]
for sock in sockets:
    sock.bind(("127.0.0.1", 0))
print(*(sock.getsockname()[1] for sock in sockets))
'
)

docker run -d \
    --name "$POSTGRES_CONTAINER" \
    -e POSTGRES_USER=fault \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB=fault \
    -p "127.0.0.1:${postgres_port}:5432" \
    pgvector/pgvector:0.8.2-pg17-bookworm >/dev/null

docker run -d \
    --name "$CACHE_CONTAINER" \
    -p "127.0.0.1:${cache_port}:6379" \
    redis:7.4.9-alpine \
    redis-server \
    --requirepass "$REDIS_PASSWORD" \
    --maxmemory 64mb \
    --maxmemory-policy allkeys-lru >/dev/null

docker run -d \
    --name "$TASKIQ_CONTAINER" \
    --mount "type=volume,src=$TASKIQ_VOLUME,dst=/data" \
    -p "127.0.0.1:${taskiq_port}:6379" \
    redis:7.4.9-alpine \
    redis-server \
    --requirepass "$REDIS_PASSWORD" \
    --maxmemory 64mb \
    --maxmemory-policy noeviction \
    --appendonly yes \
    --appendfsync everysec >/dev/null

wait_for_postgres
wait_for_redis "$CACHE_CONTAINER"
wait_for_redis "$TASKIQ_CONTAINER"

export APP_ENV=test
export SECRET_KEY="fault-matrix-secret-key-at-least-32-characters"
export POSTGRES_SSL_MODE=disable
export DATABASE_URL="postgresql+asyncpg://fault:${POSTGRES_PASSWORD}@127.0.0.1:${postgres_port}/fault"
export TEST_DATABASE_URL="$DATABASE_URL"
export REDIS_PASSWORD
export REDIS_URL="redis://:${REDIS_PASSWORD}@127.0.0.1:${cache_port}/0"
export TEST_REDIS_URL="$REDIS_URL"
export TASKIQ_REDIS_URL="redis://:${REDIS_PASSWORD}@127.0.0.1:${taskiq_port}/0"
export TEST_TASKIQ_REDIS_URL="$TASKIQ_REDIS_URL"
export DEWFLOW_TEST_PROFILE=local
export T1_4_FAULT_MATRIX=1
export T1_4_FAULT_CACHE_CONTAINER="$CACHE_CONTAINER"
export T1_4_FAULT_TASKIQ_CONTAINER="$TASKIQ_CONTAINER"

log_section "Migrating disposable PostgreSQL"
uv run alembic upgrade head

log_section "Running T1-4 fault matrix"
uv run pytest -q -n 0 tests/integration/test_durable_task_fault_matrix.py

log_section "T1-4 fault matrix passed"
