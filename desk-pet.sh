#!/bin/sh
# 启动桌宠（已在跑就不重复开）。放大：DESK_PET_SCALE=2 ./desk-pet.sh
pgrep -x desk-pet >/dev/null && exit 0
BIN=${CARGO_TARGET_DIR:-/mnt/data2/desk-pet-build/target}/release/desk-pet
nohup "$BIN" >/dev/null 2>&1 &
