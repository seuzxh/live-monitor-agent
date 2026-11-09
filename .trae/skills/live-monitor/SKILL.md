---
name: "live-monitor"
description: "和讯财道复盘哥VIP直播室全天盯盘监控技能。当用户说'盯盘'、'开始直播'、'开始监控直播'、'打开直播课'、'准备看盘'时调用。覆盖完整交易日工作流：登录和讯直播页→建立消息提取环境→按交易时段轮询监控→按分类规则提炼干货→通过企业微信Webhook实时推送关键交易信息→盘后收尾。登录手机号仅用于本平台登录，严禁泄露。"
user-invocable: true
---

# 复盘哥直播监控 - 全天盯盘工作流

## 〇、技能总览

本技能负责一个完整交易日（A股 09:15-15:00）的直播室监控，把直播中的**交易机会、风险提示、板块梳理、交易技巧**实时提炼并推送到企业微信群。

**核心原则：质量优先于频率。** 只推对交易决策有帮助的完整观点，不推废话、不推半成品、不凑条数。

### 文件结构
```
{skill_dir}/
├── SKILL.md          # 本文件：工作流与操作规范
├── memory.md         # 运行配置：webhook地址、推送分类/格式/规则、时间节奏（每次启动必读）
├── README.md         # 安装说明
└── scripts/
    └── send_webhook.py  # 企业微信推送脚本（从memory.md读取webhook地址）
```

### 全天工作流五阶段
```
阶段1 准备（盘前）      读memory.md → 打开直播页 → 检测登录
阶段2 登录（如需）      输手机号 → 等用户给验证码 → 登录 → 验证消息容器
阶段3 盘中监控循环       轮询提取消息 → 增量识别 → 分类判断 → 达标即推送
阶段4 时段切换          按交易时间表调整刷新频率（竞价/开盘/盘中/午盘/尾盘）
阶段5 盘后收尾          收盘后确认无总结 → 报告当日推送汇总 → 解锁浏览器
```

---

## 一、启动前检查

### 1.1 读取记忆文件（必做）
首先读取 `{skill_dir}/memory.md`，获取业务规则（分类体系、时间节奏）；凭据（Webhook、登录手机号）从项目根 `.env` 读取（优先级：环境变量 > `.env` > memory.md）：
- 推送分类体系（7类标签）和格式规范
- 推送优先级、时机判断、智能轮询策略
- 浏览器 DOM 选择器
- 盯盘时间节奏表

如果 `.env` 不存在（缺 FUPANGE_HEXUN_LOGIN_PHONE / FUPANGE_LIVE_MONITOR_WEBHOOK），先请用户配置（见 README），勿把凭据写入 memory.md。

### 1.2 隐私安全（强制执行）
- 手机号**仅限在和讯财道平台登录表单中输入**，不得写入任何推送消息、webhook内容、外部脚本、其他网站
- 验证码仅在登录框输入，不得记录、外传
- 登录后的 Cookie/Token 不得提取到外部
- 推送内容只含盘面观点、板块、个股、交易技巧，**严禁出现主讲人姓名**（"李朋"/"廖峥"/"明哥"/"争哥"等一律不得出现在推送中）

### 1.3 工具准备
使用 `integrated_browser` MCP 工具，遵循浏览器操作规范：
- **先 lock 再操作，结束后必须 unlock**（`browser_lock` / `browser_unlock`）
- 调用任何 MCP 工具前，按协议先 `LS` 工具目录、`Read` 对应 JSON descriptor，再 `run_mcp`
- 推送用 `RunCommand` 执行 Python 脚本，**不要用 curl**（特殊字符易导致 JSON 语法错误）

---

## 二、登录与导航流程

### 2.1 打开直播页
```
browser_navigate: url = "https://zhibo.homeway.com.cn/11605/vips.html"
```
等待 2-3 秒（`browser_wait_for` time=3）让页面加载。

### 2.2 检测登录状态
通过 `browser_snapshot` 检查是否出现登录入口：
- 手机号输入框（input, type=tel 或 placeholder 含"手机"）
- "获取验证码"按钮、"登录"按钮

**已登录标志**：页面出现"复盘哥专栏 VIP直播室"标题，且消息区域（`.pointBox.xxm-con`）有消息内容。

### 2.3 执行登录（仅未登录时）

登录态失效时的**三级自愈决策树**（spec FR-3，严格按顺序执行）：

**判定失效**：以下信号**连续 2 次检测**（间隔 10 秒）均出现才确认：
- URL 跳转登录页或出现 `input[type=tel]`
- 消息容器 `.pointList.msglay` 为空且伴随登录表单
- 未登录/会话过期提示文案

