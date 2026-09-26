#!/usr/bin/env bash
# 启动后端：自动准备虚拟环境与依赖（venv 不可用时走 get-pip 在线引导），然后 uvicorn 拉起。
# 端口可用 BACKEND_PORT 覆盖（scripts/dev-up.sh 联动用），默认 8000。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HOST="${BACKEND_HOST:-127.0.0.1}"
PORT="${BACKEND_PORT:-8000}"

python3 scripts/ensure-backend-env.py
exec backend/.venv/bin/uvicorn --app-dir backend app.main:app --host "$HOST" --port "$PORT"
