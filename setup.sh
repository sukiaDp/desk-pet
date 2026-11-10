#!/bin/sh
# 建 Python 3.12 venv 并装 PySide6（放在 /mnt/data2，不占系统盘）。
# 必须 3.12+：PySide6 6.12 在 3.10 上会因 None 引用计数 bug 崩溃（none_dealloc）。
set -e
V=/mnt/data2/desk-pet-build/venv
python3.12 -m venv "$V"
PIP_CACHE_DIR=/mnt/data2/desk-pet-build/pip-cache "$V/bin/pip" install -q PySide6-Essentials
