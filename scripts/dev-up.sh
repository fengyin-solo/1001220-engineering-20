#!/usr/bin/env bash
# 一条命令拉起本地联调环境：
#   1. 预检依赖（python3 / venv、node、npm、curl）与端口占用；
#   2. 安装后端（.venv）与前端（node_modules）依赖；
#   3. 构建前端（vue-tsc 类型检查 + vite build），提前暴露编译问题；
#   4. 后台拉起后端 uvicorn 与前端 vite dev server；
#   5. 通过接口灌入「待上报 -> 已上报 -> 待理赔 -> 理赔中 -> 已理赔」示例事故。
#
# 停止：make dev-down（scripts/dev-down.sh）
# 复核理赔：make verify（scripts/verify-claim.sh）
#
# 可用环境变量换端口：BACKEND_PORT=8010 FRONTEND_PORT=5180 scripts/dev-up.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_lib.sh

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
RUN_DIR=".run"
BACKEND_PID="$RUN_DIR/backend.pid"
FRONTEND_PID="$RUN_DIR/frontend.pid"
BACKEND_LOG="$RUN_DIR/backend.log"
FRONTEND_LOG="$RUN_DIR/frontend.log"

# ---------------------------------------------------------------- 预检
log "预检运行环境…"

need() {
  command -v "$1" >/dev/null 2>&1 || die "缺少依赖：$1。$2"
}
need python3 "请先安装 Python 3.10+（Debian/Ubuntu 还需 apt install python3-venv）。"
need node "请先安装 Node.js 18+：https://nodejs.org/"
need npm "Node.js 安装应自带 npm，请检查 PATH。"
need curl "请先安装 curl（apt install curl）。"

node_major="$(node -p 'process.versions.node.split(".")[0]')"
[ "$node_major" -ge 18 ] || die "Node.js 版本过低（当前 $(node -v)），需要 18 及以上。"

# python venv 在 Debian 精简镜像上常缺 ensurepip：这里只提示不拦截，
# ensure-backend-env.py 会再尝试 get-pip.py 在线引导
if ! python3 -c 'import venv, ensurepip' >/dev/null 2>&1; then
  warn "Python 标准库 venv/ensurepip 不可用（Debian/Ubuntu 可 apt install python3-venv）"
  warn "稍后将尝试用 get-pip.py 在线引导；如引导失败请先装 python3-venv"
fi

check_port() {
  local port="$1" label="$2" pid_file="$3"
  if port_in_use "$port"; then
    if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
      die "${label}端口 ${port} 已被本脚本启动的服务占用，如需重启请先执行 make dev-down。"
    fi
    die "${label}端口 ${port} 已被其他进程占用。可查监听进程后释放，或换端口启动：
  BACKEND_PORT=8010 FRONTEND_PORT=5180 scripts/dev-up.sh"
  fi
}
check_port "$BACKEND_PORT" "后端" "$BACKEND_PID"
check_port "$FRONTEND_PORT" "前端" "$FRONTEND_PID"
ok "依赖与端口检查通过（后端 :${BACKEND_PORT}，前端 :${FRONTEND_PORT}）"

# 若上次异常退出残留 PID 文件，先清掉，避免新进程被误判
mkdir -p "$RUN_DIR"
rm -f "$BACKEND_PID" "$FRONTEND_PID"

cleanup_on_fail() {
  warn "启动中断，回收已拉起的进程…"
  [ -f "$FRONTEND_PID" ] && kill -TERM -- "-$(cat "$FRONTEND_PID")" 2>/dev/null || true
  [ -f "$BACKEND_PID" ] && kill -TERM -- "-$(cat "$BACKEND_PID")" 2>/dev/null || true
  exit 1
}
trap cleanup_on_fail ERR

# ---------------------------------------------------------------- 依赖安装
log "准备后端 Python 环境（backend/.venv + requirements）…"
python3 scripts/ensure-backend-env.py || die "后端环境准备失败，请按上面的提示修复后重试。"
ok "后端依赖就绪：$(backend/.venv/bin/python -c 'import fastapi;print("fastapi", fastapi.__version__)')"

log "安装前端依赖（frontend/node_modules）…"
if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm install) || die "前端依赖安装失败，可见上方 npm 输出。"
else
  ok "frontend/node_modules 已存在，跳过安装（如遇依赖异常可删除后重跑）"
fi

# ---------------------------------------------------------------- 前端构建
log "构建前端（vue-tsc 类型检查 + vite build）…"
(cd frontend && npm run build) >"$RUN_DIR/frontend-build.log" 2>&1 \
  || { tail -n 30 "$RUN_DIR/frontend-build.log" >&2 || true; die "前端构建失败，完整日志见 $RUN_DIR/frontend-build.log"; }
ok "前端构建通过，产物在 frontend/dist"

# ---------------------------------------------------------------- 拉起服务
log "拉起后端 uvicorn（日志：$BACKEND_LOG）…"
# setsid 让服务成为新进程组组长，dev-down 可整组回收（uvicorn 重载子进程等）
setsid env BACKEND_HOST=127.0.0.1 BACKEND_PORT="$BACKEND_PORT" \
  backend/.venv/bin/uvicorn --app-dir backend app.main:app \
  --host 127.0.0.1 --port "$BACKEND_PORT" >"$BACKEND_LOG" 2>&1 &
echo $! >"$BACKEND_PID"

if ! wait_for_http "http://127.0.0.1:${BACKEND_PORT}/api/health" 60; then
  tail -n 30 "$BACKEND_LOG" >&2 || true
  die "后端 60s 内未通过健康检查，见 $BACKEND_LOG"
fi
ok "后端就绪：http://127.0.0.1:${BACKEND_PORT}（/api/health）"

log "拉起前端 vite dev server（日志：$FRONTEND_LOG）…"
setsid env VITE_PORT="$FRONTEND_PORT" VITE_PROXY_TARGET="http://127.0.0.1:${BACKEND_PORT}" \
  npm --prefix frontend run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" \
  >"$FRONTEND_LOG" 2>&1 &
echo $! >"$FRONTEND_PID"

if ! wait_for_http "http://127.0.0.1:${FRONTEND_PORT}/" 60; then
  tail -n 30 "$FRONTEND_LOG" >&2 || true
  die "前端 dev server 60s 内未就绪，见 $FRONTEND_LOG"
fi
# 代理是否真的打到后端
if ! wait_for_http "http://127.0.0.1:${FRONTEND_PORT}/api/health" 30; then
  die "前端已起，但 /api 代理到后端失败，请检查 VITE_PROXY_TARGET 与后端状态。"
fi
ok "前端就绪：http://127.0.0.1:${FRONTEND_PORT}（/api 已代理到后端）"

# ---------------------------------------------------------------- 灌示例链路
log "通过接口写入事故理赔示例链路（待上报 → 已上报 → 待理赔 → 理赔中 → 已理赔）…"
BACKEND_PORT="$BACKEND_PORT" scripts/seed-accident-demo.sh \
  --base-url "http://127.0.0.1:${BACKEND_PORT}"

trap - ERR

echo
ok "联调环境已就绪："
echo "  前端页面  http://127.0.0.1:${FRONTEND_PORT}/accident"
echo "  后端接口  http://127.0.0.1:${BACKEND_PORT}/api/accident"
echo "  停止服务  make dev-down"
echo "  理赔复核  make verify"
