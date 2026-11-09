# 直播监控智能体

无人值守盯盘智能体：交易日自动登录和讯财道「复盘哥专栏 VIP直播室」，盘中轮询老师发言，LLM 按七类分类整理后推送飞书卡片。

**一句话架构**：脚本管可靠（重试/去重/自愈/落盘），LLM 管判断（分类/合并/提炼），runtime 档案管记忆——模型会话被刻意排除在架构之外。

| 文档 | 内容 |
|------|------|
| [直播监控方案](直播监控方案.md) | 架构总览、盘中监控、信息归纳、推送链路、登录恢复、调度运维、实盘故障记录 |
| [交互式架构图](直播监控架构.html) | 可缩放/聚焦/主题切换的组件图（主链路/采集登录/记忆配置三视图） |
| [架构定位与业界对标](架构定位与业界对标.md) | 与 Anthropic workflow / LangGraph / n8n 的逐项对标 |
| [脚本功能说明](脚本功能说明.md) | scripts/monitor 十三个脚本的功能分组与详述 |
| [trae-cli 使用示例](trae-cli使用示例.md) | 认证/exec/会话/MCP/cron 全实测示例（1.x→2.x 差异） |
| [部署指南](ops/deploy.md) | 服务器首次部署与 crontab 配置 |
| [登录恢复 SOP](ops/login-recovery-sop.md) | 三级自愈手册（辅助登录/Cookie 续期/人工排查） |

## 快速状态

- 仓库：[seuzxh/live-monitor-agent](https://github.com/seuzxh/live-monitor-agent)（private）
- 调度：交易日 08:45 预检 → 08:50 启动 → 15:20 回收
- 技术栈：Python 标准库 + Playwright（Xvfb 有头）+ traecli 2.x + 飞书 webhook
