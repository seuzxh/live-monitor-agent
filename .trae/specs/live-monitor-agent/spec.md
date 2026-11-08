# 无人值守盯盘 Agent - Product Requirement Document

## Overview

- **Summary**: 项目已有 [hexun-live-login](../../skills/hexun-live-login/SKILL.md)（登录）和 [live-monitor](../../skills/live-monitor/SKILL.md)（盯盘+推送）两个技能，但运行模式是"用户每天手动说一句'盯盘'才启动"，依赖一个开着的 Trae 会话和浏览器，关掉就停。本批目标：给这两个技能套上一层**标准化外壳**（调度 + 看门狗 + 状态持久化 + 登录自愈流程），让它在云服务器上**交易日全自动无人值守运行**——早上自动启动、自动检测登录态、全天轮询提炼、实时+定时摘要推送到企业微信、收盘自动收尾。登录态失效时按**三级自愈优先级**处理：①系统自动发起手机号验证码登录（滑块验证自动识别完成），用户只需看到企微告警后提供一个短信验证码；②辅助登录失败才降级到 Cookie 续期 SOP；③SOP 也失败才进入人工深度排查。
- **Purpose**:
  1. 消除人工触发：cron 定时拉起，交易日全程无人值守。
  2. 登录态自愈优先：失效先走系统自动辅助登录（仅需用户回传一个验证码），不行再走标准化 Cookie 续期 SOP，把"偶发人工干预"压缩到最小。
  3. 故障可自愈：分级故障矩阵，能自动恢复的自动恢复，不能的快速告警安全退出。
  4. 产物标准化：推送记录/消息快照落盘为 JSON，与 hexun-live-collect → hexun-live-distill 的文件契约模式对齐，为多 agent 协作预留接口。
- **Target Users**: 仓库维护者（唯一用户，接收企微推送）；未来接入的复盘/知识库 agent（消费落盘 JSON）。

## Goals

- **G1: 定时无人值守启动**：cron 在交易日 09:05 预检、09:10 启动、15:20 兜底回收，全程无需人工。
- **G2: 确定性外壳 + LLM 决策分层**：定时、重试、心跳、告警由 Python 外壳完成；消息分类、提炼、推送决策由 traecli exec 加载 SKILL.md 完成。
- **G3: 登录三级自愈机制**：失效自动检测（连续 2 次确认）→ 第一级：系统自动辅助登录（自动填手机号、发验证码、自动过滑块，用户仅需通过 `make auth-input-code` 回传验证码）；→ 第二级：辅助登录失败降级到 Cookie 续期标准化 SOP（告警 → 安全退出（退出码 2 不重启）→ 两条人工续期路径（本地打包上传 / noVNC 应急）→ 5 项固定验证清单 → 状态自动恢复）；→ 第三级：SOP 也失败则告警提示人工深度排查。
- **G4: 故障自愈与看门狗**：心跳监控（15 分钟超时判定卡死）、L1/L2/L3 分级处理、自动重启限次、推送哈希去重、消息游标落盘防丢。
- **G5: 实时 + 定时摘要双轨推送**：🎯/⚠️ 类实时推；10:00/11:30/15:05 三个固定节点推送阶段性摘要。
- **G6: 运行产物标准化落盘**：`直播课/runtime/` 下 heartbeat/state.json/pushes/snapshots/logs，格式与现有 collect→distill 流水线对齐。
- **G7: 每日健康度报告**：收盘汇总附带一行运行状态（轮询次数/重启次数/推送条数/登录态）。
- **G8: 滑块验证码自动识别**：登录过程中出现滑动滑块验证时，通过本地图像识别（ddddocr 缺口检测）+ 拟人轨迹模拟自动完成，无需人工介入；连续失败自动重试，仍失败则降级到第二级 Cookie SOP。

## Non-Goals (Out of Scope)

