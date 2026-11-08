#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""captcha_solver 测试：轨迹生成与坐标换算为纯逻辑（不依赖 ddddocr）。"""
import base64
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "monitor"))

from captcha_solver import (  # noqa: E402
    b64_to_bytes,
    build_track,
    slice_offset_to_distance,
)


class TestB64Decode(unittest.TestCase):
    def test_plain_and_data_uri(self):
        raw = b"fake-image-bytes"
        plain = base64.b64encode(raw).decode()
        self.assertEqual(b64_to_bytes(plain), raw)
        uri = f"data:image/png;base64,{plain}"
        self.assertEqual(b64_to_bytes(uri), raw)


class TestTrackGeneration(unittest.TestCase):
    def test_track_reaches_target_with_overshoot_and_backtrack(self):
        track = build_track(200.0, seed=42)
        # 终点前一点应到达 200
        xs = [p["x"] for p in track]
        self.assertAlmostEqual(xs[-1], 200.0, places=1)
        # 序列里存在过冲点（>200）
        self.assertTrue(any(x > 200 for x in xs))
        # 过冲之后有回拉（最大值之后出现下降）
        peak_idx = xs.index(max(xs))
        self.assertLess(xs[-1], xs[peak_idx])

    def test_sine_easing_monotonic_forward(self):
        track = build_track(100.0, seed=1)
        forward = track[:20]  # 正弦段
        xs = [p["x"] for p in forward]
        self.assertEqual(xs, sorted(xs))  # 单调递增

    def test_later_frames_have_jitter(self):
        track = build_track(300.0, start_y=50, seed=7)
        late = track[15:20]  # 后半程
        ys = {p["y"] for p in late}
        self.assertTrue(len(ys) > 1 or 49 in ys or 51 in ys)  # 出现非 start_y 值

    def test_seed_deterministic(self):
        a = build_track(150.0, seed=99)
        b = build_track(150.0, seed=99)
        self.assertEqual(a, b)

    def test_zero_distance(self):
        track = build_track(0.0, seed=3)
        self.assertAlmostEqual(track[-1]["x"], 0.0, places=1)


class TestDistanceConversion(unittest.TestCase):
    def test_basic_conversion(self):
        # 缺口在背景图 x=180，小图页x=30，把手页x=10 → 位移 = 180-(30-10)=160
        d = slice_offset_to_distance(180, 30, 10)
        self.assertEqual(d, 160.0)

    def test_slice_aligned_with_slider(self):
        # 小图与把手对齐时，位移=缺口坐标
        d = slice_offset_to_distance(180, 30, 30)
        self.assertEqual(d, 180.0)


if __name__ == "__main__":
    unittest.main()
