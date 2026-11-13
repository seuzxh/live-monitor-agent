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
      const imgs = Array.from(m.querySelectorAll('img'))
        .map(x => x.src || '')
        .filter(s => s.includes('photo') && /\\.(png|jpg|jpeg)/i.test(s));
      result.push({index: i, text: text.substring(0, 1500), imgs: imgs});
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
    m = re.search(r"[\"']pushed[\"'][:\s]+(\d+)", r.stdout or "")
    pushed = int(m.group(1)) if m else -1
    (TMP / "editor_last.log").write_text(
        f"rc={r.returncode} pushed={pushed}\n{r.stdout[-600:] if r.stdout else ''}\n{r.stderr[-300:] if r.stderr else ''}",
        encoding="utf-8")
    # 伪造防护（evolve 8 提案根源故障）：agent 可能未执行工具就编造
    # {"pushed": N}——真推送必然在 pushes 档案留下 content 记录，由调用方
    # 对比任务前后的档案增量核验，此处仅返回声称值
    return r.returncode == 0 and pushed >= 0, pushed


def count_push_records() -> int:
    """当日 pushes 档案中的真实推送记录数（仅 archive_push 写入的 content 记录）。"""
    p = RUNTIME / "pushes" / f"{datetime.now().strftime('%Y%m%d')}.jsonl"
    if not p.exists():
        return 0
    n = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            if "content" in json.loads(line):
                n += 1
        except Exception:
            continue
    return n


