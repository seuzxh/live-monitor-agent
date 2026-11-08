#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盯盘运行时状态管理（live-monitor-agent 外壳层）

职责（对应 spec FR-2 / FR-8）：
- state.json：auth_status、消息游标 total、轮询统计、重启计数
- heartbeat：touch / 年龄检测（看门狗消费）
- pushes/{日期}.jsonl：推送记录 + 内容哈希去重
- auth_history.jsonl：登录/续期历史留痕

纯标准库实现（spec NFR-3）。
"""
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

VALID = "valid"
EXPIRED = "expired"

DEFAULT_RUNTIME_DIR = Path(__file__).resolve().parent.parent.parent / "runtime"


class RuntimeState:
    """盯盘运行时状态，所有读写均落盘到 runtime 目录。"""

    def __init__(self, runtime_dir: Path | str = DEFAULT_RUNTIME_DIR, clock=time.time):
        self.dir = Path(runtime_dir)
        self._clock = clock
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "pushes").mkdir(exist_ok=True)
        (self.dir / "snapshots").mkdir(exist_ok=True)
        (self.dir / "logs").mkdir(exist_ok=True)
        self.state_file = self.dir / "state.json"
        self.heartbeat_file = self.dir / "heartbeat"
        self.auth_history_file = self.dir / "auth_history.jsonl"
        self._state = self._load()

    # ---------- state.json ----------

    def _load(self) -> dict:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # 状态文件损坏时从空状态重新开始，避免外壳整体崩溃
                return {}
        return {}

    def _save(self) -> None:
        tmp = self.state_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def get(self, key: str, default=None):
        return self._state.get(key, default)

    def set(self, key: str, value) -> None:
        self._state[key] = value
        self._save()

    # ---------- 登录态（FR-3 / FR-6） ----------

    @property
    def auth_status(self) -> str:
        return self._state.get("auth_status", VALID)

    def mark_expired(self, reason: str = "") -> None:
        self._state["auth_status"] = EXPIRED
        self._state["auth_expired_at"] = datetime.now().isoformat(timespec="seconds")
        if reason:
            self._state["auth_expire_reason"] = reason
        self._save()

    def reset_valid(self, source: str = "") -> None:
        self._state["auth_status"] = VALID
        self._state["auth_valid_at"] = datetime.now().isoformat(timespec="seconds")
        if source:
            self._state["auth_valid_source"] = source
        self._save()
        self.append_auth_history("valid", source)

    def append_auth_history(self, event: str, detail: str = "") -> None:
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            "detail": detail,
        }
        with self.auth_history_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ---------- 心跳（FR-7 看门狗消费） ----------

    def touch_heartbeat(self) -> None:
        self.heartbeat_file.write_text(str(self._clock()), encoding="utf-8")

    def heartbeat_age(self) -> float:
        """返回心跳距今年秒数；无心跳文件返回 -1。"""
        try:
            ts = float(self.heartbeat_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return -1.0
        return self._clock() - ts

    # ---------- 消息游标（FR-8 防丢消息） ----------

    @property
    def msg_cursor(self) -> int:
        return int(self._state.get("msg_cursor_total", 0))

    def advance_cursor(self, total: int) -> None:
        """处理完一轮消息后落盘游标（先处理后落盘）。"""
        if total > self.msg_cursor:
            self._state["msg_cursor_total"] = total
            self._save()

    # ---------- 推送去重（FR-8） ----------

    @staticmethod
    def content_hash(text: str) -> str:
        return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()

    def _pushes_file(self) -> Path:
        today = datetime.now().strftime("%Y%m%d")
        return self.dir / "pushes" / f"{today}.jsonl"

    def is_pushed(self, text: str) -> bool:
        h = self.content_hash(text)
        pushes_file = self._pushes_file()
        if not pushes_file.exists():
            return False
        try:
            for line in pushes_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    if json.loads(line).get("hash") == h:
                        return True
                except json.JSONDecodeError:
                    continue
        except OSError:
            return False
        return False

    def record_push(self, category: str, text: str) -> dict:
        h = self.content_hash(text)
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "category": category,
            "hash": h,
        }
        with self._pushes_file().open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def today_push_count(self) -> int:
        pushes_file = self._pushes_file()
        if not pushes_file.exists():
            return 0
        return sum(1 for line in pushes_file.read_text(encoding="utf-8").splitlines() if line.strip())

    # ---------- 运行统计（FR-9 健康度报告） ----------

    def bump_stat(self, key: str, increment: int = 1) -> int:
        stats = self._state.setdefault("stats", {})
        stats[key] = int(stats.get(key, 0)) + increment
        self._save()
        return stats[key]

    def stats(self) -> dict:
        return dict(self._state.get("stats", {}))

    # ---------- PID（FR-2 启动器写入） ----------

    def write_pid(self, pid: int) -> None:
        (self.dir / "monitor.pid").write_text(str(pid), encoding="utf-8")

    def read_pid(self) -> int | None:
        try:
            return int((self.dir / "monitor.pid").read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def clear_pid(self) -> None:
        try:
            (self.dir / "monitor.pid").unlink()
        except OSError:
            pass