- **NG1: 不脱离 Trae 生态**：不重写为纯 Playwright + LLM API 独立程序（现有技能资产不浪费；将来如需脱离，分类规则可从 SKILL.md 平滑迁移）。
- **NG2: 不做多 agent 实时协作**：本批只把产物落盘成标准格式，MCP server 暴露查询接口、复盘 agent 消费推送记录等属 P4 后续批次。
- **NG3: 不新增推送渠道**：仅企业微信群机器人（现有 send_webhook.py）；飞书/邮件/Telegram 如需后续扩展。
- **NG4: 不做 Web UI 监控面板**：状态查看用 `make status` + 日志；可视化面板如确有需要后续再议。
- **NG5: 不改动 hexun-live-collect / hexun-live-distill 技能**：它们消费 history JSON 的链路不变，本批只保证盯盘产物的格式与它们对齐。
- **NG6: 不处理非交易时段**：盘前盘后、周末、节假日一律不运行（预检脚本判断节假日直接退出）。

## Background & Context

- 现有 [live-monitor/SKILL.md](../../skills/live-monitor/SKILL.md) 已覆盖完整盯盘业务逻辑：登录、分时段轮询（竞价 1-2 分钟 / 盘中 3-5 分钟 / 尾盘 2-3 分钟）、智能降频（连续 2 轮无新消息频率翻倍）、7 类分类体系（🎯交易机会/⚠️风险提示/📊行情播报/💡交易技巧/📰新闻催化/📋案例分析/🔔竞价异动）、推送格式规范、MQTT 断连补推、盘后收尾。缺的只是"自动启动 + 状态持久化 + 故障处理"的外壳。
- 现有 [hexun-live-login/SKILL.md](../../skills/hexun-live-login/SKILL.md) 已覆盖登录全流程：打开页面、5 种页面状态判断、广告弹窗处理、手机号+验证码登录、消息容器就绪验证、DOM 选择器速查。
- 和讯登录只支持手机号+短信验证码，短信码只能发到用户手机——无头服务器无法完全自动登录，但可以把人工参与压缩到"提供一个验证码"（第一级辅助登录）。滑块验证是登录流程的常见风控环节，社区已有成熟的开源自动识别方案（ddddocr 本地缺口识别 + 拟人轨迹模拟，见 FR-3B），无需打码平台。
- 滑块自动识别的既有方案调研（2026-11）：ddddocr `slide_match()` 本地比对背景图与缺口图返回坐标，配合正弦变速轨迹 + 垂直微抖 + 过冲回拉的鼠标模拟，社区报告成功率 85–95%；不保证 100%，风控可能升级验证难度，因此设计上保留失败降级路径（Cookie SOP）。
- 官方社区已知 traecli 在无图形界面 Ubuntu 上有 keyring 报错（`keyring is not supported on this system`），本设计的部署清单用 `gnome-keyring` + `traecli login --with-trae-pat` 绕过。
- 项目已有 `直播课/cdp_scrape.py` 等 CDP 抓取脚本，证明 Playwright/CDP 无头路线在本项目可行。
- 现有 hexun-live-collect → hexun-live-distill 就是"文件契约"多 agent 协作先例：collect 落 `history/{日期}.json`，distill 消费。本批盯盘产物沿用同一模式。

## Functional Requirements

- **FR-1（预检）**：`scripts/monitor/preflight.sh` 在 09:05 执行：①traecli 登录态检查（`traecli login status`）；②浏览器 user-data-dir 存在且完整；③网络连通性（能访问 zhibo.homeway.com.cn）；④磁盘空间（>500MB）；⑤A 股交易日判断（调用节假日 API，失败时按周一到周五粗匹配）。任一不过 → 企微告警并退出，不启动。
- **FR-2（启动器）**：`scripts/monitor/launcher.py` 在 09:10 被 cron 调用：①读取 `runtime/state.json` 的 `auth_status`，为 `expired` 则跳过当日（避免重复告警）；②拉起 `traecli exec` 无头运行，加载 live-monitor 技能，工作目录为项目根；③将 traecli 的 stdout/stderr 重定向到 `runtime/logs/{日期}.log`；④写入 `runtime/monitor.pid`。
- **FR-3（登录态检测与自愈决策）**：agent 打开直播页后按现有 5 种状态判断，出现以下任一信号且**连续 2 次检测确认**即判定登录态失效：①URL 跳转登录页或出现 `input[type=tel]`；②消息容器 `.pointList.msglay` 为空且伴随登录表单；③未登录/会话过期提示文案。判定失效后**不直接置 expired**，而是按三级自愈顺序处理：
  - **第一级（FR-3A 辅助登录）**：agent 自动执行辅助登录流程，用户仅需提供一个短信验证码；
  - **第二级（FR-4/FR-5 Cookie 续期 SOP）**：辅助登录失败才进入；
  - **第三级（人工排查）**：第二级也失败，推送告警提示查日志/联系维护。
