# 直播智能体（独立仓库）

无人值守盯盘智能体：交易日 08:45 自动预检、08:50 自动登录和讯财道「复盘哥专栏 VIP直播室」并全天盯盘，提炼交易机会/风险提示等推送到飞书群，15:20 收盘回收。**代码与运行数据全部在本目录，独立于 fupan-ge-wiki 知识库仓库。**

## 目录结构

```
直播智能体/
├── AGENTS.md                  # 项目规范（agent 必读）
├── Makefile                   # 全部运维命令入口
├── README.md                  # 本文件
├── scripts/monitor/           # 三组：core（monitor_poll 主程序）/ login（登录恢复）/ 顶层入口
│   └── .venv/                 # 仅 ddddocr（git 忽略，换目录需重建）
├── tests/monitor/             # 单元测试（make test）
├── docs/                      # 方案/架构对标/脚本说明/prompt 梳理 + ops 运维手册
│   └── （mkdocs 站点，见 GitHub Pages）
├── .trae/
│   ├── skills/live-monitor/       # 盯盘技能
│   ├── skills/hexun-live-login/   # 登录技能（与 fupan-ge-wiki 各持一份）
│   └── specs/live-monitor-agent/  # 需求 spec
└── runtime/                   # 运行产物（git 忽略）：logs/pushes/snapshots/browser-profile
```

## 快速上手

```bash
make help        # 全部命令
make test        # 42 项单元测试
make status      # 运行状态（auth_status/心跳/游标/推送数）
make preflight   # 交易日预检（非交易日静默退出）
```

首次配置（用户本人操作）：

```bash
# ① 凭据（项目根 .env，600 权限，git 忽略）
printf 'FUPANGE_HEXUN_LOGIN_PHONE=<和讯登录手机号>\nFUPANGE_LIVE_MONITOR_WEBHOOK=<飞书群机器人webhook>\n' > .env
chmod 600 .env
# ② 业务规则载体（不含敏感值）
cp .trae/skills/live-monitor/memory.template.md .trae/skills/live-monitor/memory.md
cp .trae/skills/hexun-live-login/memory.template.md .trae/skills/hexun-live-login/memory.md
```

traecli 认证：PAT 存于 `~/.config/trae-cli/credentials.env`（600），crontab 自动注入；详见 `docs/ops/deploy.md`。

## 与 fupan-ge-wiki 的关系

| 关注点 | 归属 |
|--------|------|
| 盯盘运行、登录、推送（本目录） | 直播智能体 |
| 直播内容收录与知识沉淀（`直播课/history/`、wiki/） | fupan-ge-wiki |
| hexun-live-login 登录技能 | 两侧各一份副本，登录页改版时两边同步改 |
