#!/usr/bin/env bash
# 交易日 09:05 预检（spec FR-1）
# ① traecli 登录态 ② user-data-dir 完整 ③ 网络连通 ④ 磁盘空间 ⑤ A股交易日判断
# 任一不过 → 企微告警并退出码 1，不启动盯盘
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="${MONITOR_RUNTIME_DIR:-$PROJECT_ROOT/runtime}"
MEMORY_FILE="$PROJECT_ROOT/.trae/skills/live-monitor/memory.md"
PROFILE_DIR="${HEXUN_PROFILE_DIR:-$PROJECT_ROOT/runtime/browser-profile}"
LOG_FILE="$RUNTIME_DIR/logs/preflight.log"

mkdir -p "$RUNTIME_DIR/logs"
log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE"; }

alert() {
  local msg="$1"
  python3 "$PROJECT_ROOT/.trae/skills/live-monitor/scripts/send_webhook.py" \
    "## ⚠️ 盯盘预检失败\n\n$msg" >/dev/null 2>&1 || true
}

fail() { log "FAIL: $1"; alert "$1"; exit 1; }
pass() { log "PASS: $1"; }

# ⑤ A股交易日判断（周末直接退出；工作日调节假日 API，失败时放行）
is_trading_day() {
  local dow
  dow=$(date +%u)  # 1=周一 ... 7=周日
  if [ "$dow" -ge 6 ]; then
    log "周末，非交易日"
    return 1
  fi
  # 调聚合节假日 API（失败或响应异常时保守放行：宁可误跑，不可漏跑）
  local today resp
  today=$(date +%Y-%m-%d)
  resp=$(curl -s --max-time 8 "https://timor.tech/api/holiday/info/$today" || true)
  if [ -z "$resp" ]; then
    log "节假日 API 不可达，按工作日放行"
    return 0
  fi
  # timor.tech: {"code":0,"holiday":null} 工作日; holiday 非 null 为节假日
  # 响应非 JSON（如 Cloudflare 挑战页）视为 API 异常，按工作日放行
  if ! echo "$resp" | grep -q '"holiday"'; then
    log "节假日 API 响应异常（非 JSON，前 40 字符: ${resp:0:40}），按工作日放行"
    return 0
  fi
  if echo "$resp" | grep -q '"holiday":null'; then
    return 0
  fi
  log "节假日 API 判定今日非交易日"
  return 1
}

log "===== preflight start ====="

is_trading_day || exit 0   # 非交易日静默退出（不告警）

# ① traecli 登录态（PAT 环境变量注入，兼容无 keyring 服务器）
CRED_FILE="$HOME/.config/trae-cli/credentials.env"
if command -v traecli >/dev/null 2>&1; then
  if [ -f "$CRED_FILE" ]; then
    set -a; . "$CRED_FILE"; set +a
  fi
  if timeout 30 traecli models >/dev/null 2>&1; then
    pass "traecli 登录态正常（PAT）"
  else
    fail "traecli PAT 登录失败，检查 $CRED_FILE 或重置令牌"
  fi
else
  fail "traecli 不在 PATH（export PATH=\$HOME/.local/bin:\$PATH）"
fi

# ② 浏览器 user-data-dir（允许首次不存在，仅告警不阻断——首次部署时由 SOP 路径 A 生成）
if [ -d "$PROFILE_DIR" ]; then
  if [ -f "$PROFILE_DIR/Cookies" ] || ls "$PROFILE_DIR"/Default/Cookies >/dev/null 2>&1; then
    pass "浏览器 profile 存在且含 Cookie"
  else
    log "WARN: $PROFILE_DIR 存在但未见 Cookie 文件（可能未登录过，启动时将走登录流程）"
  fi
else
  log "WARN: profile 目录不存在（首次部署？），启动时将自动创建: $PROFILE_DIR"
fi

# ③ 网络连通性
if curl -s -o /dev/null --max-time 10 "https://zhibo.homeway.com.cn"; then
  pass "和讯直播站可达"
else
  fail "无法访问 zhibo.homeway.com.cn，检查服务器网络/代理"
fi

# ④ 磁盘空间（>500MB）
avail_kb=$(df "$PROJECT_ROOT" | awk 'NR==2{print $4}')
if [ "${avail_kb:-0}" -gt 512000 ]; then
  pass "磁盘可用 $((avail_kb/1024))MB"
else
  fail "磁盘空间不足 500MB（可用 $((avail_kb/1024))MB），清理 logs/snapshots"
fi

# ⑥ 凭据配置完整性（手机号 + webhook）
#    首选：项目根 .env（FUPANGE_HEXUN_LOGIN_PHONE + FUPANGE_LIVE_MONITOR_WEBHOOK）；
#    兼容：memory.md 内嵌明文（旧方式，已弃用但可用）
ENV_FILE="$PROJECT_ROOT/.env"
env_ok=0
if [ -f "$ENV_FILE" ]; then
  if grep -qE "^FUPANGE_HEXUN_LOGIN_PHONE=1[0-9]{10}" "$ENV_FILE" && \
     grep -qE "^FUPANGE_LIVE_MONITOR_WEBHOOK=https://" "$ENV_FILE"; then
    pass ".env 凭据配置完整（手机号 + webhook）"
    env_ok=1
  fi
fi
if [ "$env_ok" -eq 0 ]; then
  if [ -f "$MEMORY_FILE" ] && \
     grep -qE "1[0-9]{10}" "$MEMORY_FILE" && \
     grep -qE "qyapi\.weixin\.qq\.com|open\.feishu\.cn/open-apis/bot" "$MEMORY_FILE"; then
    log "WARN: 走旧方式（memory.md 明文凭据），建议迁移到项目 .env（参考 README）"
    pass "memory.md 凭据可用（旧方式）"
  else
    fail "凭据缺失：请创建 $ENV_FILE（FUPANGE_HEXUN_LOGIN_PHONE=手机号、FUPANGE_LIVE_MONITOR_WEBHOOK=webhook地址，权限 600）"
  fi
fi

log "===== preflight all passed ====="
