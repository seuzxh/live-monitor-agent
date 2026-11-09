#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_auth 测试：checklist 纯逻辑，用构造的 facts 验证各分支。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "monitor" / "login"))

from runtime_state import RuntimeState, EXPIRED, VALID  # noqa: E402
from verify_auth import run_checklist  # noqa: E402


GOOD_FACTS = {"url": "https://zhibo.homeway.com.cn/11605/vips.html",
              "has_tel_input": False, "msg_count": 12}


class ChecklistTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rs = RuntimeState(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class TestAllPass(ChecklistTestBase):
    def test_good_facts_all_pass(self):
        result = run_checklist(GOOD_FACTS, self.rs, source="test")
        self.assertTrue(result["all_pass"])
        self.assertTrue(all(c["pass"] for c in result["checks"]))

    def test_expired_state_reset_to_valid(self):
        self.rs.mark_expired("测试")
        run_checklist(GOOD_FACTS, self.rs, source="辅助登录")
        self.assertEqual(self.rs.auth_status, VALID)
        self.assertEqual(self.rs.get("auth_valid_source"), "辅助登录")

    def test_history_recorded(self):
        run_checklist(GOOD_FACTS, self.rs, source="cookie_sop")
        lines = Path(self.rs.auth_history_file).read_text(encoding="utf-8").strip().splitlines()
        events = [json.loads(l)["event"] for l in lines]
        self.assertIn("verify_pass", events)


class TestPageFailures(ChecklistTestBase):
    def test_login_page_url_fails(self):
        facts = dict(GOOD_FACTS, url="https://zhibo.homeway.com.cn/login")
        result = run_checklist(facts, self.rs)
        self.assertFalse(result["all_pass"])
        self.assertFalse(result["checks"][0]["pass"])

    def test_tel_input_present_fails(self):
        facts = dict(GOOD_FACTS, has_tel_input=True)
        result = run_checklist(facts, self.rs)
        self.assertFalse(result["checks"][1]["pass"])

    def test_empty_messages_fails(self):
        facts = dict(GOOD_FACTS, msg_count=0)
        result = run_checklist(facts, self.rs)
        self.assertFalse(result["checks"][2]["pass"])

    def test_page_fail_keeps_expired_state(self):
        """页面检查不过时，不允许重置 expired 状态。"""
        self.rs.mark_expired("测试")
        result = run_checklist({"url": "https://x/login", "has_tel_input": True,
                                "msg_count": 0}, self.rs)
        self.assertFalse(result["all_pass"])
        self.assertEqual(self.rs.auth_status, EXPIRED)


class TestCheck4AlreadyValid(ChecklistTestBase):
    def test_already_valid_still_passes_check4(self):
        # valid 状态下跑验证（如每日预检），第④项应直接通过
        result = run_checklist(GOOD_FACTS, self.rs)
        check4 = [c for c in result["checks"] if c["id"] == 4][0]
        self.assertTrue(check4["pass"])


if __name__ == "__main__":
    unittest.main()
