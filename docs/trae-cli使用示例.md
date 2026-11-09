# trae-cli 实际使用示例

> 全部示例来自 2026-11-08/09 在 zxh@GPU 服务器（无图形界面）的实测。
> 当前版本：**TRAE CLI 0.214.1（2.x 线，Rust 版，`installation: public`）**，2026-11-09 自 0.121.3 升级。
> 内嵌手册：`traecli doc <topic>`；`traecli release-notes` 查看当前账号的发版说明。

## 〇、版本与升级（1.x → 2.x）

```bash
# 安装/升级 2.x（官方入口；0.x 的 install.sh 只给旧线）
sh -c "$(curl -fsSL https://trae.cn/trae-cli/install_v2.sh)"

# 旧配置迁移：traecli.yaml → traecli.toml（MCP 等自动迁移，报告存 ~/.trae/coco-migration-report.txt）
traecli migrate
traecli mcp list        # 确认 MCP 已迁移
```

| 差异点 | 1.x（0.121.3） | 2.x（0.214.1） |
|--------|----------------|----------------|
| 非交互入口 | 根命令 `-p`（exec 不存在） | **`traecli exec [PROMPT]`**（别名 `e`） |
| `-o` 参数 | 静默退出 | 合法（`--output-last-message`） |
| `--query-timeout` | 支持 | **已移除**（超时靠外部控制，如 `timeout 300`） |
| 权限 | `-c permission_mode=...` | `--permission-mode ...`（default/auto/bypass_permissions）或 `-s` 沙箱、`-y` 全放行 |
| keyring 报错 | 每次打印噪音 | 消失 |
| 配置文件 | `~/.trae/trae_cli.yaml` | `~/.trae/traecli.toml`（`-c key=value` 覆盖，值为 TOML） |
| stdin | — | **管道环境会等待 stdin**，须 `</dev/null` 或显式喂入 |

## 一、认证（无 keyring 服务器）

```bash
# PAT 环境变量方式（2.x 同样支持；探活用 models）
set -a && . ~/.config/trae-cli/credentials.env && set +a   # 内含 TRAECLI_PERSONAL_ACCESS_TOKEN
export PATH=$HOME/.local/bin:$PATH
traecli models          # 列出模型即认证正常

# 2.x 也有 login 子命令（交互环境可用）：traecli login --help
```

## 二、非交互单次任务（exec）

```bash
# 冒烟测试（注意 </dev/null 关闭 stdin）
cd /path/to/project
traecli exec "只回复两个字：成功" --permission-mode bypass_permissions --skip-git-repo-check </dev/null

# 完整形态：prompt 位置参数 + 会话 + 全放行 + 末条消息落盘
traecli exec "阅读 AGENTS.md 后总结本项目的运维入口" \
  --permission-mode bypass_permissions \
  --session-id docs-$(date +%m%d) \
  --skip-git-repo-check \
  -o /tmp/last-message.md </dev/null

# 事件流 JSONL（管道场景）
traecli exec "..." --json </dev/null

# 只放行特定命令（比 bypass 收敛）：Bash(模式) 白名单
traecli exec "..." --allowed-tool 'Bash(python3 *)' --allowed-tool Read
```

实测输出尾部带 `tokens used` 统计；退出码 0 = 正常。

## 三、单次任务里让 agent 干活（读文件 + 调脚本 + 输出统计）

本项目核心模式——直播消息分类编辑任务（`scripts/monitor/monitor_poll.py`）：

```python
subprocess.run([
    "traecli", "exec", PROMPT,                       # PROMPT 指示：读 JSON → 分类 → Bash 调 send_webhook → 输出 {"pushed": N, "skipped": M}
    "--permission-mode", "bypass_permissions",
    "--session-id", f"push-{int(time.time())}",      # 每任务全新 ID，不复用不 resume
    "--skip-git-repo-check"],
    capture_output=True, text=True, timeout=300,     # 超时靠外部（2.x 无 --query-timeout）
    stdin=subprocess.DEVNULL)                        # 关键：关闭 stdin
```

> 稳定性结论（两代一致）：单次短任务稳定；常驻/循环会话不可靠（过程输出不可见、并发 resume 静默）。

## 四、会话管理

```bash
traecli resume --last            # 恢复最近会话（交互）
traecli exec resume --last "继续" # 非交互恢复
traecli fork / archive / delete   # 分叉/归档/删除会话
```

同 session-id 多进程并发仍需避免。

## 五、MCP 接入（以 Playwright 浏览器为例）

```bash
# 2.x 语法（-- 分隔命令）：
traecli mcp add browser -- /home/zxh/.local/bin/npx -y @playwright/mcp@latest \
  --browser chromium --user-data-dir /绝对路径/runtime/browser-profile --headless

# 1.x 旧配置用 traecli migrate 自动迁移（本文写作时已验证 browser 配置成功迁移）
traecli mcp list
```

agent 获得 `browser_navigate / browser_snapshot / browser_click / browser_type / browser_evaluate` 工具；同一 user-data-dir 单实例锁（Chromium Singleton），并发报 `Browser is already in use`。

MCP 启动较慢（npx 拉包）时，调用方给足等待（1.x 用 `--mcp-init-wait-seconds`；2.x 默认等待已改善，必要时用外部 `timeout` 兜底）。

## 六、长任务的正确姿势

不要一次 exec 跑数小时循环。**外部循环管可靠性（轮询/心跳/重试），单次任务管智能（分类/整理）**——参考 `scripts/monitor/monitor_poll.py`：Python 60s 轮询 → 每批新消息触发一次 ≤5 分钟的 exec。

## 七、cron 中使用的两个必需项（两代一致）

```cron
# PATH 补 $HOME/.local/bin + PAT 注入
50 8 * * 1-5 cd /项目根 && set -a && . $HOME/.config/trae-cli/credentials.env && set +a && PATH=$HOME/.local/bin:$PATH make monitor-start >> runtime/logs/cron.log 2>&1
```

裸环境验证：`env -i HOME=$HOME SHELL=/bin/sh /bin/sh -c '<整段命令>'`。

## 八、速查

| 命令 | 用途 |
|------|------|
| `traecli exec "..."` | 非交互任务（别名 e） |
| `traecli models` | 列模型（认证探活） |
| `traecli migrate` | 1.x 配置迁移到 toml |
| `traecli release-notes` | 当前账号发版说明 |
| `traecli doctor` | 诊断 |
| `-o <file>` | 末条消息写入文件 |
| `--json` | JSONL 事件流 |
| `--permission-mode bypass_permissions` | 放行审批 |
| `-s danger-full-access` / `-y` | 沙箱/审批全放（危险，仅隔离环境） |
| `--allowed-tool 'Bash(pattern)'` | 命令白名单 |
| `--ephemeral` | 不落盘会话（一次性任务） |
