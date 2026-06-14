#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd curl

# The deploy env file is optional here: Pages release checks may run from any
# machine with DEPLOY_FRONTEND_BASE_URL / DEPLOY_BASE_URL exported directly.
if [[ -f "$(resolve_project_path "$DEPLOY_ENV_FILE")" ]]; then
    load_deploy_env
fi

frontend_origin="${DEPLOY_FRONTEND_BASE_URL%/}"
api_origin="${DEPLOY_BASE_URL%/}"

if [[ -z "$frontend_origin" ]]; then
    log_error "DEPLOY_FRONTEND_BASE_URL is required (the public Pages origin, e.g. https://app.example.com)"
    log_info "Run: make verify-pages DEPLOY_FRONTEND_BASE_URL=https://app.example.com DEPLOY_BASE_URL=https://api.example.com"
    exit 1
fi

if [[ -z "$api_origin" || "$api_origin" == "http://localhost" ]]; then
    log_error "DEPLOY_BASE_URL must point at the public API origin (e.g. https://api.example.com)"
    log_info "For local Compose verification use 'make deploy-ec2-verify' instead"
    exit 1
fi

failures=0

check_fail() {
    failures=$((failures + 1))
    log_error "$1"
}

http_status() {
    curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 30 "$@" || true
}

response_headers() {
    curl -sSI --connect-timeout 5 --max-time 30 "$@" 2>/dev/null | tr -d '\r' || true
}

log_section "Running Cloudflare Pages release checks"
log_info "Frontend origin: ${frontend_origin}"
log_info "API origin: ${api_origin}"

log_section "1/7 Frontend healthz"
url="${frontend_origin}${DEPLOY_FRONTEND_HEALTH_PATH}"
status="$(http_status "$url")"
if [[ "$status" == "200" ]]; then
    log_info "OK: GET ${url} -> ${status}"
else
    check_fail "GET ${url} returned ${status}, expected 200"
fi

log_section "2/7 Frontend index"
status="$(http_status "${frontend_origin}/")"
if [[ "$status" == "200" ]]; then
    log_info "OK: GET ${frontend_origin}/ -> ${status}"
else
    check_fail "GET ${frontend_origin}/ returned ${status}, expected 200"
fi

log_section "3/7 Frontend security headers"
headers="$(response_headers "${frontend_origin}/")"
if ! grep -qi '^x-content-type-options: *nosniff' <<<"$headers"; then
    check_fail "Missing 'X-Content-Type-Options: nosniff' on ${frontend_origin}/ (public/_headers not applied?)"
else
    log_info "OK: X-Content-Type-Options present"
fi
csp_line="$(grep -i '^content-security-policy-report-only:' <<<"$headers" || true)"
expected_report_uri="${api_origin}/api/v1/csp/reports"
if [[ -z "$csp_line" ]]; then
    check_fail "Missing Content-Security-Policy-Report-Only header (build ran without VITE_API_BASE_URL?)"
else
    if [[ "$csp_line" == *"report-uri ${expected_report_uri}"* ]]; then
        log_info "OK: CSP report-uri points at ${expected_report_uri}"
    else
        check_fail "CSP report-uri does not point at ${expected_report_uri}"
    fi
    if [[ "$csp_line" == *"connect-src 'self' ${api_origin}"* ]]; then
        log_info "OK: CSP connect-src allows ${api_origin}"
    else
        check_fail "CSP connect-src does not allow ${api_origin}"
    fi
fi

log_section "4/7 API liveness"
url="${api_origin}${DEPLOY_API_LIVE_PATH}"
status="$(http_status "$url")"
if [[ "$status" == "200" ]]; then
    log_info "OK: GET ${url} -> ${status}"
else
    check_fail "GET ${url} returned ${status}, expected 200"
fi

log_section "5/7 CORS preflight"
allow_origin="$(
    response_headers -X OPTIONS \
        -H "Origin: ${frontend_origin}" \
        -H "Access-Control-Request-Method: POST" \
        "${api_origin}/api/v1/telemetry/errors" \
        | grep -i '^access-control-allow-origin:' \
        | awk '{print $2}' || true
)"
if [[ "$allow_origin" == "$frontend_origin" || "$allow_origin" == "*" ]]; then
    log_info "OK: Access-Control-Allow-Origin = ${allow_origin}"
else
    check_fail "CORS preflight did not allow ${frontend_origin} (got '${allow_origin:-<none>}'); check BACKEND_CORS_ORIGINS"
fi

# Checks 6 and 7 POST an intentionally invalid '{}' body: 422 proves the origin
# guard accepted the Pages origin without logging a fake telemetry/CSP event.
# 204 still proves the origin guard, but means the endpoint stored the empty
# body (a blank event may have been recorded), so it warns instead of passing.
log_section "6/7 Telemetry origin guard"
status="$(
    http_status -X POST \
        -H "Origin: ${frontend_origin}" \
        -H 'Content-Type: application/json' \
        -d '{}' \
        "${api_origin}/api/v1/telemetry/errors"
)"
if [[ "$status" == "422" ]]; then
    log_info "OK: POST /api/v1/telemetry/errors -> ${status} (origin accepted, invalid body rejected)"
elif [[ "$status" == "204" ]]; then
    log_warn "POST /api/v1/telemetry/errors -> 204: origin accepted, but the endpoint stored an empty event (expected 422; check backend validation)"
else
    check_fail "POST /api/v1/telemetry/errors returned ${status}; 403 means the telemetry origin allowlist is missing ${frontend_origin}"
fi

log_section "7/7 CSP report sink"
status="$(
    http_status -X POST \
        -H "Origin: ${frontend_origin}" \
        -H 'Content-Type: application/json' \
        -d '{}' \
        "${api_origin}/api/v1/csp/reports"
)"
if [[ "$status" == "422" ]]; then
    log_info "OK: POST /api/v1/csp/reports -> ${status} (origin accepted, invalid body rejected)"
elif [[ "$status" == "204" ]]; then
    log_warn "POST /api/v1/csp/reports -> 204: origin accepted, but the endpoint stored an empty report (expected 422; check backend validation)"
else
    check_fail "POST /api/v1/csp/reports returned ${status}; 403 means the origin allowlist is missing ${frontend_origin}, 404 means the route is not deployed"
fi

log_section "Manual follow-up"
log_info "SSE streaming needs a logged-in session and stays manual:"
log_info "verify /api/v1/chat/query_stream emits incremental output via ${api_origin} (see docs/platform/frontend-delivery-and-edge-responsibilities.md)"

if (( failures > 0 )); then
    log_error "verify-pages failed: ${failures} check(s) failed"
    exit 1
fi

log_info "All Cloudflare Pages release checks passed"
