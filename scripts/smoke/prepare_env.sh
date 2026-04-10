#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

template_path="$(resolve_project_path "$SMOKE_ENV_TEMPLATE")"
smoke_env_path="$(resolve_project_path "$SMOKE_ENV_FILE")"

if [[ ! -f "$template_path" ]]; then
    log_error "Missing smoke env template: $template_path"
    exit 1
fi

if [[ "$template_path" == "$smoke_env_path" ]]; then
    log_error "Smoke env template and output file must be different"
    exit 1
fi

log_section "Preparing smoke environment file"

cp "$template_path" "$smoke_env_path"
printf '\nCURRENT_UID=%s\nCURRENT_GID=%s\n' "$(id -u)" "$(id -g)" >> "$smoke_env_path"

log_info "Smoke env written to $smoke_env_path"
log_info "Source template: $template_path"
