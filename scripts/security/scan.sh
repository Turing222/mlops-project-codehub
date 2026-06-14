#!/usr/bin/env bash
# ============================================================================
# Security scan orchestrator.
#
# Usage:
#   bash scripts/security/scan.sh fast   # dependency audits only (~1 min)
#   bash scripts/security/scan.sh full   # deps + docker image trivy scans
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
source "$SCRIPT_DIR/../lib/common.sh"

MODE="${1:-fast}"

case "$MODE" in
    fast)
        bash "$SCRIPT_DIR/scan_deps.sh"
        ;;
    full)
        bash "$SCRIPT_DIR/scan_deps.sh"
        bash "$SCRIPT_DIR/scan_images.sh"
        ;;
    *)
        log_error "Unknown security scan mode: $MODE (expected: fast|full)"
        exit 1
        ;;
esac

log_section "Security scan ($MODE) passed"
