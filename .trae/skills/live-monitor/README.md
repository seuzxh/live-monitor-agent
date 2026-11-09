# live-monitor 技能安装说明

和讯财道「复盘哥专栏 VIP直播室」全天盯盘监控技能。自动登录直播页、按交易时段轮询消息、提炼交易机会/风险提示/板块梳理/交易技巧，并通过企业微信 Webhook 实时推送。

## 安装方法

将整个 `live-monitor/` 目录放到技能目录即可：

- **全局安装（所有项目可用）**：`~/.trae/skills/` 或平台的全局 skills 目录
- **仅当前项目**：`<项目根目录>/.trae/skills/`

目录结构需保持为：
```
skills/
└── live-monitor/
    ├── SKILL.md            # 技能主文件（工作流与操作规范）
    ├── memory.md           # 运行配置（webhook、推送规则、时间节奏）
    ├── README.md           # 本说明
    └── scripts/
        └── send_webhook.py # 企业微信推送脚本
```

## 依赖

- Python 3（仅用标准库，无需 pip 安装）
- 浏览器自动化环境（integrated_browser / MCP browser 工具）

## 使用

在对话中说「盯盘」「开始直播」「开始监控直播」即可触发。

## 配置

首次使用前，编辑 `memory.md`：

1. **Webhook 地址**：改成你自己的企业微信群机器人地址
2. **登录手机号**：改成你的和讯财道登录手机号（仅用于本平台登录）
3. 其余推送分类、格式、时间节奏规则可按需调整

> `scripts/send_webhook.py` 会自动从 `memory.md` 解析 webhook 地址，无需改脚本。
> 也可用环境变量 `FUPANGE_LIVE_MONITOR_WEBHOOK` 覆盖。

## 隐私与安全提示

- `memory.md` 内含 webhook key 和登录手机号，**请勿公开分享或提交到公共仓库**
- 手机号、验证码仅用于和讯财道平台登录，不会写入任何推送内容
- 推送内容只含盘面观点，不含任何个人信息，且不标注主讲人姓名
