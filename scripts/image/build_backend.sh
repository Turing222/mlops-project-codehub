#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd docker

log_section "Building web image"
docker build --target web -t "${DOCKER_IMAGE_NAME_WEB:?missing DOCKER_IMAGE_NAME_WEB (build via make image-build or image-build-release)}" .

log_section "Building worker image"
docker build --target worker -t "${DOCKER_IMAGE_NAME_AI:?missing DOCKER_IMAGE_NAME_AI (build via make image-build or image-build-release)}" .
