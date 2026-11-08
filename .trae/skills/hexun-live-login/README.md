# hexun-live-login 技能安装说明

和讯财道直播平台登录与页面初始化基础技能。为其他 agent（盯盘监控、消息提取、历史复盘等）提供"打开直播页并完成登录"的基础能力。

## 定位

这是一个**基础能力组件**，不包含盯盘轮询、内容推送、交易判断等业务逻辑。上层 agent 需要访问直播页时，调用本技能获得一个已登录的浏览器 view 即可。

## 安装方法

将整个 `hexun-live-login/` 目录放到技能目录：

- **全局**：`~/.trae/skills/`（所有项目可用）
- **单项目**：`<项目根目录>/.trae/skills/`

目录结构：
```
skills/
└── hexun-live-login/
    ├── SKILL.md      # 技能主文件（完整登录流程）
    ├── memory.md     # 配置（平台URL、手机号、DOM选择器、经验记录）
    └── README.md     # 本说明
```

## 依赖

- Python 3（本技能无 Python 脚本依赖，仅用标准浏览器MCP工具）
- 浏览器自动化环境（integrated_browser MCP 工具）

## 使用

### 触发词
- "打开直播课"、"登录直播"、"进入直播室"
- 其他 agent 在需要访问直播页时，先调用本技能

### 返回结果
登录完成后返回结构化结果：
```javascript
{
  "viewId": "浏览器视图ID",
  "status": "logged_in" | "already_logged_in" | "failed",
  "url": "当前页面URL",
  "roomTitle": "复盘哥专栏 VIP直播室",
  "messageCount": 123,
  "latestMessageTime": "14:38",
  "needCode": false
}
```

如果 `needCode: true`，表示已发送验证码，等待用户提供6位验证码。

## 配置

首次使用前编辑 `memory.md`：
1. **登录手机号**：改成你的和讯财道登录手机号（仅用于本平台登录）
2. **默认房间**：默认 roomId=11605（复盘哥VIP），其他房间修改URL中的数字
3. 其他DOM选择器和经验记录一般无需改动

## 与 live-monitor 的关系

| 技能 | 职责 | 依赖 |
|------|------|------|
| **hexun-live-login**（本技能） | 打开页面、登录、验证环境就绪 | 无（基础层） |
| live-monitor | 全天盯盘、消息提取、分类推送、盘后总结 | 依赖本技能完成登录 |

如果只需要登录能力（如查看历史消息、查今日股票），单独用本技能即可；需要完整盯盘推送功能，用 live-monitor（它内部可以调用本技能，也可以自己实现登录）。

## 隐私与安全

- `memory.md` 内含登录手机号，**请勿公开分享或提交到公共仓库**
- 手机号、验证码仅用于和讯财道平台登录
- 登录后的 Cookie/Token 不会被提取到外部
