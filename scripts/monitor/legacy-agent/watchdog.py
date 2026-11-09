#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
看门狗（spec FR-7 / NFR-2）

职责：
- 每 CHECK_INTERVAL 秒检查 runtime/heartbeat 年龄
- 心跳超时（默认 15 分钟）→ 按故障矩阵处理：
  L2：杀掉残留进程，自动重启 1 次（每日限 1 次自动重启）
  自动重启后再崩（10 分钟内再次超时）→ L3：告警，不再重启
- 告警节流：同类告警 ALERT_THROTTLE 秒内只发一次
- 自身结束条件：当前时间超过 END_HHMM（15:20 cron 兜底也会强杀）

设计要点：
- 告警通道通过 alert_func 注入（默认调 send_webhook.py），测试中替换为记录器
- 重启通过 restart_func 注入（默认调 launcher.main），测试中替换
- 纯标准库
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from runtime_state import RuntimeState, DEFAULT_RUNTIME_DIR  # noqa: E402

CHECK_INTERVAL = 300          # 5 分钟
HEARTBEAT_TIMEOUT = 900       # 15 分钟
RESTART_WINDOW = 600          # 自动重启后 10 分钟内再超时 = 升级 L3
ALERT_THROTTLE = 1800         # 同类告警 30 分钟一次
DEFAULT_END_HHMM = "15:20"
MAX_AUTO_RESTARTS_PER_DAY = 1

WEBHOOK_SCRIPT = Path(__file__).resolve().parent.parent.parent.parent / \
    ".trae" / "skills" / "live-monitor" / "scripts" / "send_webhook.py"


def now_hhmm() -> str:
    return datetime.now().strftime("%H:%M")


def send_alert(title: str, body: str) -> None:
    """默认告警通道：企业微信 webhook（markdown）。"""
    content = f"## ⚠️ 盯盘看门狗告警\n\n**{title}**\n\n{body}"
    try:
        subprocess.run(
            [sys.executable, str(WEBHOOK_SCRIPT), content],
            timeout=30, capture_output=True,
        )
    except Exception:
        # 告警失败不拖垮看门狗本体
        pass


def default_restart(runtime_dir: str) -> None:
    """默认重启动作：调启动器。"""
    launcher_path = Path(__file__).resolve().parent / "launcher.py"
    subprocess.Popen(
        [sys.executable, str(launcher_path), "--runtime-dir", runtime_dir],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


class Watchdog:
    def __init__(
        self,
        runtime_dir: str = str(DEFAULT_RUNTIME_DIR),
        check_interval: int = CHECK_INTERVAL,
        heartbeat_timeout: int = HEARTBEAT_TIMEOUT,
        restart_window: int = RESTART_WINDOW,
        alert_throttle: int = ALERT_THROTTLE,
        end_hhmm: str = DEFAULT_END_HHMM,
        alert_func=send_alert,
        restart_func=default_restart,
        sleep_func=time.sleep,
        clock=time.time,
    ):
        self.state = RuntimeState(runtime_dir, clock=clock)
        self.runtime_dir = Path(runtime_dir)
        self.check_interval = check_interval
        self.heartbeat_timeout = heartbeat_timeout
        self.restart_window = restart_window
        self.alert_throttle = alert_throttle
        self.end_hhmm = end_hhmm
        self.alert = alert_func
        self.restart = restart_func
        self.sleep = sleep_func
        self.clock = clock
        self._last_alert_at: dict[str, float] = {}
        self._last_restart_at: float = 0.0
        self.log_path = self.runtime_dir / "logs" / "watchdog.log"

    # ---------- 日志 ----------

    def log(self, msg: str) -> None:
        line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}\n"
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line)

    # ---------- 告警（带节流） ----------

    def throttled_alert(self, kind: str, title: str, body: str) -> bool:
        last = self._last_alert_at.get(kind, 0.0)
        if self.clock() - last < self.alert_throttle:
            return False
        self._last_alert_at[kind] = self.clock()
        self.alert(title, body)
        return True

    # ---------- 主循环 ----------

    def kill_stale_processes(self) -> None:
        """杀掉残留的 traecli / monitor 相关进程（保守匹配，只杀本项目）。"""
        pid = self.state.read_pid()
        if pid:
            try:
                import os
                os.kill(pid, 9)
                self.log(f"killed stale monitor pid={pid}")
            except (ProcessLookupError, PermissionError):
                pass
            self.state.clear_pid()

    def check_once(self) -> str:
        """执行一次检查，返回动作描述（便于测试断言）。"""
        age = self.state.heartbeat_age()
        if age < 0:
            # agent 尚未 touch 过心跳：启动初期宽限一个周期
            return "no-heartbeat-yet"
        if age <= self.heartbeat_timeout:
            return "healthy"

        # 心跳超时
        stats = self.state.stats()
        restarts_today = int(stats.get("watchdog_restarts", 0))

        # 刚自动重启过，10 分钟内又超时 → 升级 L3
        if self._last_restart_at and (self.clock() - self._last_restart_at) < self.restart_window:
            self.state.bump_stat("watchdog_l3_escalations")
            self.throttled_alert(
                "l3_escalation",
                "盯盘任务反复崩溃（L3）",
                "自动重启后 10 分钟内再次心跳超时，今日不再自动重启，请人工排查日志。",
            )
            self.log("L3 escalation: repeated failure after auto-restart")
            return "l3-escalated"

        if restarts_today >= MAX_AUTO_RESTARTS_PER_DAY:
            self.throttled_alert(
                "restart_quota_used",
                "盯盘自动重启次数已用完（L3）",
                f"今日已自动重启 {restarts_today} 次，请人工排查。",
            )
            self.log(f"L3: restart quota used ({restarts_today})")
            return "restart-quota-used"

        # L2：杀残留 + 自动重启 1 次
        self.kill_stale_processes()
        self.state.bump_stat("watchdog_restarts")
        self._last_restart_at = self.clock()
        self.throttled_alert(
            "auto_restart",
            "盯盘心跳超时，已自动重启（L2）",
            f"心跳超时 {int(age)} 秒，看门狗已自动重启盯盘任务。",
        )
        self.restart(str(self.runtime_dir))
        self.log(f"L2 auto-restart (age={int(age)}s)")
        return "auto-restarted"

    def run(self) -> None:
        self.log(f"watchdog started (check={self.check_interval}s, timeout={self.heartbeat_timeout}s)")
        while True:
            if now_hhmm() >= self.end_hhmm:
                self.log(f"past end time {self.end_hhmm}, watchdog exiting")
                return
            try:
                self.check_once()
            except Exception as e:  # 看门狗本体任何错误都不能让它静默死掉
                self.log(f"check error: {e!r}")
            self.sleep(self.check_interval)


def main() -> int:
    parser = argparse.ArgumentParser(description="盯盘看门狗")
    parser.add_argument("--runtime-dir", default=str(DEFAULT_RUNTIME_DIR))
    parser.add_argument("--check-interval", type=int, default=CHECK_INTERVAL)
    parser.add_argument("--heartbeat-timeout", type=int, default=HEARTBEAT_TIMEOUT)
    parser.add_argument("--end-hhmm", default=DEFAULT_END_HHMM)
    parser.add_argument("--once", action="store_true", help="只检查一次后退出（调试/cron 用）")
    args = parser.parse_args()

    wd = Watchdog(
        runtime_dir=args.runtime_dir,
        check_interval=args.check_interval,
        heartbeat_timeout=args.heartbeat_timeout,
        end_hhmm=args.end_hhmm,
    )
    if args.once:
        print(wd.check_once())
        return 0
    wd.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
