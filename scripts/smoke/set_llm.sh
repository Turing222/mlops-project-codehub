#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

PROVIDER="${1:-}"
EMBED_PROVIDER="${2:-}"

if [[ -z "$PROVIDER" ]]; then
    log_error "Usage: make set-llm PROVIDER=<llm_provider> [EMBED_PROVIDER=<embed_provider>]"
    log_error "       (or $0 <llm_provider> [embed_provider])"
    log_error ""
    log_error "Examples:"
    log_error "  make set-llm PROVIDER=mock                    # LLM=mock, EMBED unchanged"
    log_error "  make set-llm PROVIDER=gemini                  # LLM=gemini, EMBED unchanged"
    log_error "  make set-llm PROVIDER=bifrost MODEL_ROUTING=true  # LLM=bifrost_pro + routing tiers"
    log_error "  make set-llm PROVIDER=gemini EMBED_PROVIDER=google  # LLM=gemini, EMBED=google"
    log_error "  make set-llm PROVIDER=mock EMBED_PROVIDER=mock      # both mock"
    exit 1
fi

smoke_env_path="$(resolve_project_path "$SMOKE_ENV_FILE")"

update_env_smoke() {
    local key="$1"
    local value="$2"
    if [[ ! -f "$smoke_env_path" ]]; then
        log_error "Missing $smoke_env_path. Please run 'make env-smoke-prepare' first."
        exit 1
    fi
    if grep -q "^${key}=" "$smoke_env_path"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$smoke_env_path"
    else
        echo "${key}=${value}" >> "$smoke_env_path"
    fi
    log_info "Updated ${key}=${value} in $smoke_env_path"
}

secret_path_for_provider() {
    local provider="$1"
    local secret_file_var default_path

    if [[ "$provider" == "bifrost_encryption" ]]; then
        secret_file_var="SMOKE_BIFROST_ENCRYPTION_KEY_FILE"
        default_path="./secrets/smoke/bifrost_encryption_key.txt"
    else
        secret_file_var="SMOKE_${provider^^}_API_KEY_FILE"
        default_path="./secrets/smoke/${provider}_api_key.txt"
    fi

    resolve_project_path "$(smoke_env_value "$secret_file_var" "$default_path")"
}

configure_model_routing() {
    local enabled="${MODEL_ROUTING:-}"
    if [[ -z "$enabled" ]]; then
        return
    fi

    case "$enabled" in
        true|false) ;;
        *)
            log_error "MODEL_ROUTING must be true or false, got: $enabled"
            exit 1
            ;;
    esac

    log_warn "MODEL_ROUTING only configures route providers; enable-llm-model-routing is controlled by GrowthBook."
    if [[ "$enabled" == "false" ]]; then
        return
    fi

    update_env_smoke "LLM_PROVIDER" "${ROUTING_LLM_PROVIDER:-bifrost_pro}"
    update_env_smoke "LLM_MODEL_ROUTE_FAST_PROVIDER" "${FAST_PROVIDER:-bifrost_flash}"
    update_env_smoke "LLM_MODEL_ROUTE_BALANCED_PROVIDER" "${BALANCED_PROVIDER:-bifrost_pro}"
    update_env_smoke "LLM_MODEL_ROUTE_REASONING_PROVIDER" "${REASONING_PROVIDER:-bifrost_reasoner}"
    update_env_smoke "LLM_MODEL_ROUTE_MIN_CONFIDENCE" "${MIN_CONFIDENCE:-0.65}"
}

write_secret_for_provider() {
    local provider="$1"
    local key="$2"
    local secret_path secret_dir

    secret_path="$(secret_path_for_provider "$provider")"
    secret_dir="$(dirname "$secret_path")"

    mkdir -p "$secret_dir"

    local tmp
    tmp="$(mktemp -p "$secret_dir" tmp.XXXXXX)"
    (
        umask 077
        printf '%s' "$key" > "$tmp"
    )
    chmod 600 "$tmp"
    mv "$tmp" "$secret_path"

    log_info "API key securely written to $secret_path"
}

# --- LLM Provider ---
if [[ "$PROVIDER" == "mock" ]]; then
    if [[ "${MODEL_ROUTING:-}" == "true" ]]; then
        log_error "MODEL_ROUTING=true requires a non-mock provider."
        exit 1
    fi
    update_env_smoke "LLM_PROVIDER" "mock"
    update_env_smoke "RAG_PLANNER_PROVIDER" "mock"
    update_env_smoke "RAG_RERANK_PROVIDER" "mock"
    configure_model_routing
