#!/usr/bin/env bash
# Materialize the configured AWS runtime bundle before EC2 deploy checks.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

cd "$PROJECT_ROOT"
require_deploy_env_file
require_cmd uv

secret_source="$(deploy_control_env_value "DEPLOY_SECRET_SOURCE" "files")"
secret_id="$(
    deploy_control_env_value "DEPLOY_RUNTIME_SECRET_ID" "dewflow-prod-runtime"
)"
secret_dir="$(
    deploy_control_env_value "DEPLOY_SECRET_DIR" "/run/dewflow-secrets"
)"
region="$(deploy_control_env_value "DEPLOY_AWS_REGION" "us-west-2")"

if [[ "$secret_source" != "aws" ]]; then
    log_error "DEPLOY_SECRET_SOURCE must be aws to materialize Secrets Manager"
    exit 1
fi
if [[ "$secret_dir" != /* ]]; then
    log_error "AWS materialize target must be an absolute runtime path"
    exit 1
fi

uv run --frozen python scripts/deploy/secret_bundle.py materialize \
    --secret-id "$secret_id" \
    --directory "$secret_dir" \
    --region "$region"