def main() -> int:
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    TMP.mkdir(exist_ok=True)
    RUNTIME.mkdir(exist_ok=True)
    out = (TMP / "poll_out.jsonl").open("a", encoding="utf-8")
    state_file = RUNTIME / "state.json"
    last_total = 0
    stall = 0
    err_streak = 0
    login_fail_streak = 0
    last_login_alert = 0.0
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

    def vision_describe(img_path: Path) -> str:
        """多模态识别直播配图（Doubao-Seed-2.1-Pro；GLM-5.3 无视觉）。
        参数顺序必须 prompt 在前、-i 在后（-i 贪婪吞参）；-o 落干净输出。"""
        import subprocess
        out = TMP / f"vision_{img_path.stem}.txt"
        try:
            subprocess.run(
                ["traecli", "exec",
                 "这是直播里发的配图（多为K线/板块表格/盘面截图）。用中文提炼核心信息："
                 "说明图类型与关键数据点（如连板梯队、涨幅结构、指标状态），80字内。",
                 "-i", str(img_path),
                 "-m", "Doubao-Seed-2.1-Pro-0915",
                 "--permission-mode", "bypass_permissions",
                 "--skip-git-repo-check", "-o", str(out)],
                capture_output=True, text=True, timeout=240,
                cwd=str(ROOT), stdin=subprocess.DEVNULL,
                env={**os.environ, "PATH": os.path.expanduser("~/.local/bin:") + os.environ.get("PATH", "")})
            if out.exists() and out.read_text(encoding="utf-8").strip():
                return out.read_text(encoding="utf-8").strip()[:300]
        except Exception:
            pass
        return ""

    def download_images(msgs: list) -> dict:
        """下载消息配图到 runtime/images/{日期}/，返回 {消息hash: [本地路径]}。
        每消息最多 2 张；失败不阻塞主流程。"""
        import urllib.request
        img_dir = RUNTIME / "images" / datetime.now().strftime("%Y%m%d")
        mapping = {}
        for m in msgs:
            paths = []
            for src in m.get("imgs", [])[:2]:
                h = msg_hash(src)
                dest = img_dir / f"{m.get('index', 'x')}_{h[:8]}.png"
                try:
                    if not dest.exists():
                        img_dir.mkdir(parents=True, exist_ok=True)
                        # 和讯图床按 UA 反盗链（Python-urllib 被拒 567），需浏览器 UA
                        req = urllib.request.Request(src, headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                          "AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
                            "Referer": "https://zhibo.homeway.com.cn/"})
                        with urllib.request.urlopen(req, timeout=30) as r, dest.open("wb") as f:
                            f.write(r.read())
                    if dest.exists() and dest.stat().st_size > 2000:
                        paths.append(dest)
                except Exception:
                    continue
            if paths:
                mapping[m["text"]] = paths
        return mapping

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
                # 登录失效告警（缺口修复 2026-11-11：11-11 全天失效零告警）
                # 连续 5 轮出现登录表单 → 飞书告警一次，30 分钟内不重复
                if login_form > 0:
                    login_fail_streak += 1
                    now_ts = time.time()
                    if login_fail_streak >= 5 and now_ts - last_login_alert > 1800:
                        # 触发自动登录（飞书要码→收码→登录→回执，30 分钟去重防重复触发）
                        try:
                            import subprocess
                            subprocess.Popen(
                                ["xvfb-run", "-a", "python3",
                                 str(ROOT / "scripts/monitor/login/auto_login.py")],
                                stdout=(TMP / "auto_login.log").open("a"),
                                stderr=subprocess.STDOUT,
                                start_new_session=True)
                            last_login_alert = now_ts
                        except Exception:
                            pass
                else:
                    login_fail_streak = 0
                # 老师新消息 → 配图识别并入文本 → LLM 分类编辑推送
                teacher_new = [{"time": rec["ts"], "text": m["text"]}
                               for m in new_msgs
                               if any(m["text"].startswith(t) for t in TEACHERS)]
                if teacher_new:
                    # 配图下载 + 多模态识别（每批最多 3 张，超出不识别仅注明）
                    img_map = download_images(new_msgs)
                    vision_used = 0
                    for tm in teacher_new:
                        paths = img_map.get(tm["text"], [])
                        if not paths:
                            continue
                        notes = []
                        for ip in paths[:3]:
                            desc = vision_describe(ip)
                            notes.append(f"[配图识别] {desc}" if desc
                                         else f"[配图未识别] {ip.name}")
                            vision_used += 1
                        if len(paths) > 3:
                            notes.append(f"[另有{len(paths)-3}张配图未识别]")
                        tm["text"] = tm["text"] + "\n" + "\n".join(notes)
                    if vision_used:
                        out.write(json.dumps({"ts": rec["ts"], "vision": vision_used}) + "\n")
                    pushes_dir = RUNTIME / "pushes"
                    pushes_dir.mkdir(exist_ok=True)
                    # 成败以 pushes 档案增量核验（archive_push 仅在真实发送成功后
                    # 落盘）——agent 编造 {"pushed": N} 而未执行工具时增量必为 0，
                    # 判定失败走重试/留待补推（evolve 8 提案根源故障的代码级防线）
                    before_n = count_push_records()
                    claimed = -1
                    mode = "llm"
                    try:
                        ok, claimed = llm_edit_and_push(teacher_new)
                        if not ok:
                            ok, claimed = llm_edit_and_push(teacher_new)
                            mode = "llm-retry" if ok else "llm-failed"
                    except Exception as e:
                        out.write(json.dumps({"ts": rec["ts"], "llm_err": str(e)[:80]}) + "\n")
                        mode = "llm-failed"
                    after_n = count_push_records()
                    if mode != "llm-failed" and after_n - before_n != claimed:
                        mode = "llm-failed"
                        out.write(json.dumps({"ts": rec["ts"],
                                               "fabricated": claimed,
                                               "actual": after_n - before_n}) + "\n")
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
                # 跨天退出（缺口修复 2026-11-11：收盘后 15:30 主动退出，
                # 不再僵尸跨日——次日 08:45 由 cron 重新拉起）
                hm = datetime.now().strftime("%H%M")
                if "1530" <= hm <= "2359":
                    out.write(json.dumps({"ts": rec["ts"], "action": "收盘后自动退出"}) + "\n")
                    out.flush()
                    try:
                        ctx.close()
                    except Exception:
                        pass
                    return 0
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