else
    KEY=""
    secret_provider="$(llm_secret_provider "$PROVIDER")"
    existing_secret="$(secret_path_for_provider "$secret_provider")"
    if [[ -f "$existing_secret" && -s "$existing_secret" ]]; then
        KEY="$(cat "$existing_secret")"
        log_info "Using existing API key from $existing_secret"
    elif [[ ! -t 0 ]]; then
        if ! read -r KEY; then
            log_error "Failed to read API key from stdin."
            exit 1
        fi
        if [[ -z "$KEY" ]]; then
            log_error "API key read from stdin is empty."
            exit 1
        fi
    else
        read -rsp "Enter API Key for LLM ${PROVIDER}: " KEY || true
        echo ""
        if [[ -z "$KEY" ]]; then
            log_error "API key cannot be empty."
            exit 1
        fi
    fi
    if [[ "$secret_provider" == "bifrost" && "$KEY" != sk-bf-* ]]; then
        log_error "Bifrost virtual keys must start with 'sk-bf-'."
        exit 1
    fi

    write_secret_for_provider "$secret_provider" "$KEY"
    if [[ "${MODEL_ROUTING:-}" == "true" ]]; then
        configure_model_routing
    else
        update_env_smoke "LLM_PROVIDER" "$PROVIDER"
        configure_model_routing
    fi

    if [[ "$secret_provider" == "bifrost" ]]; then
        BIFROST_ENC_KEY=""
        existing_enc_secret="$(secret_path_for_provider "bifrost_encryption")"
        if [[ -f "$existing_enc_secret" && -s "$existing_enc_secret" ]]; then
            BIFROST_ENC_KEY="$(cat "$existing_enc_secret")"
            log_info "Using existing Bifrost encryption key from $existing_enc_secret"
        elif [[ ! -t 0 ]]; then
            read -r BIFROST_ENC_KEY || true
        else
            read -rsp "Enter Bifrost Encryption Key: " BIFROST_ENC_KEY || true
            echo ""
        fi
        if [[ -n "$BIFROST_ENC_KEY" ]]; then
            write_secret_for_provider "bifrost_encryption" "$BIFROST_ENC_KEY"
        else
            log_warn "BIFROST_ENCRYPTION_KEY not set. Bifrost may fail to start."
        fi
    fi
fi

# --- Embed Provider ---
# Alias map: embed profile → base provider whose secret file is reused.
# Add entries here when an embed profile shares a key with another provider.
readonly EMBED_SECRET_ALIAS=(
    "bifrost_embedding:bifrost"
)

_resolve_embed_secret_provider() {
    local embed="$1" entry
    for entry in "${EMBED_SECRET_ALIAS[@]}"; do
        if [[ "${entry%%:*}" == "$embed" ]]; then
            echo "${entry##*:}"
            return
        fi
    done
    echo "$embed"
}

if [[ -n "$EMBED_PROVIDER" ]]; then
    if [[ "$EMBED_PROVIDER" == "mock" ]]; then
        update_env_smoke "RAG_EMBED_PROVIDER" "mock"
    else
        _secret_provider="$(_resolve_embed_secret_provider "$EMBED_PROVIDER")"
        EMBED_KEY=""
        existing_embed_secret="$(secret_path_for_provider "$_secret_provider")"
        if [[ -f "$existing_embed_secret" && -s "$existing_embed_secret" ]]; then
            EMBED_KEY="$(cat "$existing_embed_secret")"
            log_info "Using existing embed API key from $existing_embed_secret (alias: ${EMBED_PROVIDER} -> ${_secret_provider})"
        elif [[ ! -t 0 ]]; then
            if ! read -r EMBED_KEY; then
                log_error "Failed to read embed API key from stdin."
                exit 1
            fi
            if [[ -z "$EMBED_KEY" ]]; then
                log_error "Embed API key read from stdin is empty."
                exit 1
            fi
        else
            read -rsp "Enter API Key for Embed ${EMBED_PROVIDER}: " EMBED_KEY || true
            echo ""
            if [[ -z "$EMBED_KEY" ]]; then
                log_error "Embed API key cannot be empty."
                exit 1
            fi
        fi

        write_secret_for_provider "$_secret_provider" "$EMBED_KEY"
        update_env_smoke "RAG_EMBED_PROVIDER" "$EMBED_PROVIDER"
    fi
fi
