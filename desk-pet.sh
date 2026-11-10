#!/bin/sh
# 启动桌宠（已在跑就不重复开）。放大：DESK_PET_SCALE=2 ./desk-pet.sh
cd "$(dirname "$0")"
PIDF=${XDG_RUNTIME_DIR:-/tmp}/desk-pet.pid
[ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null && exit 0
nohup /mnt/data2/desk-pet-build/venv/bin/python pet.py >/dev/null 2>&1 &
echo $! > "$PIDF"
