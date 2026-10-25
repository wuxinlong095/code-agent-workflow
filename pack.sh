#!/usr/bin/env bash
# 打包备份：学号姓名.rar（小于 200M）；无 rar 时退化为 zip
set -euo pipefail
cd "$(dirname "$0")/.."
NAME="2412190603_吴鑫龙"

RAR_BIN=""
if command -v rar >/dev/null 2>&1; then
  RAR_BIN="rar"
elif [ -x "/c/Program Files/WinRAR/Rar.exe" ]; then
  RAR_BIN="/c/Program Files/WinRAR/Rar.exe"
fi

if [ -n "$RAR_BIN" ]; then
  "$RAR_BIN" a -r -ep1 "${NAME}.rar" "code-agent-workflow" \
    -x'.git' -x'__pycache__' -x'runs' -x'*.pyc' -x'*.rar' >/dev/null
  echo "已生成：$(pwd)/${NAME}.rar"
else
  echo "未检测到 rar，改用 zip（提交前可用 WinRAR 另存为 .rar）"
  zip -rq "${NAME}.zip" "code-agent-workflow" \
    -x 'code-agent-workflow/.git/*' -x '*/__pycache__/*' -x 'code-agent-workflow/runs/*'
  echo "已生成：$(pwd)/${NAME}.zip"
fi
