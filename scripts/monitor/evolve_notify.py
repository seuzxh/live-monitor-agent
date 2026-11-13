#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evolve 新提案飞书通知（2026-11-13）。

流程：evolve_cli proposals 列 pending → 对比已通知基线（runtime/evolve_notified.json）
→ 新提案逐条经飞书 bot 推给 owner（主题/风险/置信/变更要点 + apply 指引）
→ 记入基线防重推。用户在飞书回复「apply <id>」由 bot 会话（evolve-setup 技能）执行。

设计：只通知不自动应用（apply 铁律须用户确认）；拉取失败静默退出（cron 友好）。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/zxh/projects/14.fupange")
STATE = ROOT / "直播智能体/runtime/evolve_notified.json"
ENV = {**os.environ,
       "EVOLVE_CONNECTOR": "trae",
       "PATH": os.path.expanduser("~/.local/bin:") + os.environ.get("PATH", "")}

sys.path.insert(0, str(ROOT / "直播智能体/scripts/monitor/login"))
from lark_notify import send  # noqa: E402


def cli(*args: str) -> str:
    r = subprocess.run(["python3", "-m", "evolve_cli", *args],
                       capture_output=True, text=True, timeout=90,
                       env=ENV, cwd=str(ROOT))
    return r.stdout or ""


def main() -> int:
    try:
        out = cli("proposals")
    except Exception as e:
        print(f"proposals 拉取失败: {e}", file=sys.stderr)
        return 1
    pending = re.findall(
        r"(p_[0-9a-f]+)\s+risk=([\d.]+)\s+conf=([\d.]+)\s+\[pending\]\s+(\S[^\n]*)", out)
    state = json.loads(STATE.read_text()) if STATE.exists() else {"notified": []}
    seen = set(state["notified"])
    new = [p for p in pending if p[0] not in seen]
    if not new:
        print("无新 pending 提案")
        return 0

    sent = 0
    for pid, risk, conf, title in new:
        try:
            detail = cli("proposal", pid)
            m = re.search(r"after: ['\"]?(.+?)(?:\n\npreviews|\npreviews)", detail, re.S)
            after = (m.group(1)[:220] + "…") if m and len(m.group(1)) > 220 else (m.group(1) if m else "")
        except Exception:
            after = ""
        text = (f"📋 进化提案待决策 {pid}\n"
                f"主题：{title}\n风险 {risk} · 置信 {conf}\n"
                + (f"变更要点：{after}\n" if after else "")
                + f"\n回复「apply {pid}」应用；不回复视为放弃")
        try:
            send(text)
            sent += 1
        except Exception as e:
            print(f"send {pid} 失败: {e}", file=sys.stderr)
            continue  # 发送失败不记基线，下次重推
        seen.add(pid)
        state["notified"] = sorted(seen)
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False))
    print(f"新提案 {len(new)} 条，已推送 {sent} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
