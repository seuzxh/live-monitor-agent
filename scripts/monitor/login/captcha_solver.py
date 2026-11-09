#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
滑块验证码自动识别（spec FR-3B）

分工：
- 本脚本：缺口坐标识别（ddddocr，本地离线）+ 拟人轨迹点序列生成（纯 Python）
- agent：通过浏览器工具提取 canvas/img 图像（base64 传入）、按返回的轨迹点回放鼠标

设计：
- ddddocr 为可选依赖：未安装时 gap detection 报明确错误，但轨迹生成/坐标换算
  等纯逻辑全部可测（spec NFR-3 例外条款，venv 隔离安装）
- 轨迹：正弦变速（先加速后减速）+ 垂直微抖 + 终点过冲 3px 回拉，
  社区验证的拟人三要素

CLI：
    python3 captcha_solver.py gap <bg_b64_file> <slice_b64_file>   # 识别缺口
    python3 captcha_solver.py track <distance> [--steps N]          # 生成轨迹
    python3 captcha_solver.py solve <bg_b64_file> <slice_b64_file> <slice_page_x>
        # 完整：返回 JSON {gap_x, track:[{x,y,delay_ms}...]}
"""
import argparse
import base64
import json
import math
import random
import sys
from pathlib import Path

OVERSHOOT_PX = 3       # 终点过冲量（模拟人眼对齐纠错）
BACKTRACK_DELAY_MS = 120
DEFAULT_STEPS = 20
DEFAULT_FRAME_DELAY_MS = 15


def load_ddddocr():
    """延迟导入 ddddocr，未安装时给出明确安装指引。"""
    try:
        import ddddocr  # noqa: N813
        return ddddocr
    except ImportError:
        sys.stderr.write(
            "ERROR: ddddocr 未安装。执行: python3 -m venv scripts/monitor/.venv && "
            "scripts/monitor/.venv/bin/pip install ddddocr\n"
        )
        sys.exit(2)


def b64_to_bytes(b64: str) -> bytes:
    """支持带/不带 data URI 前缀的 base64。"""
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    return base64.b64decode(b64)


def detect_gap_x(bg_bytes: bytes, slice_bytes: bytes) -> int:
    """返回缺口在背景图中的 x 坐标（像素）。需 ddddocr。"""
    ddddocr = load_ddddocr()
    ocr = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)
    res = ocr.slide_match(bg_bytes, slice_bytes, simple_target=True)
    target = res["target"]
    # ddddocr 新旧版本返回结构不同：target 可能是 int 或 [x, y]
    if isinstance(target, (list, tuple)):
        return int(target[0])
    return int(target)


def build_track(distance_px: float, start_x: float = 0.0, start_y: float = 0.0,
                steps: int = DEFAULT_STEPS,
                frame_delay_ms: int = DEFAULT_FRAME_DELAY_MS,
                overshoot_px: int = OVERSHOOT_PX,
                seed: int | None = None) -> list[dict]:
    """
    生成拟人滑动轨迹点序列。

    三要素（反行为风控关键）：
    1. 正弦变速：sin(i/steps * π/2) 映射，斜率先大后小 = 人手先推后刹
    2. 垂直微抖：后半程 Y 轴 ±1px 漂移
    3. 过冲回拉：终点故意超出 overshoot_px，停顿 BACKTRACK_DELAY_MS 后拉回
    """
    rng = random.Random(seed)  # seed 可注入，测试可复现
    track = []
    for i in range(steps):
        percent = math.sin(((i + 1) / steps) * (math.pi / 2))
        x = start_x + distance_px * percent
        if i > steps * 0.7:
            y = start_y + rng.choice([-1, 1])
        else:
            y = start_y
        track.append({"x": round(x, 2), "y": y, "delay_ms": frame_delay_ms})
    # 过冲：三步划出 overshoot，停顿，两步拉回
    track.append({"x": round(start_x + distance_px + overshoot_px, 2),
                  "y": start_y, "delay_ms": frame_delay_ms})
    track.append({"x": round(start_x + distance_px + overshoot_px, 2),
                  "y": start_y, "delay_ms": BACKTRACK_DELAY_MS})
    track.append({"x": round(start_x + distance_px, 2),
                  "y": start_y, "delay_ms": frame_delay_ms})
    return track


def slice_offset_to_distance(gap_x: int, slice_page_x: int,
                             slider_page_x: int) -> float:
    """
    缺口图像坐标 → 鼠标实际位移换算。

    gap_x          : 缺口在背景图内的 x 坐标（detect_gap_x 返回值）
    slice_page_x   : 滑块小图当前在页面上的 x 坐标（bounding_box）
    slider_page_x  : 拖动条把手在页面上的 x 坐标（bounding_box）
    原理：小图初始贴着把手，缺口距离 = 缺口x - (小图页x - 把手页x)
    """
    return float(gap_x - (slice_page_x - slider_page_x))


def cmd_solve(args) -> int:
    bg = b64_to_bytes(Path(args.bg_file).read_text(encoding="utf-8").strip())
    sl = b64_to_bytes(Path(args.slice_file).read_text(encoding="utf-8").strip())
    gap_x = detect_gap_x(bg, sl)
    distance = slice_offset_to_distance(gap_x, args.slice_page_x, args.slider_page_x)
    track = build_track(distance, seed=args.seed)
    print(json.dumps({
        "gap_x": gap_x,
        "distance": distance,
        "track": track,
    }, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="滑块验证码识别（ddddocr + 拟人轨迹）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_gap = sub.add_parser("gap", help="识别缺口 x 坐标")
    p_gap.add_argument("bg_file", help="背景图 base64 文件路径")
    p_gap.add_argument("slice_file", help="滑块小图 base64 文件路径")

    p_track = sub.add_parser("track", help="生成拟人轨迹")
    p_track.add_argument("distance", type=float, help="鼠标位移像素")
    p_track.add_argument("--steps", type=int, default=DEFAULT_STEPS)
    p_track.add_argument("--seed", type=int, default=None)

    p_solve = sub.add_parser("solve", help="识别+轨迹完整输出（JSON）")
    p_solve.add_argument("bg_file")
    p_solve.add_argument("slice_file")
    p_solve.add_argument("slice_page_x", type=float, help="滑块小图页面 x")
    p_solve.add_argument("slider_page_x", type=float, help="拖动条把手页面 x")
    p_solve.add_argument("--seed", type=int, default=None)

    args = parser.parse_args()
    if args.cmd == "gap":
        bg = b64_to_bytes(Path(args.bg_file).read_text(encoding="utf-8").strip())
        sl = b64_to_bytes(Path(args.slice_file).read_text(encoding="utf-8").strip())
        print(detect_gap_x(bg, sl))
        return 0
    if args.cmd == "track":
        print(json.dumps(build_track(args.distance, steps=args.steps, seed=args.seed)))
        return 0
    if args.cmd == "solve":
        return cmd_solve(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