- **FR-3A（辅助登录流程）**：失效判定后 agent 自动执行：①从 memory.md 读手机号填入 `input[type=tel]`；②点击"获取验证码"按钮；③向企微推送固定模板告警："登录已失效，验证码已发送，请在 4 分钟内执行 `make auth-input-code CODE=<6位验证码>`"（用户在任意能 SSH 到服务器的终端执行该命令，脚本将验证码写入 `runtime/sms_code.txt`）；④agent 每 10 秒轮询 `runtime/sms_code.txt`，读取到验证码后填入验证码输入框并点击登录；⑤登录成功后按 FR-6 验证清单验证（除第④项状态重置外），`auth_status` 保持 `valid`，向 `auth_history.jsonl` 追加"辅助登录成功"记录，继续进入监控。超时与失败条件：轮询超过 4 分钟未收到验证码（短信码有效期 5 分钟，留 1 分钟余量）→ 判定辅助登录超时，降级第二级；验证码错误/登录按钮无响应重试 2 次仍失败 → 降级第二级。
- **FR-3B（滑块验证码自动识别）**：辅助登录过程中，点击"获取验证码"或登录后若出现滑动滑块验证，agent 调用 `scripts/monitor/captcha_solver.py` 自动完成：①agent 通过 browser_evaluate 提取滑块背景图与缺口图（canvas `toDataURL` 或 img src 两种来源均支持，base64 传入）；②脚本用 ddddocr `slide_match()` 本地识别缺口 x 坐标（不联网、不传图到第三方），返回坐标 + 拟人轨迹点序列（正弦变速：先加速后减速；垂直微抖；终点过冲 3px 后回拉）；③agent 按轨迹点序列通过浏览器鼠标工具回放（mousedown → 逐点 move → mouseup）；④验证结果检测：滑块消失/出现"验证通过"类文案即成功；仍失败则刷新验证码重试，**最多 3 次**，3 次均失败降级第二级 Cookie SOP。脚本独立可测：提供 `make captcha-test` 用存档的验证码截图样本离线跑识别准确率。
- **FR-4（Cookie 续期 SOP 路径 A：本地打包上传）**：
  - `make auth-local-login`（本地电脑）：有头模式打开直播页 → 用户手动输入手机号+验证码 → 脚本检测到登录成功（URL 为 vips.html 且消息容器非空）→ 自动关闭浏览器 → 打包 user-data-dir 为 `hexun-profile-{日期}.tar.gz`（排除 `Singleton*` 锁文件，校验浏览器已退出）。
  - `make auth-upload HOST=<服务器>`：scp 上传到服务器固定目录 `/opt/fupan-ge-wiki/runtime/profile-incoming/`。
  - `make auth-verify`（服务器）：解压替换 → 无头打开直播页执行验证清单（见 FR-6）→ 全部通过则 `auth_status` 重置为 `valid` 并记录续期历史。