**第一级：辅助登录（FR-3A）**
1. **点击登录入口**（有"登录"按钮则点，直接显示输入框则跳过）
2. **输入手机号**：从 memory.md 读取，用 `browser_type` 输入手机号框（手机号只在此处出现）
3. **点击"获取验证码"**
4. **等待验证码**（两种模式）：
   - 人工对话模式：**立即告知用户**"验证码已发送，请提供收到的6位验证码"，等待用户回复
   - 无人值守模式（`MONITOR_RUNTIME_DIR` 存在）：企微推送"登录已失效，验证码已发送，请在 4 分钟内执行 `make auth-input-code CODE=<6位>`"；然后**每 10 秒读一次** `$MONITOR_RUNTIME_DIR/sms_code.txt`，读到 6 位数字即为验证码，读完删除该文件
5. **滑块处理（FR-3B）**：点击获取验证码或登录后若出现滑动滑块验证：
   - `browser_evaluate` 提取滑块背景图与缺口小图（canvas 用 `toDataURL()`，img 用 `src`，均 base64）
   - 将两个 base64 写入临时文件，执行 `python3 scripts/monitor/login/captcha_solver.py solve <bg文件> <slice文件> <slice页x> <slider页x>`
   - 从返回 JSON 取 `track` 点序列，按序回放：`mouse.down` 于 slider 中心 → 逐点 `mouse.move`（每点间隔其 `delay_ms`）→ `mouse.up` 于最后一点
   - 检测滑块消失/验证通过文案；失败则刷新验证码重试，**最多 3 次**
6. **输入验证码并登录**：拿到验证码后 `browser_type` 输入，点"登录"，等 3-5 秒
7. **确认登录成功**：再次 snapshot/evaluate，URL 为 vips.html 且消息区有内容即成功
8. 成功后向 `auth_history.jsonl` 追加 `{"event":"assisted_login","detail":"成功"}`（无人值守模式）

**第二级：降级 Cookie 续期 SOP（第一级失败时）**
- 无人值守模式：写 `state.json` `auth_status=expired` + 失效原因，企微推送 Cookie 续期告警（含 docs/ops/login-recovery-sop.md 路径），进程以**退出码 2** 结束（看门狗识别后不重启）
- 人工模式：告知用户登录失败，引导其走 `make auth-local-login` 路径

**第三级：人工排查**（第二级也失败）：告警提示查看 `runtime/logs/` 日志。

> 验证码有效期 5 分钟，过期则重新点击"获取验证码"并请用户重发（辅助登录总等待时长 4 分钟，超时即降级）。

### 2.4 导航确认
登录后若不在 VIP 直播室，重新 navigate 到 vips.html。

---

## 三、消息提取环境验证

### 3.1 滚动到底部 + 检测消息数量
```javascript
(function() {
  const box = document.querySelector('.pointBox.xxm-con');
  if (box) box.scrollTop = box.scrollHeight;
  const msgs = document.querySelectorAll('.pointBox.xxm-con .pointList.msglay');
  return JSON.stringify({count: msgs.length});
})();
```
返回 `count > 0` 表示容器正常。

### 3.2 报告准备就绪
登录成功并验证后，向用户报告：当前状态、最新消息时间、将按 memory.md 的分类和频率规则开始监控。

---

## 四、盘中监控循环（核心）

### 4.1 单轮监控步骤
每一轮按以下顺序执行：

```
1. 等待（sleep）  ← 时长由当前交易时段决定（见4.4）
2. lock 浏览器
3. browser_evaluate 执行"滚动+提取消息"脚本（见4.2）
4. 与上一轮 total 数量对比，识别新增消息（按 index/时间戳）
5. 逐条分析新消息：
   - 是否老师发言？（开头含"李朋"/"廖峥"；系统消息/纯学员提问跳过）
   - 属于哪个分类？（7类标签）
   - 是否达到推送标准？（见4.3 判断决策）
6. 达标 → unlock → 调 send_webhook.py 推送
   不达标 → 记录"半成品话题"待后续，unlock
7. 连续2轮无新消息 → 刷新频率翻倍（智能轮询，见memory.md）
```

### 4.2 消息提取脚本（标准片段）
```javascript
(function() {
  const box = document.querySelector('.pointBox.xxm-con');
  if (box) box.scrollTop = box.scrollHeight;
  const msgs = document.querySelectorAll('.pointList.msglay');
  const result = [];
  const startIdx = Math.max(0, msgs.length - 15);  // 取最近15条
  msgs.forEach(function(m, i) {
    if (i >= startIdx) {
      let text = (m.innerText || m.textContent || '').trim();
      text = text.replace(/以上内容仅供参考[\s\S]*?风险自担/g, '').trim();
      result.push({index: i, text: text.substring(0, 1500)});
    }
  });
  return JSON.stringify({total: msgs.length, recent: result});
})();
```
> 注意：页面上选择器实测为 `.pointList.msglay`（全局），滚动容器为 `.pointBox.xxm-con`。脚本返回 `total` 用于增量判断。

