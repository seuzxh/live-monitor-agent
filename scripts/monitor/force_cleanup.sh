#!/usr/bin/env bash
# 15:20 兜底回收（spec 附录 A）：确保盯盘相关进程全部退出，防止次日 cron 拉起时重复
# 保守策略：只杀明确属于本项目 monitor 的进程
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="${MONITOR_RUNTIME_DIR:-$PROJECT_ROOT/runtime}"
LOG="$RUNTIME_DIR/logs/cleanup.log"
mkdir -p "$RUNTIME_DIR/logs"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# 1) 按 PID 文件杀（最精确）
if [ -f "$RUNTIME_DIR/monitor.pid" ]; then
  PID=$(cat "$RUNTIME_DIR/monitor.pid" 2>/dev/null || true)
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    sleep 2
    kill -9 "$PID" 2>/dev/null || true
    log "killed monitor pid=$PID"
  fi
  rm -f "$RUNTIME_DIR/monitor.pid"
fi

# 2) 按命令行模式杀残留的 traecli exec 盯盘会话（匹配本项目工作目录，避免误伤）
pkill -f "traecli exec.*live-monitor" 2>/dev/null && log "pkilled traecli exec live-monitor" || true
pkill -f "watchdog.py.*$PROJECT_ROOT" 2>/dev/null && log "pkilled watchdog" || true

# 3) 杀无头 Chromium（profile 指向本项目目录的）
pkill -f "chromium.*$RUNTIME_DIR/browser-profile" 2>/dev/null && log "pkilled chromium" || true

log "cleanup done"
