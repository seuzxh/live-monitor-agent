#!/usr/bin/env bash
# 打包本地浏览器 profile（Cookie 续期 SOP 路径 A，spec FR-4）
# 在【本地电脑】执行：登录成功后打包 user-data-dir，供 scp 上传服务器
# 排除 Chromium 锁文件，校验打包完整性
set -eu

if [ $# -lt 1 ]; then
  echo "用法: $0 <profile目录> [输出文件]" >&2
  exit 2
fi

PROFILE_DIR="$1"
STAMP=$(date +%Y%m%d-%H%M%S)
OUT="${2:-hexun-profile-${STAMP}.tar.gz}"

if [ ! -d "$PROFILE_DIR" ]; then
  echo "ERROR: profile 目录不存在: $PROFILE_DIR" >&2
  exit 1
fi

# 确认没有浏览器进程占用 profile（锁文件存在 = 浏览器可能未关闭）
if ls "$PROFILE_DIR"/Singleton* >/dev/null 2>&1; then
  echo "ERROR: 检测到 Chromium 锁文件（Singleton*），请先完全关闭浏览器再打包" >&2
  exit 1
fi

# 排除锁文件与缓存垃圾，保留 Cookie/Local Storage/会话
tar -czf "$OUT" \
  --exclude='Singleton*' \
  --exclude='*/Cache/*' \
  --exclude='*/Code Cache/*' \
  --exclude='*.tmp' \
  -C "$(dirname "$PROFILE_DIR")" \
  "$(basename "$PROFILE_DIR")"

# 校验：包内必须含 Cookies 文件
if tar -tzf "$OUT" | grep -qE '(Cookies$|/Cookies$)'; then
  SIZE=$(du -h "$OUT" | cut -f1)
  echo "OK: 已打包 $OUT（含 Cookies，大小 $SIZE）"
  echo "下一步: scp $OUT <服务器>:/home/zxh/projects/14.fupange/直播智能体/runtime/profile-incoming/ 然后服务器执行 make auth-verify"
else
  echo "ERROR: 包内未找到 Cookies 文件，profile 可能无效" >&2
  rm -f "$OUT"
  exit 1
fi
