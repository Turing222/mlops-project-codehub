#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd curl
require_deploy_env_file
load_deploy_env

log_section "Waiting for EC2 deploy endpoints"

if [[ "${DEPLOY_CHECK_FRONTEND_HEALTH:-false}" == "true" ]]; then
    if ! wait_for_http_ok "${DEPLOY_FRONTEND_BASE_URL}${DEPLOY_FRONTEND_HEALTH_PATH}"; then
        print_deploy_logs
        exit 1
    fi
else
    log_info "Skipping frontend health check because DEPLOY_CHECK_FRONTEND_HEALTH is not enabled"
fi

if ! wait_for_http_ok "${DEPLOY_BASE_URL}${DEPLOY_API_LIVE_PATH}"; then
    print_deploy_logs
    exit 1
fi

if ! wait_for_http_ok "${DEPLOY_BASE_URL}${DEPLOY_API_READY_PATH}"; then
    print_deploy_logs
    exit 1
fi

log_info "Deploy endpoints are reachable"
