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

## 飞书 bot 与跨仓检索（已迁出至工作区根）

- bot 会话工作区自 2026-11-11 迁至工作区根目录 `../`；知识库检索（只读）、ifind 行情技能、飞书 channel 会话指引三节随之移至 `../AGENTS.md`，以该文件为准。

## 运行状态与环境

- 运行环境：Python 3.10；Playwright Chromium 在 `~/.cache/ms-playwright`；traecli 在 `~/.local/bin`（机器级，不在项目内）。
- 调度：crontab 交易日 08:45 preflight、08:50 monitor-start、15:20 monitor-stop，cron 行内注入 PAT 与 PATH。
- 飞书通道：推送走**盯盘 bot 私聊**（`.env` 的 `FUPANGE_LIVE_MONITOR_WEBHOOK=lark-bot`；填 webhook URL 则回退群机器人）——推送可引用追问，引用内容自动成为会话上下文；交互会话走 traecli lark channel（工作区为 `../`，见工作区根 AGENTS.md）——专用应用凭据 `~/.config/trae-cli/lark.env`（600，机器级），会话配对 `~/.config/trae-cli/lark_chat_id`；验证码回传与 wiki 检索问答经此通道。
- bot 收图管线（2026-11-11 起）：`scripts/lark/bot_image_pipeline.py`——companion 不转译图片且 GLM-5.3 无视觉，故轮询 rollout 发现 user.image 消息 → IM API 下载 → Doubao 识别 → 引用回复＋写当日档案 `runtime/bot_images/YYYYMMDD.jsonl`（供会话查阅）；`make bot-image-start/stop/status` 运维，@reboot 自启；状态在 `runtime/bot_image_state.json`。
- **网络与代理（2026-11-12 定论）**：会话网络曾被误判为沙箱禁网，实为本机 mihomo 代理（127.0.0.1:7890，用户级）节点抖动。已三层加固：`~/.trae/traecli.toml` 里 `[shell_environment_policy.set]` 代理变量置空＋`NO_PROXY="*"`（`ignore` 键无效，`set` 键有效）、`[sandbox_workspace_write] network_access=true`；companion/daemon 须在**无代理环境**重启（`restart` 会复用旧 daemon 环境，需先按 PID 清 `traex app-server|lark-runtime` 链再拉起；保活 cron 环境天然干净）；`channel lark disable` 会写 `enabled=false`，恢复须手动改回。
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

## 验证与交付

- 外壳层改动跑 `make test`（tests/monitor 单元测试，42 项）。
- 运行类结论三态：已部署 / 已部署待配置（memory.md 未完成）/ 未验证。
- 端到端验收以交易日 `make preflight` 通过且飞书群实收推送为准；未实收推送不得宣称盯盘正常。
