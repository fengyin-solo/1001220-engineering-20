#!/usr/bin/env bash
# 一条命令拉起本地前后端（构建产物模式）：
#   make install   首次：安装前后端依赖
#   make build     构建前端到 frontend/dist
#   make start     启动后端(8000) + 前端 preview(5173)
#
# 依赖缺失或端口被占用会在起服务前直接报错退出，不会留下半截进程。
# 运行日志写在 .run/backend.log 与 .run/frontend.log。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT=8000
FRONTEND_PORT=5173
RUN_DIR="$ROOT/.run"

red() { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
die() { red "✗ $*"; exit 1; }

# 1) 依赖检查 —— 在起任何进程之前拦清楚 ------------------------------------------------

command -v python3 >/dev/null 2>&1 \
  || die "未找到 python3，请先安装 Python 3.10+（后端运行时）"
command -v npm >/dev/null 2>&1 \
  || die "未找到 npm，请先安装 Node.js 18+（前端运行时）"

[ -x "$ROOT/backend/.venv/bin/uvicorn" ] \
  || die "后端依赖未安装：请先执行 make install（会创建 backend/.venv 并安装 requirements.txt）"

[ -d "$ROOT/frontend/node_modules/vite" ] \
  || die "前端依赖未安装：请先执行 make install（会安装 frontend/node_modules）"

[ -d "$ROOT/frontend/dist" ] \
  || die "前端尚未构建：请先执行 make build；需要热更新调试可改用 make frontend"

# 2) 端口占用检查 --------------------------------------------------------------------

port_in_use() {
  # 只依赖标准库，避免机器上没有 lsof/ss 时检查失效
  python3 - "$1" <<'PY'
import socket, sys
sock = socket.socket()
sock.settimeout(0.3)
try:
    sock.connect(("127.0.0.1", int(sys.argv[1])))
except OSError:
    sys.exit(1)  # 没人监听 → 端口空闲
else:
    sys.exit(0)  # 连接成功 → 已被占用
finally:
    sock.close()
PY
}

port_owner_hint() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | tail -n +2 || true
  elif command -v ss >/dev/null 2>&1; then
    ss -ltnp 2>/dev/null | grep ":$port " || true
  fi
}

check_port() {
  local port="$1" name="$2"
  if port_in_use "$port"; then
    red "✗ 端口 ${port} 已被占用，${name}无法启动。"
    local hint
    hint="$(port_owner_hint "$port")"
    [ -n "$hint" ] && printf '  占用进程信息：\n%s\n' "$hint"
    die "请先停掉占用 ${port} 的进程，再执行 make start"
  fi
}

check_port "$BACKEND_PORT" "后端服务"
check_port "$FRONTEND_PORT" "前端服务"

# 3) 拉起两个服务 ---------------------------------------------------------------------

mkdir -p "$RUN_DIR"
PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  rm -f "$RUN_DIR"/*.pid
}
trap cleanup EXIT INT TERM

# 后端是内存数据仓库：每次启动都会按 app/seed.py 重新写入示例数据，
# 所以「改了种子数据忘记同步」在重启后端后天然生效。
(
  cd "$ROOT/backend"
  exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
) >"$RUN_DIR/backend.log" 2>&1 &
PIDS+=("$!")
echo "$!" >"$RUN_DIR/backend.pid"

wait_for_http() {
  python3 - "$1" "$2" <<'PY'
import sys, time, urllib.request
url, timeout = sys.argv[1], float(sys.argv[2])
deadline = time.time() + timeout
while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=1) as resp:
            if resp.status < 500:
                sys.exit(0)
    except Exception:
        time.sleep(0.3)
sys.exit(1)
PY
}

show_log_tail() {
  local log="$1"
  red "  最近日志（$log）："
  tail -n 20 "$log" 2>/dev/null | sed 's/^/    /' >&2 || true
}

if ! wait_for_http "http://127.0.0.1:${BACKEND_PORT}/api/health" 20; then
  red "✗ 后端在 20 秒内未通过健康检查"
  show_log_tail "$RUN_DIR/backend.log"
  exit 1
fi
green "✓ 后端已启动：http://127.0.0.1:${BACKEND_PORT}（健康检查 GET /api/health）"

# 直接 exec vite，避免 npm 包一层导致 Ctrl+C 后残留子进程
(
  cd "$ROOT/frontend"
  exec node_modules/.bin/vite preview --strictPort
) >"$RUN_DIR/frontend.log" 2>&1 &
PIDS+=("$!")
echo "$!" >"$RUN_DIR/frontend.pid"

if ! wait_for_http "http://127.0.0.1:${FRONTEND_PORT}/" 20; then
  red "✗ 前端在 20 秒内未就绪"
  show_log_tail "$RUN_DIR/frontend.log"
  exit 1
fi
green "✓ 前端已启动：http://127.0.0.1:${FRONTEND_PORT}（构建产物，/api 代理到 ${BACKEND_PORT}）"

cat <<EOF

事故记录链路（待上报 → 已上报 → 理赔中 → 已结案）：
  1. 浏览器打开 http://127.0.0.1:${FRONTEND_PORT}/accident 手工点一遍
  2. 另开终端执行 make check，脚本会调接口走完整条链路并核对理赔结论

按 Ctrl+C 同时停止前后端。
EOF

wait
