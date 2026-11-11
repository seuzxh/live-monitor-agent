# 无人值守盯盘 Agent 标准命令入口（spec FR-11 / 附录 B）
# 所有运维操作收口于此；各脚本均支持 --help

PROJECT_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
export MONITOR_RUNTIME_DIR := $(PROJECT_ROOT)/runtime
MON := scripts/monitor
CORE := $(MON)/core
LOGIN := $(MON)/login
LARK := scripts/lark

.PHONY: help deploy preflight monitor-start monitor-stop \
        auth-input-code captcha-test \
        auth-local-login auth-upload auth-verify auth-vnc-start auth-vnc-stop \
        bot-image-start bot-image-stop bot-image-status \
        status logs test

help: ## 显示全部命令
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "%-20s %s\n", $$1, $$2}'

# ---------- 部署与日常 ----------

deploy: ## 完整部署（服务器首次）：系统依赖 + traecli + Playwright
	@bash $(MON)/deploy.sh

preflight: ## 手动跑交易日预检
	@bash $(MON)/preflight.sh

monitor-start: ## 启动盯盘（轮询+LLM分类推送；生产由 cron 触发）
	@setsid nohup xvfb-run -a -s "-screen 0 1440x900x24" python3 $(CORE)/monitor_poll.py 60 >/dev/null 2>&1 &
	@sleep 3; cat $(MONITOR_RUNTIME_DIR)/monitor.pid 2>/dev/null >/dev/null && true; echo "monitor_poll 已后台启动（日志: tmp/poll_out.jsonl）"

monitor-stop: ## 手动停止盯盘
	@bash $(MON)/force_cleanup.sh

status: ## 查看运行状态（PID/心跳年龄/auth_status/今日统计）
	@python3 -c "import sys; sys.path.insert(0,'$(CORE)'); from runtime_state import RuntimeState; rs=RuntimeState('$(MONITOR_RUNTIME_DIR)'); import time; age=rs.heartbeat_age(); print(f\"auth_status : {rs.auth_status}\"); print(f\"心跳年龄    : {'无心跳' if age<0 else f'{int(age)} 秒'}\"); print(f\"monitor PID : {rs.read_pid()}\"); print(f\"消息游标    : {rs.msg_cursor}\"); print(f\"今日推送    : {rs.today_push_count()} 条\"); print(f\"运行统计    : {rs.stats()}\")"

logs: ## tail 当日日志
	@tail -f $(MONITOR_RUNTIME_DIR)/logs/$$(date +%Y%m%d).log

test: ## 运行外壳层全部单元测试
	@python3 -m unittest discover -s tests/monitor -v

# ---------- 登录恢复三级自愈 ----------

auth-input-code: ## 回传短信验证码: make auth-input-code CODE=123456
	@if [ -z "$(CODE)" ]; then echo "用法: make auth-input-code CODE=6位数字"; exit 2; fi
	@bash $(LOGIN)/auth_input_code.sh $(CODE)

captcha-test: ## 用存档样本离线回归滑块识别准确率
	@python3 $(LOGIN)/captcha_solver.py track 200 --seed 42

auth-local-login: ## 【本地电脑】有头登录 + 打包 profile
	@bash $(LOGIN)/auth_local_login.sh

auth-upload: ## 【本地电脑】上传 profile: make auth-upload HOST=user@server
	@if [ -z "$(HOST)" ]; then echo "用法: make auth-upload HOST=user@server"; exit 2; fi
	@ls -t hexun-profile-*.tar.gz 2>/dev/null | head -1 | xargs -I{} scp {} $(HOST):/home/zxh/projects/14.fupange/直播智能体/runtime/profile-incoming/

auth-verify: ## 【服务器】解压替换 profile + 无头验证清单（FR-6）
	@python3 $(MON)/verify_auth.py --runtime-dir $(MONITOR_RUNTIME_DIR)

auth-vnc-start: ## 【服务器】应急 noVNC 有头续期（临时端口，带一次性令牌）
	@bash $(LOGIN)/auth_vnc.sh start

auth-vnc-stop: ## 【服务器】关闭 noVNC
	@bash $(LOGIN)/auth_vnc.sh stop

# ---------- 飞书 bot 收图管线 ----------

bot-image-start: ## 启动 bot 收图管线（发图→Doubao 识别→引用回复）
	@if [ -f $(MONITOR_RUNTIME_DIR)/bot_image.pid ] && kill -0 $$(cat $(MONITOR_RUNTIME_DIR)/bot_image.pid) 2>/dev/null; then echo "已在运行 PID $$(cat $(MONITOR_RUNTIME_DIR)/bot_image.pid)"; exit 0; fi
	@setsid nohup python3 $(LARK)/bot_image_pipeline.py >/dev/null 2>&1 &
	@sleep 2; cat $(MONITOR_RUNTIME_DIR)/bot_image.pid 2>/dev/null | xargs -I{} echo "bot 收图管线已启动 PID {}"

bot-image-stop: ## 停止 bot 收图管线（按 PID 文件精确终止）
	@if [ -f $(MONITOR_RUNTIME_DIR)/bot_image.pid ]; then PID=$$(cat $(MONITOR_RUNTIME_DIR)/bot_image.pid); kill $$PID 2>/dev/null && echo "已停止 PID $$PID" || echo "进程不存在"; rm -f $(MONITOR_RUNTIME_DIR)/bot_image.pid; else echo "未在运行"; fi

bot-image-status: ## 查看收图管线状态与最近日志
	@if [ -f $(MONITOR_RUNTIME_DIR)/bot_image.pid ] && kill -0 $$(cat $(MONITOR_RUNTIME_DIR)/bot_image.pid) 2>/dev/null; then echo "运行中 PID $$(cat $(MONITOR_RUNTIME_DIR)/bot_image.pid)"; else echo "未运行"; fi
	@tail -5 $(MONITOR_RUNTIME_DIR)/logs/bot_image.log 2>/dev/null || true
