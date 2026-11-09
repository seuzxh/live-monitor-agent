# Prompt 梳理

> 盘点本系统全部 prompt（LLM 指令）：作用、位置、来源与状态。2026-11-09 成文。
> 配套阅读：[直播监控方案.md](直播监控方案.md) 第三节（归纳层机制）、[架构定位与业界对标.md](架构定位与业界对标.md)。

## 一、总表

| Prompt | 位置 | 作用 | 来源 | 状态 |
|--------|------|------|------|------|
| **EDITOR_PROMPT** | `scripts/monitor/core/monitor_poll.py:53` | LLM 编辑任务总指令：驱动每批老师消息的分类/合并/提炼/推送 | live-monitor 技能的 memory.md 分类体系 + SKILL.md 推送铁律，2026-11-09 分类整理推送模式上线时编写 | **现役（生产主链）** |
| **AGENTS.md** | 项目根 | 项目级规范：工程边界/密钥红线/验证交付；traecli 在 cwd 运行时**自动加载**，是每个编辑任务的隐式上下文 | 用户项目级 AGENTS.md 编写习惯（六段结构），2026-11-08 建 | **现役（自动加载层）** |
| **memory.md 分类体系** | `.trae/skills/live-monitor/memory.md` | 分类权威定义（7 类触发条件/推送原则/时间节奏/隐私规则）；EDITOR_PROMPT 指示 agent 自行读取 | Trae 技能配置（人写机读），随技能引入、增量维护 | **现役（按需读取层）** |
| **MONITOR_PROMPT** | `scripts/monitor/legacy-agent/launcher.py:37` | 常驻 agent 盯盘总指令：登录→轮询→推送→收尾全流程委托 | spec FR-2/G5/G9（`.trae/specs/live-monitor-agent/spec.md`），launcher 初版 | 备用（legacy-agent 模式，实测会话不可靠已停用） |
| **SKILL.md 工作流** | `.trae/skills/live-monitor/SKILL.md` | 全天盯盘工作流八节（登录/提取/轮询/推送/收尾/DOM 速查） | Trae 技能文件，spec 与实盘经验持续沉淀 | 半现役（legacy 模式消费全文；编辑任务模式仅作 agent 可参考的背景知识） |
| 临时接管 prompt | `tmp/login_full.py` 等 | 一次性人工编排指令（登录接管、补推批次） | 当次处置现场编写 | 临时件（tmp/ 不入库，用完即弃） |

## 二、现役主链的上下文装配（一次编辑任务）

traecli exec 任务实际收到的完整上下文由四层组成，按加载方式分两类：

```
[自动加载]  AGENTS.md（项目规范，traecli 读 cwd）
[指令注入]  EDITOR_PROMPT（含七类定义摘要 + 任务流程 + 输出协议 {pushed, skipped}）
[数据注入]  tmp/pending_msgs.json（当批老师消息 JSON）
[按需读取]  memory.md（agent 收到指令后自行 Read，获取分类体系全文与格式规范）
```

**边界说明**：历史消息、历史会话、凭据（PAT 在进程环境变量）、webhook 地址（agent 只调脚本不接触）均**不进**上下文——详见方案文档 1.2 节 context 边界。

## 三、EDITOR_PROMPT 逐段说明（现役）

```
你是直播盯盘推送编辑。读取文件 {msg_file}（JSON 数组，每项含时间与老师发言原文）。
```
角色定界 + 输入契约（文件路径由 monitor_poll 注入当批消息）。

```
任务（严格按 .trae/skills/live-monitor/memory.md 的分类体系）：
1. 逐条判断分类：🎯交易机会（…）、⚠️风险提示（…）、📊行情播报（…）、💡交易技巧（…须话题完整）、📰新闻催化、📋案例分析
```
七类定义**摘要内嵌**（括号内为触发条件），同时指向 memory.md 全文——内嵌保证最小可靠执行，指向保证定义升级不需改代码。

```
2. 无实质内容（寒暄/碎片互动/免责声明）直接跳过；同一话题多条合并为一条
3. 每条达标推送整理为 Markdown（标题格式「## 【分类emoji+名】HH:MM 主题」，正文要点化、去人名、个股尽量带代码），立即用 Bash 执行：
   python3 .trae/skills/live-monitor/scripts/send_webhook.py '<整理后的markdown>'
```
推送铁律的工程化：碎片过滤、话题合并、去人名（隐私红线）、格式模板、**副作用唯一出口**（只许调 send_webhook——推送落盘/去重由脚本层负责，LLM 不接触 webhook 地址）。

```
4. 全部处理完只输出一行 JSON：{"pushed": N, "skipped": M}
不做任何其他操作。
```
输出协议（供 monitor_poll 判定成功/降级）+ 越权禁止（防止 agent 自由发挥读其他文件/发多余消息）。

## 四、MONITOR_PROMPT 逐段说明（备用）

```
现在是一个A股交易日。请调用 live-monitor 技能执行全天盯盘：
登录和讯直播页（如登录态失效，先按 hexun-live-login 技能的辅助登录流程处理，
全部失败才置 expired 并以退出码 2 结束），建立消息提取环境后按交易时段轮询，
按分类规则提炼并通过 Webhook 推送（飞书/企微自适应），10:00/11:30/15:05 推送定时摘要，
15:15 收尾写 state/pushes/snapshots 后退出。
```

- 来源映射：登录自愈链=spec FR-3/3A；定时摘要=FR-9；收尾落盘=FR-8；退出码 2=FR-3 降级约定；
- 2026-11-09 修正过时表述（原「企业微信Webhook」→「Webhook 推送（飞书/企微自适应）」）；
- 停用原因：该模式把**循环控制权交给 LLM**（agent 自主轮询 6 小时），实测过程输出不可见、会陷入自我排查循环（11-09 上午 12 分钟零浏览器调用）、resume 并发静默——架构上退回「脚本管循环、LLM 管判断」。

## 五、演进时间线

| 版本 | 时间 | 形态 | 结局 |
|------|------|------|------|
| v0 设计期 | 2026-11-08 前 | spec 设想 `traecli exec` 常驻 agent 全天盯盘 | exec 子命令在 1.x 不存在，首跑即败 |
| v1 常驻 agent | 11-09 09:43 | MONITOR_PROMPT + playwright-mcp | 轮询正常但推送失效、自我排查循环，09:57 杀 |
| v2 转发降级 | 11-09 10:2x | 规则化全文转发 | 用户反馈不应无脑转发，当天淘汰 |
| **v3 单次编辑任务** | 11-09 10:33 起 | **EDITOR_PROMPT + 外部循环** | 现役：分类整理、碎片过滤、稳定运行 |

## 六、维护规则

1. 分类定义变更：改 **memory.md**（权威源），EDITOR_PROMPT 内嵌摘要同步更新（两处保持一致）；
2. 推送格式变更：改 memory.md 格式规范 + send_webhook 卡片逻辑；
3. 新增 LLM 任务：沿用 EDITOR_PROMPT 三段式（角色+输入契约 / 规则+副作用出口 / 输出协议+越权禁止）；
4. 所有 prompt 的隐私红线不可弱化：不出现人名、不接触 webhook 地址与凭据。
