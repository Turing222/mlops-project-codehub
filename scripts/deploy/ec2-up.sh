#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd docker
require_deploy_env_file

load_deploy_env

log_section "Starting EC2 deploy stack"

compose_deploy_pull_registry

if [[ "${DEPLOY_PULL_IMAGES:-false}" == "true" ]]; then
    log_info "Pulling all deploy images because DEPLOY_PULL_IMAGES=true"
    compose_deploy pull
else
    log_info "Skipping app image pull; set DEPLOY_PULL_IMAGES=true to pull DOCKER_IMAGE_NAME_* from registry"
fi

compose_deploy up -d
compose_deploy ps
