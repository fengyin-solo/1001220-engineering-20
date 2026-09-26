#!/usr/bin/env bash
# 停止 dev-up.sh 拉起的前后端进程。
# 先按 .run 下记录的 PID（进程组）回收；PID 文件缺失或被覆盖时，
# 再按监听端口与本项目的 uvicorn/vite 命令行兜底，保证不会留下脱管进程。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_lib.sh

RUN_DIR=".run"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

kill_pid_group() {
  local pid="$1" label="$2"
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 10); do
      kill -0 "$pid" 2>/dev/null || { ok "${label}进程 ${pid} 已停止"; return; }
      sleep 0.3
    done
    kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    ok "${label}进程 ${pid} 已强制结束"
  fi
}

# 找监听某端口的进程 PID（取本机 TCP LISTEN 行）
pid_on_port() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp 2>/dev/null | awk -v p=":${port}" '$4 ~ p"$" {print $0}' \
      | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | sort -u
  fi
}

# 1) 先回收 PID 文件记录的进程组
for name in frontend backend; do
  pid_file="$RUN_DIR/$name.pid"
  if [ -f "$pid_file" ]; then
    kill_pid_group "$(cat "$pid_file")" "$name"
    rm -f "$pid_file"
  fi
done

# 2) 兜底：端口仍被占用时（PID 文件被换端口的 dev-up 覆盖等场景）按端口回收
for spec in "${BACKEND_PORT}:后端(uvicorn)" "${FRONTEND_PORT}:前端(vite)"; do
  port="${spec%%:*}"; label="${spec##*:}"
  if port_in_use "$port"; then
    warn "端口 ${port} 仍被占用，按监听进程兜底回收（${label}）"
    for pid in $(pid_on_port "$port"); do
      kill_pid_group "$pid" "$label:$port"
    done
  fi
done

# 3) 最后扫一遍本项目目录下可能残留的 uvicorn/vite 子进程
leftover="$(pgrep -f "uvicorn --app-dir backend app.main:app|frontend/node_modules/.bin/vite" 2>/dev/null || true)"
if [ -n "$leftover" ]; then
  warn "发现脱管的本项目服务进程：$(echo "$leftover" | tr '\n' ' ')"
  for pid in $leftover; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  sleep 1
  for pid in $leftover; do
    kill -KILL "$pid" 2>/dev/null || true
  done
  ok "脱管进程已清理"
fi

warn "日志与示例数据保留在 $RUN_DIR/，删除即可彻底清理"