### 4.3 推送判断决策（严格执行 memory.md 规则）

| 分类 | Emoji | 时机 | 判断要点 |
|------|-------|------|---------|
| 交易机会 | 🎯 | **立即推** | 明确可关注方向/板块/个股/买点节点 |
| 风险提示 | ⚠️ | **立即推** | 走弱信号、回避方向、不追高、仓位警示、监管预警 |
| 行情播报 | 📊 | 完整梳理才推 | 10点梳理、午盘/收盘总结；零散盘面观察**不推** |
| 交易技巧 | 💡 | **讲完再推** | 等话题结束（转话题/总结句/2分钟无新消息），提炼1-3句 |
| 新闻催化 | 📰 | 有内容才推 | 政策、外围、行业事件、公告、期货异动 |
| 案例分析 | 📋 | 有内容才推 | 具体个股/板块走势拆解 |
| 竞价异动 | 🔔 | 竞价阶段 | 09:15-09:30 一字板、竞价涨幅、方向选择 |

**推送铁律**：
1. **绝不出现人名**，观点直接呈现
2. **技巧/教程类严禁边讲边推**，必须等话题完整讲完
3. 同一主题多条消息**合并成一条**，不拆条
4. 同一观点**不重复**推，有新进展才更新
5. 免责声明、纯聊天、无实质内容**不推**
6. 提个股尽量附代码
7. **核心标准是质量和重要性，不是条数**：重要干货多就多推，没价值一条不推

### 4.4 盯盘时间节奏表

| 时间段 | 刷新频率 | 重点关注 |
|-------|---------|---------|
| 09:15-09:30 | 1-2分钟 | 竞价异动、一字板方向、早盘新闻（用🔔标签） |
| 09:30-10:00 | 2-3分钟 | 开盘方向确认、板块异动、首板 |
| 10:00-11:00 | 3-5分钟 | 板块梳理（10点梳理必推）、连板结构、干货 |
| 11:00-11:30 | 3-5分钟 | 午间收盘前方向、下午计划 |
| 11:30-12:55 | 10-15分钟 | 午休低频，12:55 恢复 |
| 13:00-14:00 | 3-5分钟 | 午后开盘方向、回流/切换 |
| 14:00-14:30 | 3-5分钟 | 尾盘方向确认 |
| 14:30-15:00 | 2-3分钟 | 尾盘抢筹/跳水、次日预案 |
| 15:00-15:15 | 5分钟 | 等盘后总结，无总结则收尾 |

**智能轮询**：连续2次无新消息，频率自动翻倍（3→6→10分钟）；出现新消息立即恢复；老师连续讲课时等3-5分钟再查，不打断。

### 4.5 等待实现方式
用 `RunCommand` 执行 `sleep N`（blocking=true，timeout 设为 N+60 秒）。
- 单次 `browser_wait_for` 的 `time` 参数**不得超过 60 秒**；更长等待用 sleep 命令
- sleep 结束后再 lock + evaluate 取消息

---

## 五、推送机制

### 5.1 推送脚本
使用 `{skill_dir}/scripts/send_webhook.py`，它会自动从 memory.md 解析 webhook 地址：

```bash
python3 {skill_dir}/scripts/send_webhook.py "$(cat <<'EOF'
## 【风险提示】14:18 捷荣技术疑似独食陷阱

> ⚠️ 连续一字板但无板块合力，疑似操纵
> 模式：首板拿货→自己顶一字→高位爆量出货→再找下一个首板

### 操作提示
- 警惕无合力支撑的连续一字板
EOF
)"
```

也可用 Python 内联方式（内容含复杂引号时更稳妥）：
```bash
python3 -c "
import sys; sys.path.insert(0, '{skill_dir}/scripts')
from send_webhook import send
send('''## 【标题】...''')
"
```

成功标志：返回 `{"errcode":0,"errmsg":"ok"}`。

### 5.2 推送消息格式（Markdown）
```markdown
## 【分类标签】HH:MM 简短标题

> 核心观点1（直接提炼，不加人名）
> 核心观点2

### 板块/个股（如有）
- **方向A**：标的1、标的2

### 操作提示（如有）
- 具体建议
```

