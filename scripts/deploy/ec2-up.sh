#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd docker
require_deploy_env_file

load_deploy_env

log_section "Starting EC2 deploy stack"

if [[ "${DEPLOY_PULL_IMAGES:-false}" == "true" ]]; then
    compose_deploy pull
else
    log_info "Skipping image pull because DEPLOY_PULL_IMAGES is not enabled"
fi

compose_deploy up -d
compose_deploy ps
