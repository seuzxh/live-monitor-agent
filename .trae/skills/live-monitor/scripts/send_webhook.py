#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
群机器人 Webhook 推送脚本（live-monitor 技能专用）

支持两类 webhook（按地址自动分流）：
- 企业微信 qyapi.weixin.qq.com：markdown 消息
- 飞书     open.feishu.cn：post 富文本（Markdown 标题→卡片标题，其余按行转换）

用法：
    python3 send_webhook.py "推送内容(Markdown)"
    echo "内容" | python3 send_webhook.py        # 从标准输入读取
    python3 send_webhook.py -f content.md        # 从文件读取

Webhook 地址自动从同技能目录的 memory.md 解析，也可用环境变量 FUPANGE_LIVE_MONITOR_WEBHOOK 覆盖。
"""
import os
import re
import sys
import json
import hashlib
import urllib.request
from datetime import datetime
from pathlib import Path


def load_project_env() -> dict:
    """加载项目根 .env（KEY=VALUE，# 注释）。文件不存在返回空。"""
    env_path = Path(__file__).resolve().parents[4] / ".env"
    if not env_path.exists():
        return {}
    vals = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


def resolve_webhook_url() -> str:
    # 优先级：进程环境变量 > 项目 .env > memory.md（历史兼容）
    env_url = os.environ.get("FUPANGE_LIVE_MONITOR_WEBHOOK", "").strip()
    if env_url:
        return env_url
    proj = load_project_env()
    if proj.get("FUPANGE_LIVE_MONITOR_WEBHOOK"):
        return proj["FUPANGE_LIVE_MONITOR_WEBHOOK"]
    memory_path = Path(__file__).resolve().parent.parent / "memory.md"
    if memory_path.exists():
        text = memory_path.read_text(encoding="utf-8")
        m = re.search(
            r"https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[0-9a-f\-]+"
            r"|https://open\.feishu\.cn/open-apis/bot/v2/hook/[0-9a-f\-]+", text)
        if m:
            return m.group(0)
    sys.stderr.write("ERROR: 未找到 webhook 地址（检查 环境变量 FUPANGE_LIVE_MONITOR_WEBHOOK / 项目 .env / memory.md）\n")
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


CARD_COLORS = [
    ("🎯", "green"), ("⚠️", "red"), ("📊", "blue"), ("💡", "orange"),
    ("📰", "grey"), ("📋", "turquoise"), ("🔔", "violet"),
]


def md_to_feishu_post(md: str) -> dict:
    """Markdown → 飞书交互卡片：## 行做卡片标题（emoji 映射颜色），正文进 markdown 组件。

    卡片 markdown 组件原生支持 **粗体**、> 引用、- 列表；### 小节标题转粗体行。
    """
    lines = [l.rstrip() for l in md.strip().splitlines() if l.strip()]
    title, body = "", []
    for l in lines:
        if l.startswith("## ") and not title:
            title = l[3:].strip()
            continue
        if l.startswith("###"):  # 卡片 markdown 不支持标题层级 → 粗体行
            body.append("**" + l.lstrip("#").strip() + "**")
            continue
        body.append(l)
    color = "purple"
    for emoji, tpl in CARD_COLORS:
        if emoji in (title or ""):
            color = tpl
            break
    title = (title or "盯盘推送").strip("【】")
    content = "\n".join(body)
    return {"msg_type": "interactive",
            "card": {"header": {"template": color,
                                "title": {"tag": "plain_text", "content": title}},
                     "elements": [{"tag": "markdown", "content": content}]}}


def build_payload(content: str, url: str) -> dict:
    if "open.feishu.cn" in url:
        return md_to_feishu_post(content)
    return {"msgtype": "markdown", "markdown": {"content": content}}


def check_ok(result: dict, url: str) -> bool:
    if "open.feishu.cn" in url:
        # 飞书：新版 {"code":0,...}；旧版 {"StatusCode":0,"StatusMessage":"success"}
        return result.get("code") == 0 or result.get("StatusCode") == 0
    return result.get("errcode") == 0


def archive_push(content: str) -> None:
    """推送全文落盘 runtime/pushes/{日期}.jsonl（含内容哈希，供跨重启去重与本地档案）。

    runtime 目录解析：环境变量 MONITOR_RUNTIME_DIR 优先，否则按仓库布局推导
    （本文件位于 <根>/.trae/skills/live-monitor/scripts/）。失败静默（不影响推送主流程）。
    """
    try:
        rt = os.environ.get("MONITOR_RUNTIME_DIR") or str(
            Path(__file__).resolve().parents[4] / "runtime")
        pushes = Path(rt) / "pushes"
        pushes.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "title": next((l[3:].strip() for l in content.splitlines()
                           if l.startswith("## ")), "")[:60],
            "hash": hashlib.md5(re.sub(r"\s", "", content)[:300].encode()).hexdigest(),
            "content": content,
        }
        with (pushes / f"{datetime.now().strftime('%Y%m%d')}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def send(content: str, webhook_url: str = None) -> dict:
    content = content.strip()
    if not content:
        sys.stderr.write("ERROR: 推送内容为空\n")
        sys.exit(2)
    url = webhook_url or resolve_webhook_url()
    data = json.dumps(build_payload(content, url), ensure_ascii=False).encode("utf-8")
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
            print(f"Response: {body[:200]}")
            result = json.loads(body)
            if not check_ok(result, url):
                sys.exit(1)
            archive_push(content)
            return result
    except Exception as e:
        sys.stderr.write(f"ERROR: 推送失败: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    send(read_content())
