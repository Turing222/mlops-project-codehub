#!/usr/bin/env bash
set -euo pipefail

client="${1:-codex}"

case "$client" in
  codex|claude-code)
    ;;
  *)
    printf 'usage: %s {codex|claude-code}\n' "$0" >&2
    exit 2
    ;;
esac

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"

cd "$repo_root"

exec serena start-mcp-server \
  --context="$client" \
  --project "$repo_root" \
  --mode no-memories \
  --enable-web-dashboard false \
  --open-web-dashboard false