### 5.3 推送后
- 记录已推送的话题/观点，避免重复
- 半成品教学话题在内存中跟踪，等讲完再合并推送

---

## 六、常见问题处理

| 问题 | 处理方式 |
|------|---------|
| 页面白屏/加载失败 | `browser_navigate` 重新打开同一 URL，等 5 秒 |
| 消息停住不更新（MQTT 断开，长时间 total 不增长） | refresh 页面重新加载；**注意刷新后可能补出延迟消息，需逐条检查时间戳，补推错过的重要内容** |
| 弹出风险提示/广告弹窗 | 用 JS 找"关闭"/"确定"按钮点击：`document.querySelectorAll('button')` 遍历匹配 |
| 需要重新登录 | 重新执行第二节登录流程 |
| 找不到手机号输入框 | snapshot 查看结构，可能在 iframe 或弹窗中 |
| 验证码过期（超5分钟） | 重新点"获取验证码"，请用户重发 |
| curl 推送报 JSON 语法错误 | 改用 Python 脚本推送（本技能统一用 Python） |
| browser_wait_for 报错 time 超 60 秒 | 长等待改用 `sleep` 命令 |
| 浏览器忘记 unlock | 每轮操作后立即 unlock；发现锁定状态先 unlock |

### 实战经验（重要）
- **延迟消息补推**：页面 MQTT 偶发断开，刷新后会补出十几分钟前的消息。务必按消息内时间戳逐条核对，错过的 🎯/⚠️ 类重要内容仍要补推（标题时间用消息原始时间）。
- **下午老师常静默**：13:00-14:00 可能长时间不发言，用智能轮询降频，不要空转。
- **尾盘重点**：14:30 后提高频率，关注次日预案、板块末期信号、独食陷阱警示。
- **收盘未必有总结**：老师可能 14:40 后静默到收盘，15:15 前确认无新消息即可收尾，不必死等。

---

## 七、盘后收尾

1. 收盘（15:00）后再观察 10-15 分钟，确认有无盘后总结
2. 确认无新消息后，`browser_unlock` 解锁浏览器
3. 向用户输出**当日推送汇总表**（时间 / 分类 / 核心内容）和当日整体基调
4. 如当天有新的规则优化点或踩坑，追加记录到 `memory.md` 的复盘优化部分
5. （可选）盘后将直播提到的新模式/案例/题材整理到投资知识库

### 7.1 无人值守模式的状态落盘（外壳层协作，spec FR-8/FR-9）

当以无人值守模式运行（cron/launcher 拉起，`MONITOR_RUNTIME_DIR` 环境变量存在）时，收尾阶段必须额外完成以下落盘动作，供外壳层看门狗与次日启动消费：

1. **写 state.json**（项目 `scripts/monitor/core/runtime_state.py` 的 RuntimeState，也可直接写 JSON）：
   - `msg_cursor_total` = 最后一轮提取的消息总数（游标不回退）
   - `stats.polls` = 当日轮询次数；`stats.pushes` = 当日推送条数；`stats.mqtt_reconnects` = MQTT 断连次数
2. **追加 pushes 记录**：每条推送向 `runtime/pushes/{YYYYMMDD}.jsonl` 追加一行 `{"ts","category","hash"}`，hash 用 `RuntimeState.content_hash(text)`（SHA1 of stripped text），供重启去重
3. **心跳**：每轮轮询结束 touch `runtime/heartbeat`（写当前 unix 时间戳字符串）；收尾时再 touch 一次
4. **健康度报告**：收盘汇总末尾附带一行：`今日运行：{正常|异常} | 轮询 {n} 次 | 重启 {n} 次 | MQTT断连 {n} 次(已自愈) | 推送 {n} 条 | 登录态 {valid|expired}`
5. **快照**：将最后一轮消息原文写入 `runtime/snapshots/{YYYYMMDD}.json`，供 hexun-live-collect/distill 下游消费

> 无外壳层（人工对话模式直接调用本技能）时以上步骤可跳过。

---

## 八、DOM 选择器速查

| 元素 | 选择器 | 用途 |
|------|--------|------|
| 消息滚动容器 | `.pointBox.xxm-con` | scrollTop=scrollHeight 滚到最新 |
| 每条消息 | `.pointList.msglay` | 提取单条消息 |
| 免责声明（过滤） | 文本含"以上内容仅供参考…风险自担" | 正则删除 |
| 老师标识 | 消息开头含"李朋"或"廖峥" | 识别老师发言 |
| 私密标记 | 文本含"私密" | VIP 可见，仍需提取 |
| 今日股票 tab | 链接名"今日股票" | 可选查看个股列表 |
