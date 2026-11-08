# AGENTS.md — 直播智能体项目级规范

> 全局规范见 ~/.zcode/AGENTS.md（输出形态、服务器红线、端口、工作原则八节），本文件不重复，只写本项目特有约束。

## 项目定位

- 无人值守盯盘智能体：交易日自动登录和讯财道「复盘哥专栏 VIP直播室」，按交易时段轮询提炼，推送企业微信；独立于 fupan-ge-wiki 知识库仓库运行。
- 四层结构：`.trae/skills/`（live-monitor 盯盘、hexun-live-login 登录）+ `scripts/monitor/`（preflight / launcher / watchdog 外壳）+ `tests/monitor/`（单元测试）+ `runtime/`（运行产物）。
- 知识库侧（fupan-ge-wiki）的 hexun-live-collect / distill 消费 `直播课/history/`，与本目录解耦；仅 hexun-live-login 技能在两侧各持一份副本。

## 工程边界

- 本目录即项目根（`/home/zxh/projects/14.fupange/直播智能体`），独立 git 仓库。
- `runtime/` 全部内容（state.json、heartbeat、pushes、snapshots、logs、browser-profile、sms_code.txt）为运行产物，严禁入库。
- 不改 fupan-ge-wiki 仓库内的 collect/distill 技能与 `直播课/history/` 数据。
- 外壳脚本保持 Python 标准库；唯一例外 captcha_solver 的 ddddocr，只装在 `scripts/monitor/.venv`（venv 不可搬迁，换目录重建）。

## 运行状态与环境

- 运行环境：Python 3.10；Playwright Chromium 在 `~/.cache/ms-playwright`；traecli 在 `~/.local/bin`（机器级，不在项目内）。
- 调度：crontab 交易日 09:05 preflight、09:10 monitor-start、15:20 monitor-stop，cron 行内注入 PAT 与 PATH。
- 运维命令一律收口 Makefile（`make help` 列全部）；查状态 `make status`，看日志 `make logs`。

## 密钥与账号红线

- `.trae/skills/*/memory.md`（登录手机号、企微 webhook）由用户本人从 template 复制填写；智能体不代收、不代填、不回显内容。
- traecli 认证用 PAT 环境变量 `TRAECLI_PERSONAL_ACCESS_TOKEN` 注入（无 keyring 服务器唯一可行方式），凭据文件 `~/.config/trae-cli/credentials.env` 权限 600；令牌本体不进仓库。
- 手机号、短信验证码、Cookie 仅用于和讯财道登录流程；不进推送、不进日志。
- 推送内容不出现主讲人姓名。

## 输出与术语

- 全部中文产出；术语以 `.trae/specs/live-monitor-agent/spec.md` 与各 SKILL.md 定义为准：盯盘、预检（preflight）、看门狗（watchdog）、辅助登录、Cookie 续期 SOP、无人值守模式。
- 新术语或改词直接更新本节；本项目不另建术语表文件。

## 验证与交付

- 外壳层改动跑 `make test`（tests/monitor 单元测试，42 项）。
- 运行类结论三态：已部署 / 已部署待配置（memory.md 未完成）/ 未验证。
- 端到端验收以交易日 `make preflight` 通过且企业微信实收推送为准；未实收推送不得宣称盯盘正常。
