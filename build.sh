#!/bin/sh
# 构建（工具链和产物都在 /mnt/data2/desk-pet-build）
. /mnt/data2/desk-pet-build/env.sh && cd "$(dirname "$0")/src-tauri" && cargo build --release
