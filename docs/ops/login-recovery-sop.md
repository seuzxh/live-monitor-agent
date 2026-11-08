# 登录恢复完整手册（三级自愈 SOP）

> 对应 spec：`.trae/specs/live-monitor-agent/spec.md`（FR-3 / FR-3A / FR-3B / FR-4 / FR-5 / FR-6）
> 触发条件：企微收到"登录已失效"类告警，或 `make status` 显示 `auth_status: expired`

## 自愈层级总览

```
登录态失效
  ├─ 第一级（自动）：辅助登录 ── 用户仅需回传一个短信验证码
  │     ├─ 遇滑块 → captcha_solver.py 自动识别（重试≤3）
  │     └─ 超时4分钟/失败 → 降级
  ├─ 第二级（半自动）：Cookie 续期 SOP ── 路径A 本地打包上传 / 路径B noVNC 应急
  │     └─ 验证清单不过 → 升级
  └─ 第三级（人工）：深度排查
```

## 第一级：辅助登录（优先，人工参与度最低）

**你的动作只有一步**：收到企微告警"验证码已发送"后，在任意能 SSH 到服务器的终端执行：

```bash
ssh <服务器>
cd /home/zxh/projects/14.fupange/直播智能体
make auth-input-code CODE=<手机短信里的6位数字>
```

**系统自动完成**：填手机号 → 点获取验证码 → 滑块自动识别（如遇）→ 填码登录 → 验证 → 恢复监控。

**何时失败**：4 分钟内未回传验证码 / 验证码错误 2 次 / 滑块 3 次未过 / 短信发送被风控限制。失败则自动推送第二级告警。

## 第二级路径 A：本地打包上传（日常主路径）

适用于：辅助登录失败，且你能使用自己的电脑。

```bash
# ① 本地电脑（需先 pip install playwright && playwright install chromium）
cd <项目目录>
make auth-local-login
#    浏览器自动打开直播页 → 你完成手机号+验证码（+滑块）登录
#    回到终端按回车 → 自动检测登录态 → 打包为 hexun-profile-<时间>.tar.gz

# ② 上传（Makefile 自动选最新的包）
make auth-upload HOST=user@服务器

# ③ 服务器验证（5 项清单，全过才恢复）
ssh <服务器> && cd /home/zxh/projects/14.fupange/直播智能体 && make auth-verify
```

验证清单（FR-6，全过才算成功）：① URL 为 vips.html ② 无 `input[type=tel]` ③ 消息容器非空 ④ auth_status 重置 valid ⑤ 续期历史落盘。任一项不过 → 按输出排查 → 回到 ①。

验证通过后：当日若想立即恢复盯盘执行 `make monitor-start`；否则次日 09:10 cron 自动拉起。

## 第二级路径 B：noVNC 应急（本地电脑不在手边）

```bash
ssh <服务器> && cd /home/zxh/projects/14.fupange/直播智能体
make auth-vnc-start     # 输出一次性令牌 + http://<IP>:6080/vnc.html 链接
# 手机/任意设备浏览器打开链接 → 在网页里完成登录
make auth-vnc-stop      # 立即关闭端口（安全要求）
make auth-verify
```

> noVNC 端口仅续期期间临时开放，令牌一次性，验证完必须 stop。

## 第三级：人工排查

两级均失败时按序检查：

1. `make status` — 确认 auth_status 与心跳状态
2. `tail runtime/logs/$(date +%Y%m%d).log` — agent 侧报错
3. `tail runtime/logs/watchdog.log` — 看门狗动作记录
4. `cat runtime/auth_history.jsonl` — 失效频率是否异常（频繁失效可能是和讯侧风控加强）
5. 网络：`curl -I https://zhibo.homeway.com.cn` — 服务器到和讯连通性
6. traecli：`set -a && . ~/.config/trae-cli/credentials.env && set +a && PATH=$HOME/.local/bin:$PATH traecli models` — 列出模型即认证正常；失败则令牌过期，到 Trae 控制台重置后更新该凭据文件
7. 页面改版：手动 `make auth-vnc-start` 打开页面观察 DOM 结构是否变化（对照 SKILL.md 选择器速查表）

## Cookie 寿命观测

`auth_history.jsonl` 持续记录每次 expired→valid 的时间点。积累 3 次以上后可统计实际有效期：

```bash
cat runtime/auth_history.jsonl | python3 -c "
import sys, json
from datetime import datetime
events = [json.loads(l) for l in sys.stdin]
pairs = []
last_exp = None
for e in events:
    if e['event'] == 'expired': last_exp = e['ts']
    if e['event'] == 'valid' and last_exp:
        pairs.append((last_exp, e['ts'])); last_exp = None
for a, b in pairs:
    d = datetime.fromisoformat(b) - datetime.fromisoformat(a)
    print(f'{a} -> {b}  持续 {d.days} 天 {d.seconds//3600} 小时')"
```

若寿命明显缩短（如从数周缩到数天），考虑在和讯侧检查账号安全状态，或评估预置备用 profile 轮换（spec 风险表）。
