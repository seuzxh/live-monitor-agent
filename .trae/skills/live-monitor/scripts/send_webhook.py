#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企业微信群机器人 Webhook 推送脚本（live-monitor 技能专用）

用法：
    python3 send_webhook.py "推送内容(Markdown)"
    echo "内容" | python3 send_webhook.py        # 从标准输入读取
    python3 send_webhook.py -f content.md        # 从文件读取

Webhook 地址自动从同技能目录的 memory.md 解析（正则匹配 qyapi.weixin.qq.com webhook URL），
也可用环境变量 LIVE_MONITOR_WEBHOOK 覆盖。
"""
import os
import re
import sys
import json
import urllib.request
from pathlib import Path


def resolve_webhook_url() -> str:
    # 1) 环境变量优先
    env_url = os.environ.get("LIVE_MONITOR_WEBHOOK", "").strip()
    if env_url:
        return env_url
    # 2) 从 memory.md 解析
    memory_path = Path(__file__).resolve().parent.parent / "memory.md"
    if memory_path.exists():
        text = memory_path.read_text(encoding="utf-8")
        m = re.search(r"https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[0-9a-f\-]+", text)
        if m:
            return m.group(0)
    sys.stderr.write("ERROR: 未找到 webhook 地址（memory.md 无 qyapi webhook URL，且未设 LIVE_MONITOR_WEBHOOK）\n")
    sys.exit(2)


def read_content() -> str:
    args = sys.argv[1:]
    if args and args[0] == "-f":
        if len(args) < 2:
            sys.stderr.write("ERROR: -f 需要指定文件路径\n")
            sys.exit(2)
        return Path(args[1]).read_text(encoding="utf-8")
    if args:
        return args[0]
    if not sys.stdin.isatty():
        return sys.stdin.read()
    sys.stderr.write("ERROR: 未提供推送内容\n")
    sys.exit(2)


def send(content: str, webhook_url: str = None) -> dict:
    content = content.strip()
    if not content:
        sys.stderr.write("ERROR: 推送内容为空\n")
        sys.exit(2)
    url = webhook_url or resolve_webhook_url()
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            print(f"Status: {resp.status}")
            print(f"Response: {body}")
            result = json.loads(body)
            if result.get("errcode") != 0:
                sys.exit(1)
            return result
    except Exception as e:
        sys.stderr.write(f"ERROR: 推送失败: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    send(read_content())
