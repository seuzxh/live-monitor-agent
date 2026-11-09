# scripts/monitor 目录索引

按功能分四组，各脚本功能详述见 `docs/脚本功能说明.md`。

- 顶层：`preflight.sh`（预检）、`force_cleanup.sh`（回收）、`deploy.sh`（部署）——cron/make 直接调用
- `core/`：`monitor_poll.py`（生产主程序：轮询+LLM分类推送）、`runtime_state.py`（状态基础件）
- `login/`：`captcha_solver.py`、`verify_auth.py`、`auth_input_code.sh`、`auth_local_login.sh`、`auth_vnc.sh`、`profile_pack.sh`
- `legacy-agent/`：`launcher.py`、`watchdog.py`（常驻 agent 备用件）

`.venv/` 仅装 ddddocr（git 忽略；搬迁后重建：`python3 -m venv scripts/monitor/.venv && scripts/monitor/.venv/bin/pip install ddddocr`）。
