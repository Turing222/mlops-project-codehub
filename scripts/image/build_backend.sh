#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd docker

log_section "Building backend image"
docker build -t "$DOCKER_IMAGE_NAME" .
