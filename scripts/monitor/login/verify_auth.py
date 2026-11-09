#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
登录态固定验证清单（spec FR-6）

5 项检查，全部通过才算登录恢复成功：
  ① 页面 URL 为 vips.html
  ② 不存在 input[type=tel]（无登录表单）
  ③ .pointList.msglay 取到非空消息列表
  ④ state.json 的 auth_status 改回 valid 并记录时间
  ⑤ auth_history.jsonl 追加续期记录

设计：
- run_checklist(facts, state) 为纯逻辑，接收"页面事实"字典，不依赖浏览器，可单测
- collect_facts_playwright() 仅在服务器上运行时用到 Playwright（延迟导入），
  采集页面事实后交给纯逻辑判定
- CLI 两种模式：
    --facts-file <json>   离线模式：从 JSON 读 facts（测试/调试）
    （默认）              在线模式：Playwright 无头采集
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from runtime_state import RuntimeState, DEFAULT_RUNTIME_DIR, VALID  # noqa: E402

LIVE_URL_FRAGMENT = "vips.html"
MSG_SELECTOR = ".pointList.msglay"
TEL_SELECTOR = "input[type=tel]"


def run_checklist(facts: dict, state: RuntimeState, source: str = "") -> dict:
    """执行 5 项验证清单。facts 键：url / has_tel_input / msg_count。返回逐项结果。"""
    checks = [
        {
            "id": 1,
            "name": "页面URL为vips.html",
            "pass": LIVE_URL_FRAGMENT in (facts.get("url") or ""),
        },
        {
            "id": 2,
            "name": "无登录表单(input[type=tel]不存在)",
            "pass": facts.get("has_tel_input") is False,
        },
        {
            "id": 3,
            "name": "消息容器非空",
            "pass": (facts.get("msg_count") or 0) > 0,
        },
    ]
    all_page_pass = all(c["pass"] for c in checks)

    # ④ 页面全过后才允许重置状态（避免用坏状态覆盖）
    if all_page_pass and state.auth_status != VALID:
        state.reset_valid(source)
    checks.append({
        "id": 4,
        "name": "auth_status重置为valid",
        "pass": state.auth_status == VALID,
    })

    if all_page_pass:
        state.append_auth_history("verify_pass", source)
    checks.append({
        "id": 5,
        "name": "续期历史已记录",
        "pass": all_page_pass,  # 与页面检查同生命周期
    })

    return {
        "all_pass": all(c["pass"] for c in checks),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "checks": checks,
    }


def collect_facts_playwright(user_data_dir: str, url: str,
                             timeout_ms: int = 20000) -> dict:
    """Playwright 无头采集页面事实（仅服务器运行时需要，延迟导入）。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.stderr.write("ERROR: playwright 未安装。执行: pip install playwright && playwright install chromium\n")
        sys.exit(2)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        if user_data_dir:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir, headless=True)
            browser.close()
            browser = None
            page = ctx.new_page()
        else:
            page = ctx.new_page()
        try:
            page.goto(url, timeout=timeout_ms)
            page.wait_for_timeout(3000)
            has_tel = page.locator(TEL_SELECTOR).count() > 0
            msg_count = page.locator(MSG_SELECTOR).count()
            return {"url": page.url, "has_tel_input": has_tel, "msg_count": msg_count}
        finally:
            if browser:
                browser.close()
            else:
                ctx.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="登录态验证清单（FR-6）")
    parser.add_argument("--runtime-dir", default=str(DEFAULT_RUNTIME_DIR))
    parser.add_argument("--facts-file", help="离线模式：从 JSON 文件读页面事实")
    parser.add_argument("--url", default="https://zhibo.homeway.com.cn/11605/vips.html")
    parser.add_argument("--user-data-dir", default="",
                        help="Chromium 用户数据目录（持久化 Cookie）")
    parser.add_argument("--source", default="cookie_sop", help="恢复来源标记")
    args = parser.parse_args()

    state = RuntimeState(args.runtime_dir)

    if args.facts_file:
        facts = json.loads(Path(args.facts_file).read_text(encoding="utf-8"))
    else:
        facts = collect_facts_playwright(args.user_data_dir, args.url)

    result = run_checklist(facts, state, source=args.source)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
