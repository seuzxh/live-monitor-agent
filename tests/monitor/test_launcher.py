#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""launcher 模块测试。traecli 不在测试环境中存在，通过 mock subprocess 验证行为。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "monitor"))

import launcher  # noqa: E402
from runtime_state import RuntimeState, EXPIRED  # noqa: E402


class TestPidAlive(unittest.TestCase):
    def test_current_process_alive(self):
        import os
        self.assertTrue(launcher.pid_alive(os.getpid()))

    def test_nonexistent_pid_dead(self):
        # 找一个几乎必然不存在的 PID
        self.assertFalse(launcher.pid_alive(2 ** 22 - 1))


class TestBuildCommand(unittest.TestCase):
    def test_command_shape(self):
        cmd = launcher.build_command()
        self.assertEqual(cmd[0], "traecli")
        self.assertEqual(cmd[1], "exec")
        self.assertIn("--ask-for-approval", cmd)
        self.assertIn("never", cmd)
        # prompt 在末尾，且包含盯盘关键词
        self.assertIn("live-monitor", cmd[-1])
        self.assertIn("盯盘", cmd[-1])


class TestMainFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rs = RuntimeState(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _run_main(self):
        with mock.patch.object(launcher, "build_command", return_value=["echo", "stub"]), \
             mock.patch.object(sys, "argv", ["launcher.py", "--runtime-dir", self.tmp.name]):
            return launcher.main()

    def test_expired_skips_start(self):
        self.rs.mark_expired("测试")
        rc = self._run_main()
        self.assertEqual(rc, launcher.EXIT_OK)
        self.assertIsNone(self.rs.read_pid())  # 没有启动，PID 未写入

    def test_duplicate_start_rejected(self):
        self.rs.write_pid(2 ** 22 - 1)  # 不存在的 PID，先跑一次写入有效 PID 的场景
        # 先用真实存活 PID 模拟已在运行
        import os
        self.rs.write_pid(os.getpid())
        rc = self._run_main()
        self.assertEqual(rc, launcher.EXIT_OK)

    def test_start_writes_pid_and_heartbeat(self):
        rc = self._run_main()
        self.assertEqual(rc, launcher.EXIT_OK)
        pid = self.rs.read_pid()
        self.assertIsNotNone(pid)
        self.assertGreaterEqual(self.rs.heartbeat_age(), 0.0)
        # 日志文件有启动记录
        logs = list((Path(self.tmp.name) / "logs").glob("*.log"))
        self.assertTrue(logs)
        self.assertIn("启动盯盘", logs[0].read_text(encoding="utf-8"))

    def test_dry_run_no_pid(self):
        with mock.patch.object(launcher, "build_command", return_value=["echo", "stub"]), \
             mock.patch.object(sys, "argv",
                               ["launcher.py", "--runtime-dir", self.tmp.name, "--dry-run"]):
            rc = launcher.main()
        self.assertEqual(rc, launcher.EXIT_OK)
        self.assertIsNone(self.rs.read_pid())


if __name__ == "__main__":
    unittest.main()
