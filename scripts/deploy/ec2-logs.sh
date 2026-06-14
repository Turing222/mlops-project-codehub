#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd docker
require_deploy_env_file
load_deploy_env

log_section "Showing EC2 deploy logs"

if (( $# > 0 )); then
    compose_deploy logs --tail="$DEPLOY_LOG_TAIL" "$@"
else
    compose_deploy logs --tail="$DEPLOY_LOG_TAIL"
fi
