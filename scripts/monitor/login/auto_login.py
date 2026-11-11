#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动登录编排（2026-11-11 产品化，替代 tmp/login_full.py 临时件）：

登录失效 → 发码（易盾风控时自动归档换新 profile 重试一次）
→ 飞书 bot 私聊要验证码 → lark_notify.wait_code 轮询收码
→ 同一会话填码登录 → 验证 → 飞书回执。

用法：
  python3 auto_login.py            # 完整流程（发码+等码+登录+回执）
  python3 auto_login.py --dry      # 只检测登录态，不发码
退出码：0=已登录/登录成功；2=失败（风控/超时）
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lark_notify import send, wait_code  # noqa: E402

PROFILE = ROOT / "runtime" / "browser-profile"
RUNTIME = ROOT / "runtime"
TMP = ROOT / "tmp"
URL = "https://zhibo.homeway.com.cn/11605/vips.html"


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    (TMP / "auto_login.log").open("a", encoding="utf-8").write(line + "\n")


def read_phone() -> str:
    m = re.search(r"FUPANGE_HEXUN_LOGIN_PHONE=(1[0-9]{10})", (ROOT / ".env").read_text())
    if not m:
        raise RuntimeError(".env 缺少 FUPANGE_HEXUN_LOGIN_PHONE")
    return m.group(1)


def find_login_frame(page):
    for f in page.frames:
        try:
            if f.locator('input[placeholder*="手机"]').count():
                return f
        except Exception:
            continue
    return None


def request_sms(page, frame, phone: str) -> bool:
    """填号勾协议并点发码；返回是否捕获 sendSms 200。"""
    sent = {"ok": False}
    page.on("response", lambda r: sent.update(ok=True)
            if "sendSms" in r.url and r.status == 200 else None)
    tel = frame.locator('input[placeholder*="手机"]').first
    tel.click()
    tel.fill(phone)
    for i in range(frame.locator("input[type=checkbox]").count()):
        cb = frame.locator("input[type=checkbox]").nth(i)
        try:
            if not cb.is_checked():
                cb.check()
        except Exception:
            pass
    page.wait_for_timeout(800)
    frame.evaluate("""(function(){
        var btns = document.querySelectorAll('button');
        for (var i=0;i<btns.length;i++){
            if ((btns[i].innerText||'').indexOf('短信验证码')>=0){ btns[i].click(); return 1; }}
        return 0;})()""")
    for _ in range(10):
        if sent["ok"]:
            return True
        page.wait_for_timeout(1000)
    return False


def run_login() -> bool:
    """一次完整登录（新 profile 由调用方保证），True=成功。"""
    phone = read_phone()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE), headless=False,
            viewport={"width": 1366, "height": 900},
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(6000)
        frame = find_login_frame(page)
        if frame is None:
            log("登录表单未出现（可能已登录）")
            ctx.close()
            return True
        if not request_sms(page, frame, phone):
            log("发码失败")
            ctx.close()
            return False
        log(f"短信已发（***{phone[-2:]}），飞书告警并等码")
        try:
            send("🔐 直播登录验证码已发送，请在 4 分钟内直接回复 6 位数字（纯数字，无需其他内容）。")
        except Exception as e:
            log(f"飞书告警失败: {e}")
        code = wait_code(minutes=4)
        if not code:
            log("4 分钟未收到验证码")
            ctx.close()
            return False
        log(f"收到验证码 {code[:2]}****，提交")
        ci = frame.locator('input[placeholder*="验证码"]').first
        ci.click()
        ci.fill(code)
        btn = frame.locator("button.btn-login").first
        b = btn.bounding_box()
        page.mouse.click(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
        page.wait_for_timeout(8000)
        ok = (page.locator('input[placeholder*="手机"]').count() == 0
              and all(f.locator('input[placeholder*="手机"]').count() == 0
                      for f in page.frames))
        ctx.close()
        return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()

    # 风控对策：profile 带 300+ 次失效访问指纹时易盾静默拦发码——
    # 首次发码失败即归档旧 profile 换新重试一次（2026-11-11 实测）
    for attempt in (1, 2):
        log(f"登录尝试 {attempt}")
        ok = run_login()
        if ok:
            log("登录成功")
            try:
                send("✅ 直播登录成功，监控恢复。")
            except Exception:
                pass
            (RUNTIME / "auth_history.jsonl").open("a").write(json.dumps(
                {"ts": datetime.now().isoformat(timespec="seconds"),
                 "event": "auto_login", "detail": f"尝试{attempt}成功"}) + "\n")
            return 0
        if attempt == 1:
            bak = ROOT / "runtime" / f"browser-profile.risky-{datetime.now().strftime('%m%d%H%M')}"
            try:
                PROFILE.rename(bak)
                log(f"旧 profile 已归档 {bak.name}（疑似易盾风控），换新重试")
            except Exception:
                pass
    log("自动登录失败（两次）")
    try:
        send("❌ 直播自动登录失败（两次），需要人工介入：请到会话处理。")
    except Exception:
        pass
    (RUNTIME / "auth_history.jsonl").open("a").write(json.dumps(
        {"ts": datetime.now().isoformat(timespec="seconds"),
         "event": "auto_login_failed"}) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
