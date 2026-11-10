#!/bin/bash
# 安全入口：独立实验模式、指定二进制、仅终止本次子进程。
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
BIN=/mnt/data2/desk-pet-build/target-ghost/release/desk-pet
if ! test -x "$BIN"; then echo "尚无实验二进制：$BIN" >&2; exit 1; fi
export DESK_PET_ASSETS="$ROOT/assets" DESK_PET_DEBUG=1 DESK_PET_GHOST=1
"$BIN" > "$ROOT/ghost-report/tauri.log" 2>&1 &
PET_PID=$!
trap 'kill "$PET_PID" 2>/dev/null || true; wait "$PET_PID" 2>/dev/null || true' EXIT INT TERM
# 仅启动；避免旧脚本的全局 pkill 和未加锁鼠标操作。
echo "实验进程 PID=$PET_PID；窗口位于 DP-0。Ctrl-C 结束。"
wait "$PET_PID"
