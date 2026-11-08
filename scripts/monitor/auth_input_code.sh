#!/usr/bin/env bash
# 辅助登录验证码回传（spec FR-3A）
# 用法: auth_input_code.sh <6位数字>
# 写入 runtime/sms_code.txt，agent 轮询此文件获取验证码
set -eu

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="${MONITOR_RUNTIME_DIR:-$PROJECT_ROOT/runtime}"
CODE_FILE="$RUNTIME_DIR/sms_code.txt"

if [ $# -lt 1 ]; then
  echo "用法: $0 <6位数字验证码>" >&2
  exit 2
fi

CODE="$1"
if ! [[ "$CODE" =~ ^[0-9]{6}$ ]]; then
  echo "ERROR: 验证码必须是 6 位数字，收到: '$CODE'" >&2
  exit 2
fi

mkdir -p "$RUNTIME_DIR"
printf '%s' "$CODE" > "$CODE_FILE"
echo "OK: 验证码已写入 $CODE_FILE，agent 将在 10 秒内读取"