- **FR-5（Cookie 续期 SOP 路径 B：noVNC 应急）**：`make auth-vnc-start` 启动 Xvfb + noVNC + 带虚拟显示器的有头 Chromium，开放临时端口（带一次性访问令牌）；用户任意设备浏览器打开 noVNC 网页完成登录；`make auth-vnc-stop` 关闭；之后同样执行 `make auth-verify`。端口仅续期时临时开放，验证完立即关闭。
- **FR-6（固定验证清单）**：`scripts/monitor/verify_auth.py` 执行 5 项检查，全部通过才算续期成功：①页面 URL 为 vips.html；②不存在 `input[type=tel]`；③`.pointList.msglay` 取到非空消息列表；④`state.json` 的 `auth_status` 改回 `valid` 并记录续期时间；⑤向 `runtime/auth_history.jsonl` 追加续期记录（时间/路径/操作人标记）。
- **FR-7（看门狗）**：`scripts/monitor/watchdog.py` 与 traecli 解耦独立运行：①每 5 分钟检查 `runtime/heartbeat`，超过 15 分钟未更新判定卡死；②按故障分级矩阵处理（见 NFR-2）；③同类故障 30 分钟内只告警一次；④所有动作写入 `runtime/logs/watchdog.log`；⑤自身由 cron 在 09:10 与 agent 同时拉起、15:20 统一回收；若自身退出，整点 cron 健康检查发现无心跳会重新拉起整个任务。
- **FR-8（推送去重与消息游标）**：①每轮处理完消息才将游标 `total` 落盘到 `state.json`（先处理后落盘）；②每条推送写入 `pushes/{日期}.jsonl` 时带消息内容哈希，重启后待推送消息先查哈希，已推过跳过；③MQTT 补出的延迟消息按消息内时间戳逐条核对，错过的 🎯/⚠️ 类仍要补推（沿用现有技能规则）。
- **FR-9（定时摘要）**：10:00 推送板块梳理摘要；11:30 推送午盘摘要（上午 pushes 聚合）；15:05 推送收盘汇总 + 每日健康度一行（格式：`今日运行：正常 | 轮询 42 次 | 重启 0 次 | MQTT断连 1 次(已自愈) | 推送 18 条 | 登录态 valid`）。
- **FR-10（对现有技能的改造）**：
  - `live-monitor/SKILL.md` 收尾阶段增加：写 `state.json`、追加 `pushes/*.jsonl`、touch `runtime/heartbeat` 的明确指令；登录失效时明确决策树："判定失效 → 先 FR-3A 辅助登录（等验证码文件，超时 4 分钟）→ 遇滑块调 captcha_solver.py（重试 3 次）→ 全部失败才写 expired → 退出码 2"。
  - `hexun-live-login/SKILL.md` 登录态检测部分增加"连续 2 次确认失效"判定规则；登录流程部分增加辅助登录分支（填手机号→点发送→轮询 sms_code.txt→填码登录）和滑块分支（提取 canvas 图→调 captcha_solver→回放轨迹）的操作指引。
  - `send_webhook.py` 不改动，直接复用。
- **FR-11（Makefile 标准命令）**：提供 `make deploy / preflight / monitor-start / monitor-stop / auth-input-code CODE=<6位> / captcha-test / auth-local-login / auth-upload / auth-verify / auth-vnc-start / status / logs`，所有运维操作收口到 Makefile，脚本内置 `--help`。
- **FR-12（运维文档）**：`docs/ops/deploy.md`（部署指南）+ `docs/ops/login-recovery-sop.md`（登录恢复完整手册：第一级辅助登录操作指引 + 第二级 Cookie 续期 SOP + 第三级人工排查 checklist），告警消息中附带手册路径。

## Non-Functional Requirements

