#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盯盘轮询（人工触发模式的 Playwright 实现，按 live-monitor SKILL.md 4.2 提取）：
循环：滚动到底 → 提取最近消息 → 增量对比 → 新消息 JSONL 追加到 tmp/poll_out.jsonl
每轮 touch runtime/heartbeat；游标写 runtime/state.json（msg_cursor_total）。
连续 12 轮 total 不变则刷新页面一次（MQTT 断连自愈，SKILL 第六节）。
用法：xvfb-run -a python3 tmp/monitor_poll.py [轮询间隔秒，默认60]
"""
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent.parent
PROFILE = str(ROOT / "runtime/browser-profile")
TMP = ROOT / "tmp"
RUNTIME = ROOT / "runtime"
URL = "https://zhibo.homeway.com.cn/11605/vips.html"
WEBHOOK = ROOT / ".trae/skills/live-monitor/scripts/send_webhook.py"
TEACHERS = ("李朋", "廖峥")  # 老师标识（SKILL DOM 速查）

EXTRACT_JS = """
(function() {
  const box = document.querySelector('.pointBox.xxm-con');
  if (box) box.scrollTop = box.scrollHeight;
  const msgs = document.querySelectorAll('.pointList.msglay');
  const result = [];
  const startIdx = Math.max(0, msgs.length - 40);
  msgs.forEach(function(m, i) {
    if (i >= startIdx) {
      let text = (m.innerText || m.textContent || '').trim();
      text = text.replace(/以上内容仅供参考[\\s\\S]*?风险自担/g, '').trim();
      result.push({index: i, text: text.substring(0, 1500)});
    }
  });
  return JSON.stringify({total: msgs.length, recent: result, url: location.href});
})();
"""


EDITOR_PROMPT = """你是直播盯盘推送编辑。读取文件 {msg_file}（JSON 数组，每项含时间与老师发言原文）。

任务（严格按 .trae/skills/live-monitor/memory.md 的分类体系）：
1. 逐条判断分类：🎯交易机会（明确可关注方向/板块/个股/买点）、⚠️风险提示（走弱/回避/仓位警示）、📊行情播报（板块梳理/指数判断/连板结构/竞价异动）、💡交易技巧（方法论/模式/心态，须话题完整）、📰新闻催化、📋案例分析
2. 无实质内容（寒暄/碎片互动/免责声明）直接跳过；同一话题多条合并为一条
3. 每条达标推送整理为 Markdown（标题格式「## 【分类emoji+名】HH:MM 主题」，正文要点化、去人名、个股尽量带代码），立即用 Bash 执行：
   python3 .trae/skills/live-monitor/scripts/send_webhook.py '<整理后的markdown>'
