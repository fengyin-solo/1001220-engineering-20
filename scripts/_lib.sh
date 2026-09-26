#!/usr/bin/env bash
# 共享小工具：日志输出、端口探测、健康检查等待。
# 仅依赖 bash + python3（json 解析）+ curl，被 dev-up / seed / verify 包装脚本复用。

set -uo pipefail

RED=$'\033[31m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
BOLD=$'\033[1m'
RESET=$'\033[0m'

log()  { printf '%s\n' "${BOLD}[$(date +%H:%M:%S)]${RESET} $*"; }
ok()   { printf '%s\n' "${GREEN}✔${RESET} $*"; }
warn() { printf '%s\n' "${YELLOW}!${RESET} $*"; }
die()  { printf '%s\n' "${RED}✘ $*${RESET}" >&2; exit 1; }

# 端口是否已被监听；返回 0 表示已占用。兼容 ss / lsof / netstat，都没有时退回 python 探测。
port_in_use() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]${port}\$" && return 0
  elif command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$port" -sTCP:LISTEN -nP >/dev/null 2>&1 && return 0
  elif command -v netstat >/dev/null 2>&1; then
    netstat -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]${port}\$" && return 0
  fi
  python3 - "$port" <<'PY'
import socket, sys
port = int(sys.argv[1])
s = socket.socket()
s.settimeout(0.3)
try:
    s.connect(("127.0.0.1", port))
except OSError:
    sys.exit(1)
else:
    sys.exit(0)
finally:
    s.close()
PY
}

# 反复 GET 健康检查地址，直到 200 或超时。参数：url 最大等待秒数
wait_for_http() {
  local url="$1" timeout="${2:-60}" waited=0
  while [ "$waited" -lt "$timeout" ]; do
    if curl -fsS -m 3 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  return 1
}

# 不依赖 jq：用标准库读 JSON。用法：json_get <file> <dotted.path>
json_get() {
  python3 - "$1" "$2" <<'PY'
import json, sys

path, target = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)
for part in target.split("."):
    if isinstance(data, list):
        data = data[int(part)]
    else:
        data = data[part]
if isinstance(data, (dict, list)):
    print(json.dumps(data, ensure_ascii=False))
else:
    print(data)
PY
}
