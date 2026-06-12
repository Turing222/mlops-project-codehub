#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_deploy_env_file
log_section "Preparing local production rehearsal secret files"

ensure_deploy_secret_files

write_local_s3_secret_if_empty() {
    local file_env_name="$1"
    local value="$2"
    local secret_path="${!file_env_name}"

    if [[ -s "$secret_path" ]]; then
        chmod_deploy_secret_file "$secret_path"
        return
    fi

    (
        umask 077
        printf '%s\n' "$value" >"$secret_path"
        chmod_deploy_secret_file "$secret_path"
    )
    log_info "Wrote local S3 rehearsal secret: $secret_path"
}

write_local_s3_secret_if_empty "DEPLOY_S3_ACCESS_KEY_ID_FILE" "minioadmin"
write_local_s3_secret_if_empty "DEPLOY_S3_SECRET_ACCESS_KEY_FILE" "minioadmin"

log_info "Local production rehearsal secret files are ready under ${DEPLOY_SECRET_DIR}"
