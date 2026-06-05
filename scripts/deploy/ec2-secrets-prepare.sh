#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_deploy_env_file
log_section "Preparing EC2 deploy secret files"

ensure_deploy_secret_files

log_info "EC2 deploy secret files are ready under ${DEPLOY_SECRET_DIR}"
