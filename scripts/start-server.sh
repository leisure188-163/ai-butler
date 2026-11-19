#!/usr/bin/env bash
# butler server 启动脚本（macOS / Linux）——与 scripts/start-server.ps1 同口径
# 数据根：项目内 data/database/butler.db（2026-11-19 用户裁决统一到这里；
# 平台默认根 ~/Library/Application Support/butler 的库已迁入并清理，
# 网关与主控必须共用同一 BUTLER_DB，否则账户/计量 split-brain）
# 用法：bash scripts/start-server.sh   （可追加 uvicorn 参数，如 --reload）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export BUTLER_DB="$ROOT/data/database/butler.db"

# 豆包身份簿：项目内有就钉住（与 Windows 脚本同口径），没有则沿用连接器缺省
if [ -f "$ROOT/data/doubao_identity.json" ]; then
  export DOUBAO_IDENTITY_PATH="$ROOT/data/doubao_identity.json"
fi

# 豆包 CDP 端口自动探测（2026-11-18）：mac 上豆包常以非 9222 端口启动，
# 连接器缺省读 9222 会让签到卡 PENDING「调试端口不可达」。
# 显式设了 DOUBAO_CDP_PORT 就不动。
if [ -z "${DOUBAO_CDP_PORT:-}" ]; then
  port="$(ps ax -o command= 2>/dev/null | grep -i "Doubao" | grep -o "remote-debugging-port=[0-9]*" | head -1 | cut -d= -f2 || true)"
  if [ -n "${port:-}" ]; then
    export DOUBAO_CDP_PORT="$port"
    echo "豆包 CDP 端口自动探测: $port"
  fi
fi

cd "$ROOT"
exec uv run python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 "$@"
