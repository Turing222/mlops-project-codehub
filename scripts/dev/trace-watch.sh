#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# trace-watch.sh — 实时追踪前后端联调日志
#
# 用法：
#   ./scripts/dev/trace-watch.sh              # tail 所有日志，按 trace_id 着色
#   ./scripts/dev/trace-watch.sh <trace_id>   # 只看指定 trace_id 的行
#   ./scripts/dev/trace-watch.sh stream       # 只看 stream:xxx 相关行（chat流式）
#
# 颜色说明：
#   蓝色  = API 进程日志（前端 → API 端）
#   黄色  = Worker 进程日志（后台生成端）
#   红色  = WARNING / ERROR
#   绿色  = INFO 成功路径（spent credits, checkin, success）
# ─────────────────────────────────────────────────────────────

FILTER="${1:-}"
COMPOSE_FILE="docker-compose.db.yml"
ENV_FILE=".env.smoke"

# ── ANSI 颜色 ─────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;36m'
GRAY='\033[0;90m'
BOLD='\033[1m'
RESET='\033[0m'

echo -e "${BOLD}==> 开始追踪日志 (Ctrl+C 退出)${RESET}"
if [[ -n "$FILTER" ]]; then
  echo -e "${BOLD}==> 过滤关键词: ${YELLOW}${FILTER}${RESET}"
fi
echo ""

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
  logs api task_worker --follow --no-log-prefix --timestamps 2>/dev/null \
| while IFS= read -r line; do
    # ── 跳过不匹配的行 ──────────────────────────────────────
    if [[ -n "$FILTER" && "$line" != *"$FILTER"* ]]; then
      continue
    fi

    # ── 来源着色：识别是 api 还是 worker ────────────────────
    if echo "$line" | grep -q '"logger":"backend.worker\|task_worker\|taskiq'; then
      PREFIX="${YELLOW}[worker]${RESET}"
    else
      PREFIX="${BLUE}[api]   ${RESET}"
    fi

    # ── 级别着色 ─────────────────────────────────────────────
    if echo "$line" | grep -qE '"level":"(ERROR|CRITICAL)"'; then
      COLOR="$RED"
    elif echo "$line" | grep -qE '"level":"WARNING"'; then
      COLOR="$YELLOW"
    elif echo "$line" | grep -qE 'spent|checkin|success|成功'; then
      COLOR="$GREEN"
    else
      COLOR="$RESET"
    fi

    # ── 提取关键字段 ──────────────────────────────────────────
    MSG=$(echo "$line" | python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
    msg   = d.get('message','')
    lvl   = d.get('level','')
    tid   = d.get('trace_id','')[:12] if d.get('trace_id') else ''
    ts    = d.get('timestamp','')[:19].replace('T',' ')
    mod   = d.get('logger','').split('.')[-1][:25]
    tid_s = f'[{tid}]' if tid else '        '
    print(f'{ts}  {tid_s:14s}  {mod:<25s}  {msg}')
except:
    print(sys.stdin.read())
" 2>/dev/null || echo "$line")

    echo -e "${PREFIX} ${COLOR}${MSG}${RESET}"
done
