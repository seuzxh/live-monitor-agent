#!/usr/bin/env bash
# 【本地电脑】Cookie 续期 SOP 路径 A 第一步（spec FR-4）
# 有头模式打开直播页 → 人工完成手机号+验证码登录 → 检测登录成功 → 自动打包 profile
# 用法: auth_local_login.sh [profile输出目录]
set -eu

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PROFILE_OUT="${1:-$HOME/.hexun-monitor-profile}"
LIVE_URL="https://zhibo.homeway.com.cn/11605/vips.html"
PACK_SCRIPT="$(dirname "$0")/profile_pack.sh"

cat <<'EOF'
============================================================
和讯直播 本地登录（Cookie 续期 SOP 路径 A）
步骤：
  1. 稍后会打开有头浏览器并加载直播页
  2. 请人工完成：手机号 + 短信验证码 + 可能的滑块验证
  3. 登录成功（看到直播消息列表）后，回到此终端按回车
  4. 脚本自动检测登录态并打包 profile
============================================================
按回车开始（或 Ctrl-C 取消）...
EOF
read -r _

python3 - "$PROFILE_OUT" "$LIVE_URL" <<'PYEOF'
import sys, time
from pathlib import Path

profile_out, live_url = sys.argv[1], sys.argv[2]
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("ERROR: 本地未装 playwright。执行: pip install playwright && playwright install chromium")

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(profile_out, headless=False, no_viewport=True)
    page = ctx.new_page()
    page.goto(live_url)
    print("\n>>> 浏览器已打开，请完成登录。登录成功后回到这里按回车 <<<")
    input()
    # 检测登录成功：URL 在 vips 且消息容器有内容
    has_tel = page.locator("input[type=tel]").count() > 0
    msg_count = page.locator(".pointList.msglay").count()
    if has_tel or msg_count == 0:
        print("WARN: 未检测到登录态（可能未登录成功），仍将按当前状态打包。可通过 make auth-verify 验证。")
    else:
        print(f"OK: 登录态检测通过（消息数 {msg_count}）")
    ctx.close()
print("浏览器已关闭，开始打包...")
PYEOF

bash "$PACK_SCRIPT" "$PROFILE_OUT"
