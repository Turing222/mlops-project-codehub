#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

log_section "Running preflight environment checks"

require_smoke_env_file
source "$(resolve_project_path "$SMOKE_ENV_FILE")"

check_provider_secret() {
    local provider="$1"
    local secret_file_var="SMOKE_${provider^^}_API_KEY_FILE"
    local default_path="./secrets/smoke/${provider}_api_key.txt"
    local secret_path
    
    secret_path="$(smoke_env_value "$secret_file_var" "$default_path")"
    secret_path="$(resolve_project_path "$secret_path")"
    
    if [[ ! -s "$secret_path" ]]; then
        log_error "Provider is set to '$provider' but secret file is empty or missing: $secret_path"
        log_error "Please run: make set-llm PROVIDER=$provider"
        exit 1
    fi
}

# 1. Check LLM_PROVIDER
if [[ "${LLM_PROVIDER:-mock}" != "mock" ]]; then
    base_provider="$(llm_secret_provider "$LLM_PROVIDER")"
    check_provider_secret "$base_provider"

    if [[ "$base_provider" == "bifrost" ]]; then
        enc_secret_path="$(resolve_project_path "$(smoke_env_value "SMOKE_BIFROST_ENCRYPTION_KEY_FILE" "./secrets/smoke/bifrost_encryption_key.txt")")"
        if [[ ! -s "$enc_secret_path" ]]; then
            log_warn "LLM_PROVIDER is 'bifrost' but BIFROST_ENCRYPTION_KEY secret file is empty or missing: $enc_secret_path"
            log_warn "Bifrost may fail to start. Run: make set-llm PROVIDER=bifrost"
        fi
    fi
fi

# 2. Check RAG_EMBED_PROVIDER
if [[ "${RAG_EMBED_PROVIDER:-mock}" != "mock" ]]; then
    embed_provider="${RAG_EMBED_PROVIDER}"

    # Alias map: embed profile → base provider whose secret file is reused.
    # Keep in sync with EMBED_SECRET_ALIAS in set_llm.sh.
    readonly CHECK_EMBED_SECRET_ALIAS=(
        "bifrost_embedding:bifrost"
        "qwen3-embedding:dashscope"
    )
    for entry in "${CHECK_EMBED_SECRET_ALIAS[@]}"; do
        if [[ "${entry%%:*}" == "$embed_provider" ]]; then
            embed_provider="${entry##*:}"
            break
        fi
    done

    check_provider_secret "$embed_provider"
fi

log_info "Environment preflight check passed."
