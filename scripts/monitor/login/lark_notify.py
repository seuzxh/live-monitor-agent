#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书 bot 收发模块（验证码人机接力用，2026-11-11）。

凭据：~/.config/trae-cli/lark.env（LARK_APP_ID/LARK_APP_SECRET，600）；
owner：~/.trae/lark/credentials.json 的 owner_open_id（扫码+ /pair 绑定的用户）。

纯标准库 REST：
- send(text)：tenant_access_token → IM 发私聊
- wait_code(minutes)：轮询与 owner 的 p2p 会话历史，找告警之后 owner 发来的
  6 位纯数字消息，返回验证码字符串
"""
import json
import re
import time
import urllib.request
from pathlib import Path

LARK_ENV = Path.home() / ".config/trae-cli/lark.env"
LARK_CRED = Path.home() / ".trae/lark/credentials.json"
BASE = "https://open.feishu.cn/open-apis"


def _load_env() -> tuple[str, str]:
    kv = {}
    for line in LARK_ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip()
    return kv["LARK_APP_ID"], kv["LARK_APP_SECRET"]


def _owner_id() -> str:
    return json.loads(LARK_CRED.read_text())["owner_open_id"]


def _token(app_id: str, app_secret: str) -> str:
    req = urllib.request.Request(
        f"{BASE}/auth/v3/tenant_access_token/internal",
        data=json.dumps({"app_id": app_id, "app_secret": app_secret}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
    if d.get("code") != 0:
        raise RuntimeError(f"token 失败: {d}")
    return d["tenant_access_token"]


def _api(token: str, method: str, path: str, payload=None, params: str = ""):
    url = f"{BASE}{path}" + (f"?{params}" if params else "")
    req = urllib.request.Request(url, method=method,
        data=json.dumps(payload).encode() if payload else None,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
    if d.get("code") != 0:
        raise RuntimeError(f"{path}: {d.get('code')} {d.get('msg')}")
    return d.get("data", {})


CHAT_CACHE = Path.home() / ".config/trae-cli/lark_chat_id"


def send(text: str) -> str:
    """发私聊给 owner，返回 message_id（并缓存 p2p chat_id 供 wait_code 用）。"""
    app_id, app_secret = _load_env()
    token = _token(app_id, app_secret)
    data = _api(token, "POST", "/im/v1/messages", {
        "receive_id": _owner_id(),
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False)},
        params="receive_id_type=open_id")
    chat_id = data.get("chat_id", "")
    if chat_id:
        CHAT_CACHE.write_text(chat_id)
    return data.get("message_id", "")


def _p2p_chat_id(token: str) -> str:
    """p2p 单聊不在 GET /im/v1/chats 列表（只列群）；优先用 send() 缓存的
    chat_id，否则发一条探测消息从响应反查。"""
    if CHAT_CACHE.exists():
        cid = CHAT_CACHE.read_text().strip()
        if cid.startswith("oc_"):
            return cid
    app_id, app_secret = _load_env()
    _token(app_id, app_secret)  # 探测消息由 send 自带 token
    send("（通道探测，无需回复）")
    if CHAT_CACHE.exists():
        return CHAT_CACHE.read_text().strip()
    raise RuntimeError("无法确定 p2p chat_id")


def wait_code(minutes: float = 4.0, poll_interval: int = 6) -> str | None:
    """轮询 p2p 会话，返回 start 之后 owner 发来的 6 位纯数字。"""
    app_id, app_secret = _load_env()
    token = _token(app_id, app_secret)
    chat_id = _p2p_chat_id(token)
    start_ms = int(time.time() * 1000)
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        try:
            data = _api(token, "GET", f"/im/v1/messages",
                        params=f"container_id={chat_id}&container_id_type=chat"
                               f"&page_size=20&sort_type=ByCreateTimeDesc")
            for item in data.get("items", []):
                if item.get("sender", {}).get("id") != _owner_id():
                    continue
                if int(item.get("create_time", "0") + "000") < start_ms:
                    continue  # 告警前的旧消息
                body = json.loads(item.get("body", {}).get("content", "{}"))
                text = (body.get("text") or "").strip()
                m = re.fullmatch(r"(\d{6})", text)
                if m:
                    return m.group(1)
        except Exception:
            pass
        time.sleep(poll_interval)
    return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "send":
        print(send(sys.argv[2]))
    else:
        print("用法: lark_notify.py send <文本> | （wait_code 供登录流程 import）")
