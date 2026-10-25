#!/usr/bin/env bash
# 自动探测可用的 Python 3.10+ 后执行参数里的命令
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

if [ -n "${PY_BIN:-}" ]; then
  CANDIDATES=("$PY_BIN")
else
  CANDIDATES=(
    "$HOME/AppData/Local/Programs/Python/Python312/python.exe"
    python3
    python
    py
  )
fi

for candidate in "${CANDIDATES[@]}"; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
      exec "$candidate" "$@"
    fi
  fi
done

echo "未找到 Python 3.10+。可显式指定，例如：" >&2
echo "  export PY_BIN=/c/Users/49158/AppData/Local/Programs/Python/Python312/python.exe" >&2
exit 1
