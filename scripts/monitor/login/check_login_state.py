#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""登录态真实检查（preflight 第②项升级，2026-11-11）：
打开直播页 → 检测登录表单与消息容器 → 输出 JSON。
退出码：0=已登录；3=未登录（Cookie 失效或风控）；1=页面异常。
用法：python3 check_login_state.py [--timeout 45]
"""
import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent
URL = "https://zhibo.homeway.com.cn/11605/vips.html"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()

    result = {"ok": False, "logged_in": False, "total": 0, "login_form": 0}
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(ROOT / "runtime" / "browser-profile"), headless=False,
                viewport={"width": 1280, "height": 800},
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(URL, wait_until="domcontentloaded", timeout=args.timeout * 1000)
            page.wait_for_timeout(6000)
            data = page.evaluate("""(function(){
              const msgs = document.querySelectorAll('.pointList.msglay');
              return JSON.stringify({total: msgs.length});})()""")
            login_form = page.locator('input[placeholder*="手机"]').count()
            for f in page.frames:
                try:
                    login_form += f.locator('input[placeholder*="手机"]').count()
                except Exception:
                    continue
            result.update(total=json.loads(data)["total"], login_form=login_form,
                          logged_in=login_form == 0)
            result["ok"] = True
            try:
                ctx.close()
            except Exception:
                pass
    except Exception as e:
        result["error"] = str(e)[:120]

    print(json.dumps(result, ensure_ascii=False))
    if not result["ok"]:
        return 1
    return 0 if result["logged_in"] else 3


if __name__ == "__main__":
    sys.exit(main())
