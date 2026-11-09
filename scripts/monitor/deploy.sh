#!/usr/bin/env bash
# 完整部署脚本（spec FR-11 make deploy / NFR-1）
# 在【服务器】首次执行：系统依赖 → traecli → Playwright → venv(ddddocr) → 目录结构
set -eu

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "===== [1/5] 系统依赖 ====="
sudo apt update
sudo apt install -y python3 python3-pip python3-venv jq curl

echo "===== [2/5] TraeCode CLI ====="
if ! command -v traecli >/dev/null 2>&1; then
  sh -c "$(curl -L https://trae.cn/trae-cli/install.sh)"
  echo 'export PATH=$HOME/.local/bin:$PATH' >> ~/.bashrc
  export PATH="$HOME/.local/bin:$PATH"
fi
traecli --version || true
echo "如未认证，按 docs/ops/deploy.md 第③步写入 ~/.config/trae-cli/credentials.env（PAT 环境变量注入，本版本无 login 子命令）"

echo "===== [3/5] Playwright 无头浏览器 ====="
pip3 install playwright
playwright install --with-deps chromium

echo "===== [4/5] captcha_solver venv（ddddocr 隔离安装，NFR-3 例外） ====="
python3 -m venv scripts/monitor/.venv
scripts/monitor/.venv/bin/pip install --upgrade pip
scripts/monitor/.venv/bin/pip install ddddocr

echo "===== [5/5] 运行时目录 ====="
mkdir -p runtime/{pushes,snapshots,logs}
mkdir -p runtime/profile-incoming

echo "===== 部署完成 ====="
echo "后续: ① 配置 memory.md（手机号+webhook）② 配置 PAT 凭据文件（见 docs/ops/deploy.md 第③步） ③ make preflight 验证"
