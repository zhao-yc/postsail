#!/usr/bin/env bash
set -euo pipefail

# 从脚本自身定位项目，支持从编辑器、终端或项目子目录调用。
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${OMNIPOST_PYTHON:-$PROJECT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  printf '未找到项目 Python 环境：%s\n请先按 docs/install.md 创建 .venv，或设置 OMNIPOST_PYTHON。\n' "$PYTHON_BIN" >&2
  exit 1
fi

# 编辑器可能没有加载终端里的 Node 环境；仅在启动前端时尝试用户已有的版本管理器。
if [[ "${1:-}" == "start" && "${2:-all}" != "backend" ]]; then
  if [[ -n "${OMNIPOST_NODE_BIN:-}" ]]; then
    export PATH="$OMNIPOST_NODE_BIN:$PATH"
  fi
  if ! command -v npm >/dev/null 2>&1; then
    export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
    if [[ -s "$NVM_DIR/nvm.sh" ]]; then
      set +u
      source "$NVM_DIR/nvm.sh"
      nvm use --silent default >/dev/null
      set -u
    elif command -v fnm >/dev/null 2>&1; then
      eval "$(fnm env --shell bash)"
      fnm use >/dev/null
    fi
  fi
  if ! command -v npm >/dev/null 2>&1; then
    printf '未找到 npm，请安装 Node.js 18+，或将 OMNIPOST_NODE_BIN 设置为 Node 可执行文件所在目录。\n' >&2
    exit 1
  fi
fi

exec "$PYTHON_BIN" "$PROJECT_DIR/.codex/scripts/dev.py" "$@"
