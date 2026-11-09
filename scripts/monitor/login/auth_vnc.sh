#!/usr/bin/env bash
# Cookie 续期 SOP 路径 B：服务器 noVNC 应急续期（spec FR-5）
# start: 启动 Xvfb + noVNC + 有头 Chromium（一次性令牌），用户在任意设备浏览器完成登录
# stop:  关闭全部组件并收紧端口
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RUNTIME_DIR="${MONITOR_RUNTIME_DIR:-$PROJECT_ROOT/runtime}"
STATE_DIR="$RUNTIME_DIR/vnc"
PID_FILE="$STATE_DIR/session.pid"
TOKEN_FILE="$STATE_DIR/token"
LOG="$RUNTIME_DIR/logs/vnc.log"
VNC_PORT=5900
NOVNC_PORT=6080

cmd_start() {
  mkdir -p "$STATE_DIR"
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "noVNC 会话已在运行（pid=$(cat "$PID_FILE")），先 stop 再 start"; exit 1
  fi

  # 一次性访问令牌（仅本次会话有效）
  TOKEN=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')
  echo "$TOKEN" > "$TOKEN_FILE"

  command -v Xvfb >/dev/null || { echo "缺少 Xvfb: sudo apt install xvfb"; exit 1; }

  # Xvfb 虚拟显示 :99
  Xvfb :99 -screen 0 1280x800x24 >>"$LOG" 2>&1 &
  XVFB_PID=$!

  # noVNC（自带 websockify 的发行包）
  if command -v novnc_proxy >/dev/null; then
    DISPLAY=:99 novnc_proxy --vnc localhost:$VNC_PORT --listen $NOVNC_PORT >>"$LOG" 2>&1 &
    NOVNC_PID=$!
  else
    echo "WARN: 未找到 novnc_proxy（sudo apt install novnc websockify），跳过 web 层，可用 VNC 客户端直连 $VNC_PORT"
    NOVNC_PID=""
  fi

  # 有头 Chromium 指向直播登录页（profile 用临时目录，避免污染线上 profile）
  DISPLAY=:99 chromium-browser --no-sandbox "https://zhibo.homeway.com.cn/11605/vips.html" >>"$LOG" 2>&1 &
  CHROME_PID=$!

  echo "$XVFB_PID $NOVNC_PID $CHROME_PID" | tr -s ' ' '\n' | grep -v '^$' > "$PID_FILE"

  echo "============================================================"
  echo "noVNC 应急登录已启动（令牌仅本次有效）"
  [ -n "$NOVNC_PID" ] && echo "Web 入口: http://<服务器IP>:$NOVNC_PORT/vnc.html?password=$TOKEN"
  echo "VNC 直连: <服务器IP>:$VNC_PORT（密码见 $TOKEN_FILE）"
  echo "请在浏览器中完成登录。完成后执行: make auth-vnc-stop && make auth-verify"
  echo "============================================================"
}

cmd_stop() {
  if [ ! -f "$PID_FILE" ]; then
    echo "无运行中的 noVNC 会话"; exit 0
  fi
  while read -r pid; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done < "$PID_FILE"
  sleep 1
  while read -r pid; do
    [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
  done < "$PID_FILE"
  rm -f "$PID_FILE" "$TOKEN_FILE"
  echo "noVNC 会话已关闭，端口已回收"
}

case "${1:-}" in
  start) cmd_start ;;
  stop)  cmd_stop ;;
  *) echo "用法: $0 {start|stop}"; exit 2 ;;
esac
