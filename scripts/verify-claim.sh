#!/usr/bin/env bash
# 理赔复核的薄封装：默认同时核对后端直连与前端代理，参数原样透传给 verify-claim.py。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_lib.sh

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

exec python3 scripts/verify-claim.py \
  --backend-base-url "http://127.0.0.1:${BACKEND_PORT}" \
  --frontend-base-url "http://127.0.0.1:${FRONTEND_PORT}" \
  "$@"
