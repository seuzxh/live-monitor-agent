#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书 bot 收图管线：补齐 companion 不转译图片的缺口。

链路：轮询 ~/.trae/cli/sessions/ 下 rollout 日志 → 发现含 user.image 的
用户消息（lark_message 信封带 message_id）→ tenant token 调 IM API 下载
原图 → Doubao-Seed-2.1-Pro 识别 → 以引用回复发回飞书原消息下。

用法：nohup python3 scripts/lark/bot_image_pipeline.py >/dev/null 2>&1 &
运维收口 Makefile：make bot-image-start / stop / status。
状态：runtime/bot_image_state.json（已处理 message_id，防重）；
图片落 runtime/bot_images/；日志 runtime/logs/bot_image.log。
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent          # 直播智能体/
RUNTIME = ROOT / "runtime"
STATE_FILE = RUNTIME / "bot_image_state.json"
IMG_DIR = RUNTIME / "bot_images"
LOG_FILE = RUNTIME / "logs" / "bot_image.log"
PID_FILE = RUNTIME / "bot_image.pid"
SESSIONS_ROOT = Path.home() / ".trae" / "cli" / "sessions"
CRED_FILE = Path.home() / ".trae" / "lark" / "credentials.json"
FEISHU = "https://open.feishu.cn/open-apis"

POLL_SEC = 5
VISION_MODEL = "Doubao-Seed-2.1-Pro-0915"
VISION_PROMPT = ("这是用户在飞书里发给 bot 的图片（可能为K线/分时/板块表格/"
                 "盘面截图/聊天记录等）。用中文说明：图类型＋关键内容＋可见的"
                 "重要数值（价位/涨跌幅/名称等），150字内，不确定的明确说不确定。")


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%m-%d %H:%M:%S')} {msg}"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"processed": []}


def save_state(st: dict) -> None:
    st["processed"] = st["processed"][-500:]  # 只留最近 500 条防膨胀
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


_tenant_token = {"token": "", "expire": 0.0}


def tenant_token() -> str:
    """app cli_aa1c…（直播智能体专用应用）换 tenant_access_token，缓存至过期前 60s。"""
    if _tenant_token["token"] and time.time() < _tenant_token["expire"]:
        return _tenant_token["token"]
    cred = json.loads(CRED_FILE.read_text(encoding="utf-8"))
    req = urllib.request.Request(
        FEISHU + "/auth/v3/tenant_access_token/internal",
        data=json.dumps({"app_id": cred["app_id"],
                         "app_secret": cred["app_secret"]}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
    if d.get("code") != 0:
        raise RuntimeError(f"tenant_token 失败: {d.get('code')} {d.get('msg')}")
    _tenant_token["token"] = d["tenant_access_token"]
    _tenant_token["expire"] = time.time() + int(d.get("expire", 7200)) - 60
    return _tenant_token["token"]


def _api(path: str, *, method: str = "GET", body: dict | None = None,
         binary: bool = False):
    headers = {"Authorization": "Bearer " + tenant_token()}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(FEISHU + path, data=data,
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return raw if binary else json.loads(raw)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"IM API {path} HTTP {e.code}: {detail}")


def download_images(message_id: str) -> list[Path]:
    """按 message_id 取消息体里的 image_key 列表，逐张下载原图。"""
    d = _api(f"/im/v1/messages/{message_id}")
    if d.get("code") != 0:
        raise RuntimeError(f"取消息失败: {d.get('code')} {d.get('msg')}")
    # 消息体是嵌套 JSON 字符串，image_key 的引号在整体 dumps 后被转义（\"），两种形态都匹配
    keys = re.findall(r'image_key\\?"\s*:\s*\\?"([^"\\]+)', json.dumps(d))
    keys = [k for i, k in enumerate(keys) if k not in keys[:i]]
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for k in keys:
        raw = _api(f"/im/v1/messages/{message_id}/resources/{k}?type=image",
                   binary=True)
        p = IMG_DIR / f"{message_id}_{k[-12:]}.png"
        p.write_bytes(raw)
        paths.append(p)
    return paths


def vision_describe(img_path: Path) -> str:
    """Doubao 视觉识别（与 monitor_poll.vision_describe 同款：prompt 在前、-i 在后、-o 取干净输出）。"""
    out = IMG_DIR / f"vision_{img_path.stem}.txt"
    env = dict(os.environ)
    env["PATH"] = os.path.expanduser("~/.local/bin:") + env.get("PATH", "")
    cred = Path.home() / ".config/trae-cli/credentials.env"
    if cred.exists():  # traecli PAT 注入（与 llm_edit_and_push 同款）
        for line in cred.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    subprocess.run(
        ["traecli", "exec", VISION_PROMPT, "-i", str(img_path),
         "-m", VISION_MODEL, "--permission-mode", "bypass_permissions",
         "--skip-git-repo-check", "-o", str(out)],
        capture_output=True, text=True, timeout=240, cwd=str(ROOT),
        stdin=subprocess.DEVNULL, env=env)
    if out.exists() and out.read_text(encoding="utf-8").strip():
        return out.read_text(encoding="utf-8").strip()[:600]
    return "识别失败（视觉模型无输出）"


def reply_text(message_id: str, text: str) -> None:
    _api(f"/im/v1/messages/{message_id}/reply", method="POST",
         body={"msg_type": "text",
               "content": json.dumps({"text": text}, ensure_ascii=False)})


def scan_once(state: dict) -> None:
    """扫当天（含昨天夜里）rollout，找未处理的 user.image 用户消息。"""
    if not SESSIONS_ROOT.exists():
        return
    today = datetime.now()
    days = {(today.year, today.month, today.day),
            (today.year, today.month, today.day - 1)}  # 跨零点兜底
    for y, m, dd in days:
        day_dir = SESSIONS_ROOT / f"{y:04d}" / f"{m:02d}" / f"{dd:02d}"
        if not day_dir.is_dir():
            continue
        for f in sorted(day_dir.glob("rollout-*.jsonl")):
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for line in lines:
                if "user.image" not in line or "<lark_message>" not in line:
                    continue
                mid = re.search(r"<message_id>(om_[^<]+)</message_id>", line)
                if not mid:
                    continue
                message_id = mid.group(1)
                if message_id in state["processed"]:
                    continue
                state["processed"].append(message_id)
                save_state(state)
                try:
                    imgs = download_images(message_id)
                    if not imgs:
                        reply_text(message_id, "🖼 收到图片，但消息里没解析到图片资源。")
                        continue
                    parts = [vision_describe(p) for p in imgs]
                    reply_text(message_id,
                               "🖼 图片识别（Doubao）：" +
                               ("\n—\n".join(parts)))
                    log(f"OK {message_id} imgs={len(imgs)}")
                except Exception as e:
                    reply_text(message_id, f"🖼 图片识别失败：{e}")
                    log(f"FAIL {message_id} {e}")


def main() -> int:
    RUNTIME.mkdir(exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    log("bot 收图管线启动")
    state = load_state()
    while True:
        try:
            scan_once(state)
        except Exception as e:
            log(f"scan error: {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    sys.exit(main())