- **NFR-1（部署环境）**：Linux 云服务器（2核2G 起步，推荐 Ubuntu 22.04）；磁盘占用：Playwright Chromium ~400MB + user-data-dir ~200MB + 日志按日切割保留 30 天；内存峰值：Chromium ~400MB + traecli ~200MB，2G 内存足够。
- **NFR-2（故障分级矩阵）**：

  | 故障类型 | 检测信号 | 分级 | 自动处理 | 升级条件 |
  |---------|---------|------|---------|---------|
  | MQTT 断连/消息停更 | `total` 连续 15 分钟不增长 | L1 | agent 内部 refresh，时间戳补推 | 连续 3 次 refresh 不恢复 → L2 |
  | 网络瞬断 | 页面加载超时、webhook 失败 | L1 | 指数退避重试 30s→60s→120s，最多 5 次 | 重试耗尽 → L2 |
  | traecli 崩溃 | PID 消失，退出码非 0 非 2 | L2 | 看门狗自动重启 1 次，从 state.json 恢复游标 | 重启后 10 分钟内再次崩溃 → L3 |
  | 浏览器卡死 | 心跳超时 15 分钟、内存超阈值 | L2 | 杀浏览器进程，重启任务复用 profile | 当天发生 2 次 → L3 |
  | 登录态失效 | FR-3 三类信号 | L3 | 先自动辅助登录（FR-3A/FR-3B）；辅助失败退出码 2 → 不重启，推送 Cookie 续期 SOP 告警 | — |
  | 推送通道故障 | webhook 连续返回错误 | L2 | 推送内容落本地队列不丢失，恢复后补推 | 30 分钟未恢复 → L3 |
  | 磁盘写满/系统错误 | 日志写入失败、磁盘超阈值 | L3 | 立即告警，安全退出 | — |

- **NFR-3（依赖最小化原则）**：外壳脚本默认只用 Python 标准库 + 系统命令（send_webhook.py 已是标准库实现，保持一致）。**唯一例外**：滑块识别脚本 `captcha_solver.py` 依赖 `ddddocr`（含 onnxruntime），理由：缺口识别用深度学习模型明显优于手写 OpenCV 规则（抗噪、抗仿射变换），且 ddddocr 开箱即用无需训练。约束：①装在独立 venv（`scripts/monitor/.venv`），不影响系统 Python 和其他脚本；②识别完全本地运行，图像不出服务器；③requirements 锁版本并入库。
- **NFR-4（日志与可追溯）**：所有外壳动作写 `runtime/logs/watchdog.log`；agent 输出按日切割到 `runtime/logs/{日期}.log`；推送记录、续期历史、故障重启均以 JSON/JSONL 追加，可追溯。
- **NFR-5（安全）**：①memory.md（含手机号、webhook key）已在 .gitignore 中，服务器上的真实配置绝不进 git；②noVNC 临时端口带一次性令牌，验证完立即关闭；③profile tar 包传输用 scp，不落第三方网盘；④告警内容不含任何凭证信息。
- **NFR-6（性能）**：看门狗每 5 分钟轮询一次，自身 CPU/内存开销可忽略；预检脚本 10 秒内完成；单轮消息提取（滚动+读 DOM）在 2 秒内完成（现有技能已实测）。

## 验收标准（分期）

