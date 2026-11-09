# 无人值守盯盘 Agent 部署指南

> 对应 spec：`.trae/specs/live-monitor-agent/spec.md`（FR-1/FR-11/NFR-1）
> 前置条件：Trae 企业旗舰版权限（获取 PAT 令牌）、一台 Linux 云服务器（2核2G 起步，推荐 Ubuntu 22.04）
> 2026-11-08 已按本指南在 zxh@GPU 服务器实际部署：本目录 `/home/zxh/projects/14.fupange/直播智能体` 即独立 git 仓库（代码与运行数据一体，脱离 fupan-ge-wiki 知识库仓库），PAT 认证与 traecli exec 链路已实测打通。

## 1. 首次部署（约 30 分钟）

```bash
# ① 获取项目（独立仓库；zxh@GPU 实际部署于 /home/zxh/projects/14.fupange/直播智能体）
git clone https://github.com/seuzxh/live-monitor-agent.git && cd live-monitor-agent

# ② 一键部署（系统依赖 + traecli + Playwright + ddddocr venv + 目录）
#    sudo 不可用时见下方「无 sudo 部署差异」
make deploy

# ③ 配置 traecli 认证（PAT 环境变量注入——无 keyring 服务器唯一可行方式）
#    注意：trae-cli 0.121.x 公网版没有 login 子命令，不要用 traecli login
mkdir -p ~/.config/trae-cli && umask 177
cat > ~/.config/trae-cli/credentials.env <<'EOF'
TRAECLI_PERSONAL_ACCESS_TOKEN=<你的 trae-lt- 开头令牌>
EOF
chmod 600 ~/.config/trae-cli/credentials.env
# 验证（列出模型清单即认证正常，keyring ERROR 属无害噪音）：
set -a && . ~/.config/trae-cli/credentials.env && set +a
PATH=$HOME/.local/bin:$PATH traecli models

# ④ 配置敏感信息（memory.md 已在 .gitignore，不会入库）
cp .trae/skills/live-monitor/memory.template.md .trae/skills/live-monitor/memory.md
# 编辑填入：登录手机号、企业微信 webhook
cp .trae/skills/hexun-live-login/memory.template.md .trae/skills/hexun-live-login/memory.md
# 编辑填入：登录手机号

# ⑤ 验证预检（应在交易日 09:05 前执行；非交易日静默退出）
make preflight

# ⑥ 手动触发一次完整盯盘验证（P1 验收）
make monitor-start
# 观察：runtime/logs/当日.log + 企业微信是否收到推送
```

### 无 sudo 部署差异（2026-11-08 实测）

`deploy.sh` 第 1 步 `apt install` 需要 sudo；无 sudo 时逐项核对：

| deploy.sh 拟装的包 | 无 sudo 时实际情况 |
|---|---|
| gnome-keyring | **不需要**——PAT 环境变量注入方式不依赖 keyring（本指南第 ③ 步） |
| jq / curl / python3 / python3-venv | 多数服务器已有，`which jq curl && python3 -m venv --help` 核对即可 |

其余步骤（traecli 安装脚本、`pip3 install --user playwright`、`playwright install chromium`、ddddocr venv）全部落在 `~` 下，无需 sudo。

## 2. crontab 配置

> 两处必需项（缺一 cron 必失败）：`PATH` 补 `$HOME/.local/bin`（cron 默认 PATH 找不到 traecli）；
> `set -a && . credentials.env`（把 PAT 注入环境，launcher 拉起的 traecli 靠它认证）。

```cron
# 盯盘主任务：交易日 08:45 预检 + 08:50 启动 + 15:20 兜底回收
45 8 * * 1-5 cd /home/zxh/projects/14.fupange/直播智能体 && set -a && . $HOME/.config/trae-cli/credentials.env && set +a && PATH=$HOME/.local/bin:$PATH make preflight >> runtime/logs/cron.log 2>&1
50 8 * * 1-5 cd /home/zxh/projects/14.fupange/直播智能体 && set -a && . $HOME/.config/trae-cli/credentials.env && set +a && PATH=$HOME/.local/bin:$PATH make monitor-start >> runtime/logs/cron.log 2>&1
20 15 * * 1-5 cd /home/zxh/projects/14.fupange/直播智能体 && PATH=$HOME/.local/bin:$PATH make monitor-stop >> runtime/logs/cron.log 2>&1
```

安装：`crontab -e` 粘贴以上三行。节假日由 preflight.sh 内的节假日 API 判断（API 不可达时按工作日放行，宁可误跑不可漏跑）。

## 3. 日常运维命令

| 场景 | 命令 |
|------|------|
| 查看状态 | `make status` |
| 看当日日志 | `make logs` |
| 手动启动（调试） | `make monitor-start` |
| 手动停止 | `make monitor-stop` |
| 跑全部外壳测试 | `make test` |

## 4. 目录与产物

```
runtime/
├── state.json           # auth_status / 消息游标 / 运行统计
├── heartbeat            # 心跳（看门狗每 5 分钟检查，15 分钟超时判卡死）
├── monitor.pid
├── sms_code.txt         # 辅助登录验证码回传（用后删除）
├── auth_history.jsonl   # 登录/续期历史（观测 Cookie 实际寿命）
├── pushes/{日期}.jsonl   # 推送记录（含内容哈希，重启去重）
├── snapshots/{日期}.json # 消息快照（供 collect→distill 下游）
├── browser-profile/     # Chromium 持久化 profile（Cookie 跨天保留，严禁入库）
└── logs/                # 按日切割日志 + watchdog.log
```

## 5. 已知问题与对策

| 问题 | 对策 |
|------|------|
| traecli keyring 报错（headless Ubuntu） | 无害噪音，不影响 PAT 注入方式运行；认证一律走 `TRAECLI_PERSONAL_ACCESS_TOKEN` 环境变量（见第 1 节第 ③ 步） |
| 公网版 traecli 无 login 子命令 / 内嵌 doc 显示字节内场文档 | 属正常现象（0.121.x 公网版即如此）；认证与排障均用 `traecli models` 探活，勿参考内场安装方式 |
| 和讯页面改版 DOM 失效 | 看门狗心跳超时告警；选择器集中在两个 SKILL.md 速查表，改一处即可 |
| 滑块识别成功率波动 | `make captcha-test` 回归；失败自动降级 Cookie SOP（见 login-recovery-sop.md） |
