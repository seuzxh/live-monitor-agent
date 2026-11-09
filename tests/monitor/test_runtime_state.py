#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""runtime_state 模块测试（stdlib unittest，无第三方依赖）。"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "monitor" / "core"))

from runtime_state import RuntimeState, VALID, EXPIRED  # noqa: E402


class TestAuthStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rs = RuntimeState(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_valid(self):
        self.assertEqual(self.rs.auth_status, VALID)

    def test_mark_expired_and_reset(self):
        self.rs.mark_expired("测试失效")
        self.assertEqual(self.rs.auth_status, EXPIRED)
        self.assertEqual(self.rs.get("auth_expire_reason"), "测试失效")
        self.rs.reset_valid("辅助登录")
        self.assertEqual(self.rs.auth_status, VALID)
        self.assertEqual(self.rs.get("auth_valid_source"), "辅助登录")

    def test_history_appended(self):
        self.rs.append_auth_history("expired", "检测到登录页")
        self.rs.reset_valid("cookie_sop")
        lines = Path(self.rs.auth_history_file).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)


class TestHeartbeat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rs = RuntimeState(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_heartbeat_returns_negative(self):
        self.assertEqual(self.rs.heartbeat_age(), -1.0)

    def test_fresh_heartbeat_age_small(self):
        self.rs.touch_heartbeat()
        self.assertLess(self.rs.heartbeat_age(), 5.0)

    def test_stale_heartbeat(self):
        self.rs.touch_heartbeat()
        stale = time.time() - 1200  # 20 分钟前
        Path(self.rs.heartbeat_file).write_text(str(stale), encoding="utf-8")
        self.assertGreater(self.rs.heartbeat_age(), 1200.0)


class TestCursorAndDedup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rs = RuntimeState(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cursor_monotonic(self):
        self.assertEqual(self.rs.msg_cursor, 0)
        self.rs.advance_cursor(15)
        self.assertEqual(self.rs.msg_cursor, 15)
        # 游标不回退：传更小的值应保持
        self.rs.advance_cursor(10)
        self.assertEqual(self.rs.msg_cursor, 15)
        self.rs.advance_cursor(20)
        self.assertEqual(self.rs.msg_cursor, 20)

    def test_push_dedup(self):
        self.assertFalse(self.rs.is_pushed("🎯 关注深中华二板"))
        self.rs.record_push("交易机会", "🎯 关注深中华二板")
        self.assertTrue(self.rs.is_pushed("🎯 关注深中华二板"))
        # 空白差异不影响哈希（strip 后相同）
        self.assertTrue(self.rs.is_pushed("  🎯 关注深中华二板  "))
        self.assertFalse(self.rs.is_pushed("🎯 关注深中华二板。"))

    def test_push_count(self):
        self.assertEqual(self.rs.today_push_count(), 0)
        self.rs.record_push("a", "消息1")
        self.rs.record_push("b", "消息2")
        self.assertEqual(self.rs.today_push_count(), 2)


class TestStatsAndPid(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rs = RuntimeState(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stats_bump(self):
        self.rs.bump_stat("polls")
        self.rs.bump_stat("polls")
        self.rs.bump_stat("mqtt_reconnects")
        self.assertEqual(self.rs.stats(), {"polls": 2, "mqtt_reconnects": 1})

    def test_pid_roundtrip(self):
        self.rs.write_pid(12345)
        self.assertEqual(self.rs.read_pid(), 12345)
        self.rs.clear_pid()
        self.assertIsNone(self.rs.read_pid())


class TestCorruptedState(unittest.TestCase):
    def test_corrupted_json_recovers(self):
        tmp = tempfile.TemporaryDirectory()
        rs = RuntimeState(tmp.name)
        rs.state_file.write_text("{broken json", encoding="utf-8")
        rs2 = RuntimeState(tmp.name)  # 重新加载应回退到空状态而不是抛异常
        self.assertEqual(rs2.auth_status, VALID)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