| 分期 | 内容 | 验收标准 |
|------|------|---------|
| **P1 手动跑通** | 服务器部署 + 手动触发一次完整盯盘 | 手动执行 `traecli exec "盯盘"` 在无头环境跑完一天流程，企微收到推送 |
| **P2 外壳自动化** | launcher + watchdog + crontab + state.json | cron 自动拉起；模拟进程崩溃能自动重启 1 次；重启后消息不丢不重复 |
| **P3 登录自愈 + 无人值守** | 辅助登录（FR-3A/FR-3B）+ Cookie 续期 SOP 降级链路 | ①模拟 Cookie 失效，辅助登录走通（收到告警→`make auth-input-code`→登录成功→进入监控）；②遇滑块验证自动识别通过（用 `make captcha-test` 样本回归）；③辅助登录强制失败，降级 Cookie SOP 走通（告警→本地打包上传→验证 5 项清单全过→状态恢复） |
| **P4 多 agent 协作预留** | 产物格式固化 | 当日 pushes/snapshots JSON 可被 hexun-live-collect/distill 的下游流程读取 |

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| traecli 无头环境 keyring 报错 | CLI 无法登录运行 | gnome-keyring + `traecli login --with-trae-pat` 绕过（官方社区已有验证） |
| Cookie 有效期短于预期 | 续期频繁，"无人值守"打折 | auth_history.jsonl 积累数据后统计实际周期；评估在服务器上预置备用 profile 轮换 |
| 和讯页面改版导致 DOM 选择器失效 | 消息提取失败 | 选择器集中在 SKILL.md 速查表，改版后只需改一处；看门狗心跳超时会告警 |
| 云服务器网络到和讯不稳定 | 盘中断连 | L1 自动重试 + 补推机制；长期观察如频繁发生考虑换机房/加网络探测 |
| traecli exec 输出格式不稳定 | 外壳解析失败 | 心跳/state 由 agent 主动写文件而非解析 stdout，降低耦合 |
| 滑块识别成功率不足 100%（社区报告 85-95%） | 辅助登录偶尔失败 | 重试 3 次 + 失败自动降级 Cookie SOP（FR-3B）；`make captcha-test` 用存档样本回归准确率，和讯换验证码皮肤后重测 |
| 风控升级（滑块变点选/语音等更难验证） | 自动识别完全失效 | 降级 Cookie SOP 兜底；告警中提示人工观察验证码类型变化，必要时引入打码平台（预留接口，本批不实现） |
| 用户 4 分钟内未回传验证码 | 辅助登录超时 | 自动降级 Cookie SOP 并告警，不傻等；用户看到告警后可主动执行 `make auth-input-code` 重试一轮 |
| 短信验证码下发被风控限制（频繁登录触发） | 辅助登录路径不可用 | 降级 Cookie SOP；SOP 的本地有头登录同样会发短信，因此 auth_history 记录失败频率，必要时人工隔日再试 |

## 附录 A：交易日全流程时序

```
09:05 cron → preflight.sh（预检，不过则告警退出）
09:10 cron → launcher.py（读 auth_status，拉起 traecli exec + watchdog）
09:10-09:15 agent → 打开直播页 → 登录态检测
        ├─ 有效 → 直接进入监控
        └─ 失效 → 第一级辅助登录（FR-3A）：
            填手机号 → 点获取验证码 → 企微告警请用户回传验证码
            ├─ 遇滑块 → captcha_solver.py 自动识别（FR-3B，重试≤3）
            ├─ 用户 4 分钟内 make auth-input-code → 填码登录 → 验证 → 进入监控
            └─ 辅助登录失败 → 第二级 Cookie SOP（FR-4/5，退出码 2 不重启）
09:15-11:30 竞价+上午盘轮询，实时推送 🎯/⚠️；10:00 定时摘要
11:30 午盘摘要
11:30-13:00 休市降频，保持页面不断线
13:00-15:00 下午盘轮询推送
15:05 收盘汇总 + 健康度报告
15:15 收尾：写 state/pushes/snapshots，正常退出
全天   每 5 分钟看门狗检查心跳，按故障矩阵处理
15:20 cron 兜底回收
```

## 附录 B：Makefile 命令清单

| 命令 | 执行位置 | 用途 |
|------|---------|------|
| `make deploy` | 服务器 | 完整部署（首次） |
| `make preflight` | 服务器 | 手动跑预检 |
| `make monitor-start` | 服务器 | 手动启动盯盘（调试） |
| `make monitor-stop` | 服务器 | 手动停止 |
| `make auth-input-code CODE=<6位>` | 任意终端（SSH 到服务器） | 辅助登录时回传短信验证码，写入 runtime/sms_code.txt |
| `make captcha-test` | 服务器 | 用存档验证码样本离线回归滑块识别准确率 |
| `make auth-local-login` | 本地电脑 | 有头登录 + 打包 profile |
| `make auth-upload HOST=<服务器>` | 本地电脑 | 上传 profile |
| `make auth-verify` | 服务器 | 解压替换 + 无头验证 + 重置状态 |
| `make auth-vnc-start` | 服务器 | 应急 noVNC 续期 |
| `make auth-vnc-stop` | 服务器 | 关闭 noVNC |
| `make status` | 服务器 | 查看运行状态 |
| `make logs` | 服务器 | tail 当日日志 |
