#!/usr/bin/env bash

# Stops the EC2 deploy stack.
#
# Plain `down` keeps named volumes intact. Set DEPLOY_CONFIRM_VOLUME_WIPE=yes
# (non-interactive) or =prompt (TTY ask) to also pass `-v` to docker compose;
# the legacy DEPLOY_DOWN_VOLUMES env var is ignored.

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd docker
require_deploy_env_file
load_deploy_env

log_section "Stopping EC2 deploy stack"

args=(down)

if [[ -n "${DEPLOY_DOWN_VOLUMES:-}" && -z "${DEPLOY_CONFIRM_VOLUME_WIPE:-}" ]]; then
    log_warn "DEPLOY_DOWN_VOLUMES is ignored; set DEPLOY_CONFIRM_VOLUME_WIPE=yes to wipe volumes"
fi

volume_wipe="${DEPLOY_CONFIRM_VOLUME_WIPE:-no}"
case "${volume_wipe,,}" in
    yes|1|true|on)
        log_warn "Volume wipe requested; this will destroy the following named volumes:"
        log_warn "  - prod_db_volume"
        log_warn "  - knowledge_files_volume"
        log_warn "  - bifrost_data_volume"
        args+=(-v)
        ;;
    prompt|interactive)
        log_warn "Volume wipe requested; this will destroy the following named volumes:"
        log_warn "  - prod_db_volume"
        log_warn "  - knowledge_files_volume"
        log_warn "  - bifrost_data_volume"
        if [[ -t 0 ]]; then
            read -r -p "Type 'yes' to continue: " reply
            if [[ "${reply}" != "yes" ]]; then
                log_info "Continuing without -v; volumes left intact"
            else
                args+=(-v)
            fi
        else
            log_warn "No TTY available for prompt; continuing without -v"
        fi
        ;;
    *)
        log_info "Keeping named volumes; pass DEPLOY_CONFIRM_VOLUME_WIPE=yes to wipe them"
        ;;
esac

compose_deploy "${args[@]}"