4. 全部处理完只输出一行 JSON：{{"pushed": N, "skipped": M}}
不做任何其他操作。"""


def llm_edit_and_push(new_teacher_msgs: list) -> bool:
    """新老师消息 → 独立 traecli 单次编辑任务（分类提炼+推送）。成功 True。"""
    import subprocess
    msg_file = TMP / "pending_msgs.json"
    msg_file.write_text(json.dumps(new_teacher_msgs, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = os.path.expanduser("~/.local/bin:") + env.get("PATH", "")
    cred = Path.home() / ".config/trae-cli/credentials.env"
    if cred.exists():
        for line in cred.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    r = subprocess.run(
        ["traecli", "exec", EDITOR_PROMPT.format(msg_file=msg_file),
         "--permission-mode", "bypass_permissions",
         "--session-id", f"push-{int(time.time())}",
         "--skip-git-repo-check"],
        capture_output=True, text=True, timeout=300, cwd=str(ROOT), env=env,
        stdin=subprocess.DEVNULL)
    ok = r.returncode == 0 and re.search(r"[\"']pushed[\"']", r.stdout or "")
    (TMP / "editor_last.log").write_text(
        f"rc={r.returncode}\n{r.stdout[-600:] if r.stdout else ''}\n{r.stderr[-300:] if r.stderr else ''}",
        encoding="utf-8")
    return ok


def main() -> int:
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    TMP.mkdir(exist_ok=True)
    RUNTIME.mkdir(exist_ok=True)
    out = (TMP / "poll_out.jsonl").open("a", encoding="utf-8")
    state_file = RUNTIME / "state.json"
    last_total = 0
    stall = 0
    err_streak = 0
    import hashlib
    seen = set()  # 已处理消息内容哈希（防 MQTT 补发重复推送；启动时从当日档案恢复）

    def msg_hash(t: str) -> str:
        return hashlib.md5(re.sub(r"\s", "", t)[:200].encode()).hexdigest()

    def today_path(sub: str) -> Path:
        return RUNTIME / sub / f"{datetime.now().strftime('%Y%m%d')}.jsonl"

    # 恢复当日已处理记录：messages（原文归档）+ pushes（整理成品，由 send_webhook 落盘）
    for _sub in ("messages", "pushes"):
        _p = today_path(_sub)
        if _p.exists():
            for _line in _p.read_text(encoding="utf-8").splitlines():
                try:
                    seen.add(json.loads(_line)["hash"])
                except Exception:
                    continue

    def archive_messages(msgs: list) -> None:
        """当日消息全量归档（含非老师消息），崩溃/重启后可回溯。"""
        try:
            mp = today_path("messages")
            mp.parent.mkdir(parents=True, exist_ok=True)
            with mp.open("a", encoding="utf-8") as f:
                for m in msgs:
                    f.write(json.dumps({"index": m.get("index"),
                                        "hash": msg_hash(m["text"]),
                                        "text": m["text"]}, ensure_ascii=False) + "\n")
        except Exception:
            pass

    with sync_playwright() as p:
        def make_ctx():
            ctx = p.chromium.launch_persistent_context(
                PROFILE, headless=False,
                viewport={"width": 1366, "height": 900},
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(URL, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(6000)
            return ctx, pg

        ctx, page = make_ctx()
        while True:
            try:
                raw = page.evaluate(EXTRACT_JS)
                data = json.loads(raw)
                total = data["total"]
                err_streak = 0
                # 增量 + 哈希去重（MQTT 补发的旧消息不重复推送）
                fresh = []
                for m in data["recent"]:
                    h = msg_hash(m["text"])
                    if h not in seen:
                        seen.add(h)
                        fresh.append(m)
                if fresh:
                    archive_messages(fresh)  # 全量归档（含学员消息，供回溯）
                if last_total == 0:
                    fresh = []  # 重启首轮纯基线：不推送（防重复），记录 total 起点
                # 增量以内容哈希为准（MQTT 重排后 index 语义失效，曾致 11-10 午后
                # 45 条老师消息被 index>=last_total 误杀；hash 已跨重启防补发重推）
                new_msgs = fresh
                # 登录态检测（失效信号）
                login_form = page.locator('input[placeholder*="手机"]').count()
                for f in page.frames:
                    try:
                        login_form += f.locator('input[placeholder*="手机"]').count()
                    except Exception:
                        pass
                rec = {"ts": datetime.now().strftime("%H:%M:%S"), "total": total,
                       "delta": total - last_total, "login_form": login_form,
                       "new": new_msgs}
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                # 老师新消息 → LLM 分类编辑推送（批量，失败兜底转发）
                teacher_new = [{"time": rec["ts"], "text": m["text"]}
                               for m in new_msgs
                               if any(m["text"].startswith(t) for t in TEACHERS)]
                if teacher_new:
                    pushes_dir = RUNTIME / "pushes"
                    pushes_dir.mkdir(exist_ok=True)
                    mode = "llm"
                    try:
                        if not llm_edit_and_push(teacher_new):
                            mode = "llm-retry" if llm_edit_and_push(teacher_new) else "llm-failed"
                    except Exception as e:
                        out.write(json.dumps({"ts": rec["ts"], "llm_err": str(e)[:80]}) + "\n")
                        mode = "llm-failed"
                    if mode == "llm-failed":
                        # 消息已在 messages 档案不丢失；不降级转发（用户裁定），
                        # 留待盘后人工补推（backfill 流程）
                        out.write(json.dumps({"ts": rec["ts"], "deferred": len(teacher_new),
                                               "action": "编辑任务两次失败，留待补推"}) + "\n")
                    with (pushes_dir / f"{datetime.now().strftime('%Y%m%d')}.jsonl").open("a", encoding="utf-8") as pf:
                        for tm in teacher_new:
                            pf.write(json.dumps({"ts": rec["ts"], "mode": mode,
                                                 "head": tm["text"][:80]}, ensure_ascii=False) + "\n")
                    out.write(json.dumps({"ts": rec["ts"], "teacher_msgs": len(teacher_new),
                                           "mode": mode}) + "\n")
                    out.flush()
                # 心跳 + 游标
                (RUNTIME / "heartbeat").write_text(str(int(time.time())))
                state = {}
                if state_file.exists():
                    try:
                        state = json.loads(state_file.read_text(encoding="utf-8"))
                    except Exception:
                        state = {}
                state["msg_cursor_total"] = total
                state["last_poll_ts"] = rec["ts"]
                state_file.write_text(json.dumps(state, ensure_ascii=False, indent=1))
                # 停更检测 → 刷新
                if total == last_total:
                    stall += 1
                    if stall >= 12:
                        page.reload(wait_until="domcontentloaded")
                        page.wait_for_timeout(5000)
                        stall = 0
                else:
                    stall = 0
                last_total = total
            except Exception as e:
                err_streak += 1
                out.write(json.dumps({"ts": datetime.now().strftime("%H:%M:%S"),
                                      "error": str(e)[:120], "streak": err_streak}) + "\n")
                out.flush()
                if err_streak >= 3:
                    # 浏览器崩溃自愈：整 context 重建（而非无效 goto）
                    out.write(json.dumps({"ts": datetime.now().strftime("%H:%M:%S"),
                                          "action": "rebuild_context"}) + "\n")
                    out.flush()
                    try:
                        ctx.close()
                    except Exception:
                        pass
                    try:
                        ctx, page = make_ctx()
                        err_streak = 0
                    except Exception as e2:
                        out.write(json.dumps({"ts": datetime.now().strftime("%H:%M:%S"),
                                              "rebuild_err": str(e2)[:100]}) + "\n")
                        out.flush()
                        time.sleep(30)
                else:
                    try:
                        page.goto(URL, wait_until="domcontentloaded", timeout=45000)
                        page.wait_for_timeout(6000)
                    except Exception:
                        pass
            time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
