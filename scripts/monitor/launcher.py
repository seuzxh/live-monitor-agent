#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盯盘启动器（spec FR-2）

职责：
- 读 state.json 的 auth_status，expired 则跳过当日（避免重复告警）
- 拉起 traecli exec 无头运行 live-monitor 技能
- stdout/stderr 重定向到 runtime/logs/{日期}.log，写 monitor.pid
- 若已有实例在跑（PID 存活），拒绝重复启动

退出码约定（spec FR-3 / NFR-2）：
- 0  正常（包括 skipped/expired）
- 2  登录态 expired（看门狗识别后不走自动重启）
- 1  其他错误

纯标准库实现。traecli 的可执行名与启动命令集中在 build_command()，便于测试替换。
"""
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_state import RuntimeState, EXPIRED, DEFAULT_RUNTIME_DIR  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_AUTH_EXPIRED = 2

MONITOR_PROMPT = (
    "现在是一个A股交易日。请调用 live-monitor 技能执行全天盯盘："
    "登录和讯直播页（如登录态失效，先按 hexun-live-login 技能的辅助登录流程处理，"
    "全部失败才置 expired 并以退出码 2 结束），建立消息提取环境后按交易时段轮询，"
    "按分类规则提炼并通过企业微信Webhook推送，10:00/11:30/15:05 推送定时摘要，"
    "15:15 收尾写 state/pushes/snapshots 后退出。"
)


def pid_alive(pid: int) -> bool:
    """检查进程是否存活（UNIX 方式）。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def build_command(runtime_dir: Path | None = None) -> list[str]:
    """构造 traecli exec 启动命令（独立函数便于测试）。"""
    out_dir = runtime_dir if runtime_dir is not None else DEFAULT_RUNTIME_DIR
    return [
        "traecli", "exec",
        "--sandbox", "workspace-write",
        "--ask-for-approval", "never",
        "--skip-git-repo-check",
        "-o", str(out_dir / "logs" / "last-message.md"),
        MONITOR_PROMPT,
    ]


def log_line(log_path: Path, msg: str) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="盯盘启动器")
    parser.add_argument("--runtime-dir", default=str(DEFAULT_RUNTIME_DIR))
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印将执行的命令，不真正启动（调试用）")
    args = parser.parse_args()

    state = RuntimeState(args.runtime_dir)
    log_path = Path(args.runtime_dir) / "logs" / f"{datetime.now().strftime('%Y%m%d')}.log"

    # 1) 登录态检查：expired 当日直接跳过（spec FR-2）
    if state.auth_status == EXPIRED:
        log_line(log_path, "auth_status=expired，跳过今日启动")
        print("SKIP: auth_status=expired")
        return EXIT_OK

    # 2) 防重复启动
    existing_pid = state.read_pid()
    if existing_pid and pid_alive(existing_pid):
        log_line(log_path, f"已有实例在跑 pid={existing_pid}，拒绝重复启动")
        print(f"SKIP: monitor already running (pid={existing_pid})")
        return EXIT_OK

    # 3) 拉起 traecli exec
    cmd = build_command(Path(args.runtime_dir))
    log_line(log_path, f"启动盯盘: {' '.join(cmd[:3])} ...")

    if args.dry_run:
        print("DRY-RUN:", " ".join(cmd))
        return EXIT_OK

    env = dict(os.environ)
    env["MONITOR_RUNTIME_DIR"] = str(Path(args.runtime_dir).resolve())

    with log_path.open("a", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=logf,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,  # 独立进程组，cron 环境不挂死
        )
    state.write_pid(proc.pid)
    state.touch_heartbeat()  # 启动即有心跳，给看门狗一个初始基准
    log_line(log_path, f"已拉起 pid={proc.pid}")
    print(f"STARTED pid={proc.pid}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
