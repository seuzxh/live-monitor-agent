#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watchdog 测试：用假时钟/假告警/假重启验证故障矩阵行为。"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "monitor" / "legacy-agent"))

from runtime_state import RuntimeState  # noqa: E402
from watchdog import Watchdog  # noqa: E402


class FakeClock:
    def __init__(self):
        self.t = time.time()

    def __call__(self):
        return self.t

    def advance(self, seconds: float):
        self.t += seconds


class WatchdogTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.rs = RuntimeState(self.tmp.name, clock=self.clock)
        self.alerts = []
        self.restarts = []
        self.wd = Watchdog(
            runtime_dir=self.tmp.name,
            check_interval=1,
            heartbeat_timeout=900,
            restart_window=600,
            alert_throttle=1800,
            end_hhmm="23:59",
            alert_func=lambda title, body: self.alerts.append((title, body)),
            restart_func=lambda rt: self.restarts.append(rt),
            sleep_func=lambda s: None,
            clock=self.clock,
        )
        self.rs = self.wd.state  # 与看门狗共用同一实例，统计断言直接读

    def tearDown(self):
        self.tmp.cleanup()

    def stale_heartbeat(self, age_seconds: float = 1200):
        """写入一个 age_seconds 前的心跳。"""
        (Path(self.tmp.name) / "heartbeat").write_text(
            str(self.clock.t - age_seconds), encoding="utf-8")


class TestHealthy(WatchdogTestBase):
    def test_healthy_heartbeat_no_action(self):
        self.rs.touch_heartbeat()
        # 心跳写入用真实时间，但 clock 也是真实起点，年龄为 0
        self.assertEqual(self.wd.check_once(), "healthy")
        self.assertEqual(self.restarts, [])
        self.assertEqual(self.alerts, [])

    def test_no_heartbeat_yet_grace(self):
        self.assertEqual(self.wd.check_once(), "no-heartbeat-yet")
        self.assertEqual(self.restarts, [])


class TestAutoRestart(WatchdogTestBase):
    def test_stale_heartbeat_triggers_restart(self):
        self.stale_heartbeat(1200)  # 20 分钟未更新
        action = self.wd.check_once()
        self.assertEqual(action, "auto-restarted")
        self.assertEqual(len(self.restarts), 1)
        self.assertEqual(len(self.alerts), 1)
        self.assertEqual(self.rs.stats().get("watchdog_restarts"), 1)

    def test_restart_quota_only_once_per_day(self):
        # 第一次：自动重启
        self.stale_heartbeat(1200)
        self.wd.check_once()
        # 推进 30 分钟（超过告警节流），心跳再次超时
        self.clock.advance(1900)
        self.stale_heartbeat(1200)
        action = self.wd.check_once()
        self.assertEqual(action, "restart-quota-used")
        self.assertEqual(len(self.restarts), 1)  # 没有第二次重启

    def test_l3_escalation_within_restart_window(self):
        # 第一次超时 → 自动重启
        self.stale_heartbeat(1200)
        self.wd.check_once()
        self.assertEqual(len(self.restarts), 1)
        # 10 分钟内再次超时 → L3 升级
        self.clock.advance(60)
        self.stale_heartbeat(1200)
        action = self.wd.check_once()
        self.assertEqual(action, "l3-escalated")
        self.assertEqual(len(self.restarts), 1)  # 不再重启
        self.assertEqual(self.rs.stats().get("watchdog_l3_escalations"), 1)

    def test_alert_throttling(self):
        # 同 kind 的告警在节流窗口内只发一次
        self.stale_heartbeat(1200)
        self.wd.check_once()
        self.clock.advance(300)  # 5 分钟 < 30 分钟节流
        self.stale_heartbeat(1200)
        # 此时重启配额已用完，但 l3/restart-quota 告警也应被节流
        self.wd.check_once()
        # 统计：auto_restart 告警 1 条 + restart_quota 被节流或发出
        # 关键断言：auto_restart 类的告警只有 1 条
        auto_restart_alerts = [a for a in self.alerts if "自动重启（L2）" in a[0]]
        self.assertEqual(len(auto_restart_alerts), 1)


class TestKillStale(WatchdogTestBase):
    def test_clears_dead_pid(self):
        self.rs.write_pid(2 ** 22 - 1)  # 不存在的进程
        self.stale_heartbeat(1200)
        self.wd.check_once()
        self.assertIsNone(self.rs.read_pid())


if __name__ == "__main__":
    unittest.main()
