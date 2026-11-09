# trae-cli 实际使用示例

> 全部示例来自 2026-11-08/09 在 zxh@GPU 服务器（无图形界面）的实测，版本 trae-cli 0.121.3（公网版）。
> 内嵌手册：`traecli doc <topic>`（faq / cli-reference / settings / env-vars / model-config 等；注意其中安装/登录章节是字节内场文档，公网版勿照搬）。

## 一、认证（无 keyring 服务器的唯一可行方式）

```bash
# 令牌落地（600 权限，git 忽略）
mkdir -p ~/.config/trae-cli && umask 177
cat > ~/.config/trae-cli/credentials.env <<'EOF'
TRAECLI_PERSONAL_ACCESS_TOKEN=<trae-lt- 开头的令牌>
EOF
chmod 600 ~/.config/trae-cli/credentials.env

# 探活：列出模型即认证正常（keyring ERROR 属无害噪音）
set -a && . ~/.config/trae-cli/credentials.env && set +a
export PATH=$HOME/.local/bin:$PATH
traecli models
```

> 本版本**没有 `login` 子命令**（`traecli login --with-trae-pat` 是旧文档写法，实际不存在）；PAT 环境变量在每次调用时自动向 `api.enterprise.trae.cn` 换取 access token，不依赖 keyring 持久化。

## 二、非交互单次任务（`-p` 模式）

```bash
# 最小用法：冒烟测试
traecli -p "只回复两个字：成功"

# 完整形态：项目根目录执行 + 放行权限 + 限时 + 指定会话
cd /path/to/project
traecli -p "阅读 AGENTS.md 后总结本项目的运维入口" \
  --session-id docs-summary-$(date +%m%d) \
  -c permission_mode=bypass_permissions \
  --query-timeout 3m \
  --bash-tool-timeout 1m

# 需要 JSON 输出（管道场景）
traecli -p "列出 tests/ 下所有测试文件名" --json
```

**必须避开的坑**（均为实测踩过）：

| 坑 | 现象 | 正解 |
|----|------|------|
| `traecli exec ...` | exec 不是子命令，prompt 被丢弃，回复「请指定要执行的命令」 | 根命令 + `-p` |
| `-o out.md` 参数 | 静默退出（exit 0 无任何输出） | 不要用 `-o`，输出走 stdout |
| 交互式确认 | 默认权限模式下 Bash/Edit 被拒 | `-c permission_mode=bypass_permissions` 或 `--allowed-tool Bash,Read` 收窄放行 |
| 输出格式 | 可能输出 Python 单引号 dict 而非标准 JSON | 解析用宽松正则，别 strict json.loads |

## 三、单次任务里让 agent 干活（读文件 + 调脚本 + 输出统计）

本项目的核心模式——「直播消息分类编辑任务」（`scripts/monitor/monitor_poll.py` 每批新消息触发一次）：

```bash
# prompt 指令：读输入文件 → 判断 → 执行 Bash 推送脚本 → 输出一行统计
traecli -p "你是推送编辑。读取 <文件路径>（JSON 数组）。
1. 逐条分类判断（达标/碎片）
2. 达标内容整理后立即用 Bash 执行: python3 .trae/skills/.../send_webhook.py '<markdown>'
3. 结束只输出一行: {\"pushed\": N, \"skipped\": M}" \
  --session-id push-$(date +%s) \
  -c permission_mode=bypass_permissions \
  --query-timeout 4m
```

要点：**每个任务一个全新 `--session-id`**（不复用、不 resume），进程结束即完成——单次短任务稳定（当日 10+ 次验证），而常驻/循环会话不可靠。

## 四、会话管理

```bash
traecli --resume auto          # 恢复最近会话（交互模式）
traecli -p "接着上次的任务继续" --resume <session-id>   # 非交互恢复
```

> 实测警告：同 session-id 多进程并发（原进程存活时 resume）会出现静默无响应；恢复会话仅在前一进程已结束后使用。

## 五、MCP 接入（以 Playwright 浏览器为例）

```bash
# 注册：stdio 方式，复用登录态 profile，headless
traecli mcp add-json browser '{
  "type": "stdio",
  "command": "/home/zxh/.local/bin/npx",
  "args": ["-y", "@playwright/mcp@latest", "--browser", "chromium",
           "--user-data-dir", "/绝对路径/runtime/browser-profile", "--headless"]
}'

traecli mcp list               # 查看（配置落在 ~/.trae/trae_cli.yaml）
traecli mcp remove browser     # 移除
```

接入后 agent 自动获得 `browser_navigate / browser_snapshot / browser_click / browser_type / browser_evaluate` 等工具；注意同一 user-data-dir 同时只能被一个实例持有（Chromium Singleton 锁），并发使用会报 `Browser is already in use`。

调用示例（让 agent 检查页面登录态）：

```bash
traecli -p "调用 browser MCP：browser_navigate 打开 https://example.com，
然后 browser_snapshot，报告页面关键状态。只用 browser 工具。" \
  --session-id web-check-1 -c permission_mode=bypass_permissions \
  --mcp-init-wait-seconds 60 --query-timeout 3m
```

> `--mcp-init-wait-seconds 60`：MCP 启动（npx 拉包）可能较慢，默认等待不够时会「工具不可用」。

## 六、长任务的正确姿势

**不要**指望一次 `-p` 跑 6 小时循环（会话机制不稳定：过程输出不可见、可能卡在自我排查）。正确做法是**外部循环 + 单次任务**：

```bash
# 外部脚本每 60s 轮询检测事件 → 触发一次 4 分钟的 traecli 单次任务处理
# 参考实现：scripts/monitor/monitor_poll.py（轮询 + llm_edit_and_push）
```

若确需长驻（如盯盘），把可靠的部分（轮询、心跳、重试）放在外部 Python，把智能部分（分类、整理）切成一次次短任务——可靠性接近 100%。

## 七、cron 中使用的两个必需项

```cron
# PATH 必须补 $HOME/.local/bin（cron 默认 PATH 找不到 traecli）
# PAT 必须注入（set -a source 凭据文件）
50 8 * * 1-5 cd /项目根 && set -a && . $HOME/.config/trae-cli/credentials.env && set +a && PATH=$HOME/.local/bin:$PATH make monitor-start >> runtime/logs/cron.log 2>&1
```

裸环境验证（模拟 cron 最小环境）：`env -i HOME=$HOME SHELL=/bin/sh /bin/sh -c '<上面整段命令>'`。

## 八、速查

| 命令 | 用途 |
|------|------|
| `traecli models` | 列模型（认证探活） |
| `traecli doctor` | 环境体检（版本/配置/MCP） |
| `traecli doc faq` | 内嵌手册（含 keyring、错误码速查） |
| `traecli -p "..." --json` | 非交互 + JSON 输出 |
| `traecli update` | 自更新 |
| `--query-timeout 5m` | 单次模型调用总限时 |
| `--bash-tool-timeout 30m` | Bash 工具单次限时 |
| `--allowed-tool Read,Grep` | 只放行指定工具（比 bypass 更收敛） |
