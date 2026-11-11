# AGENTS.md — 直播智能体项目级规范

> 全局规范见 ~/.zcode/AGENTS.md（输出形态、服务器红线、端口、工作原则八节），本文件不重复，只写本项目特有约束。

## 项目定位

- 无人值守盯盘智能体：交易日自动登录和讯财道「复盘哥专栏 VIP直播室」，按交易时段轮询提炼，推送飞书群；独立于 fupan-ge-wiki 知识库仓库运行。
- 四层结构：`.trae/skills/`（live-monitor 盯盘、hexun-live-login 登录）+ `scripts/monitor/`（core 运行主链 / login 登录恢复，详见 docs/脚本功能说明.md）+ `tests/monitor/`（单元测试）+ `runtime/`（运行产物）。
- 知识库侧（fupan-ge-wiki）的 hexun-live-collect / distill 消费 `直播课/history/`，与本目录解耦；仅 hexun-live-login 技能在两侧各持一份副本。

## 工程边界

- 本目录即项目根（`/home/zxh/projects/14.fupange/直播智能体`），独立 git 仓库，远程 https://github.com/seuzxh/live-monitor-agent（public，Pages 站点 https://seuzxh.github.io/live-monitor-agent/）。
- GitHub 一切操作（建仓/改可见性/PR/Pages/Actions run/secrets）一律用 **gh-cli**，不用网页控制台或裸 curl API。
- `runtime/` 全部内容（state.json、heartbeat、pushes、snapshots、logs、browser-profile、sms_code.txt）为运行产物，严禁入库。
- 不改 fupan-ge-wiki 仓库内的 collect/distill 技能与 `直播课/history/` 数据。
- 外壳脚本保持 Python 标准库；唯一例外 captcha_solver 的 ddddocr，只装在 `scripts/monitor/.venv`（venv 不可搬迁，换目录重建）。

## 知识库检索（只读）

- 战法知识库在 `../fupan-ge-wiki/wiki/`（约 244 篇 md）：战法/体系类问题优先检索它；当日盘面问题用 `runtime/messages/` 当日档案。
- 检索规则以 `../fupan-ge-wiki/wiki/_manifest.json` 为准：quality=dense 页可作答案依据，index 类页仅作路由；快速入口 `wiki/index.md`。
- 只读红线：不改 fupan-ge-wiki 任何文件；回答注明依据页路径。

## 运行状态与环境

- 运行环境：Python 3.10；Playwright Chromium 在 `~/.cache/ms-playwright`；traecli 在 `~/.local/bin`（机器级，不在项目内）。
- 调度：crontab 交易日 08:45 preflight、08:50 monitor-start、15:20 monitor-stop，cron 行内注入 PAT 与 PATH。
- 飞书通道：推送走群 webhook（见密钥节）；交互会话走 traecli lark channel——专用应用凭据 `~/.config/trae-cli/lark.env`（600，机器级），会话配对 `~/.config/trae-cli/lark_chat_id`；验证码回传与 wiki 检索问答经此通道。
- 运维命令一律收口 Makefile（`make help` 列全部）；查状态 `make status`，看日志 `make logs`。

## 密钥与账号红线

- 凭据（登录手机号、推送 webhook）统一存**项目根 `.env`**（`FUPANGE_HEXUN_LOGIN_PHONE` / `FUPANGE_LIVE_MONITOR_WEBHOOK`，600 权限、git 忽略），由用户本人填写；智能体不代收、不代填、不回显内容。`memory.md` 只放业务规则，不再存敏感明文。
- traecli 认证用 PAT 环境变量 `TRAECLI_PERSONAL_ACCESS_TOKEN` 注入（无 keyring 服务器唯一可行方式），凭据文件 `~/.config/trae-cli/credentials.env` 权限 600；令牌本体不进仓库。
- **trae-cli 配置与使用约定**：凡涉及 trae-cli 的配置或用法选型，先查官方文档 https://docs.trae.cn/cli_about-trae-code-cli-2 ，对照当前版本（`traecli --version`）确认后选最佳方案，不凭记忆或旧经验直接写（CLI 1.x/2.x 命令面差异大，2.x 已无 `doc` 子命令）。
- 手机号、短信验证码、Cookie 仅用于和讯财道登录流程；不进推送、不进日志。
- 推送内容不出现主讲人姓名。

## 输出与术语

- 全部中文产出；术语以 `.trae/specs/live-monitor-agent/spec.md` 与各 SKILL.md 定义为准：盯盘、预检（preflight）、看门狗（watchdog）、辅助登录、Cookie 续期 SOP、无人值守模式。
- 新术语或改词直接更新本节；本项目不另建术语表文件。

## 飞书 channel 会话指引（2026-11-11 起）

用户在飞书 bot 里的消息经 traecli channel 进入本仓库会话，遵守：

1. **缺上下文先查档案**：用户问题若指向不明（提到「这个机会/刚才那条/继续讲」等），
   先读 `runtime/pushes/{今天}.jsonl`（当日全部推送成品，含完整 Markdown）与
   `runtime/messages/{今天}.jsonl`（当日直播原文），按引用内容或最近推送对齐所指，再回答。
2. **纯 6 位数字消息是登录验证码**：不是提问，不要展开——回复一句
   「验证码已由登录流程接收」即可，不要把它当作交易指令或代码。
3. **回答风格**：直接回答，引用对应推送的时间与标题；涉及当日盘面以档案为准，
   不确定就说明并给出可查证的档案位置。
4. 回答中不出现主讲人姓名（与推送铁律一致）。

## 验证与交付

- 外壳层改动跑 `make test`（tests/monitor 单元测试，42 项）。
- 运行类结论三态：已部署 / 已部署待配置（memory.md 未完成）/ 未验证。
- 端到端验收以交易日 `make preflight` 通过且飞书群实收推送为准；未实收推送不得宣称盯盘正常。
