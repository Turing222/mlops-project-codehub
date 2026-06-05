#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd docker
require_deploy_env_file
load_deploy_env

log_section "Stopping EC2 deploy stack"

args=(down)
if [[ "${DEPLOY_DOWN_VOLUMES:-false}" == "true" ]]; then
    args+=(-v)
fi

compose_deploy "${args[@]}"
