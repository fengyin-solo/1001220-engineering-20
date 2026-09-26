#!/usr/bin/env bash
# 事故链路示例数据：通过后端接口创建一条事故，并依次走完
#   事故上报 -> 损失核定 -> 保险理赔（启动理赔 -> 理赔到账）
# 每一步都校验返回状态，最后把事故 id 写入 .run/accident-demo.json，供 verify-claim 复核。
#
# 用法：scripts/seed-accident-demo.sh [--base-url http://127.0.0.1:8000]
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=_lib.sh
source scripts/_lib.sh

BASE_URL="http://127.0.0.1:${BACKEND_PORT:-8000}"
while [ $# -gt 0 ]; do
  case "$1" in
    --base-url) BASE_URL="$2"; shift 2 ;;
    *) die "未知参数：$1（支持 --base-url）" ;;
  esac
done

ENDPOINT="$BASE_URL/api/accident"
RUN_DIR=".run"
mkdir -p "$RUN_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 事故编号带时间戳，重复执行也不会撞号
STAMP="$(date +%m%d%H%M)"
ACC_NO="ACCI-DEMO-${STAMP}"

log "① 登记事故（待上报）：${ACC_NO}"
cat >"$TMP/create.json" <<JSON
{"values": {
  "事故编号": "${ACC_NO}",
  "关联任务": "DOOR-DEMO-${STAMP}",
  "事故类型": "冷链超温",
  "发生时间": "$(date '+%Y-%m-%d %H:%M')",
  "事故描述": "示例链路：制冷机组停机导致温区超温，冻品批量变质",
  "损失金额": 0,
  "保险理赔": "未报案"
}}
JSON
curl -fsS -m 10 -X POST "$ENDPOINT" \
  -H 'Content-Type: application/json' -d @"$TMP/create.json" >"$TMP/create.resp"
[ "$(json_get "$TMP/create.resp" ok)" = "True" ] || die "登记事故失败：$(cat "$TMP/create.resp")"
ACC_ID="$(json_get "$TMP/create.resp" entry.id)"
ok "事故已登记 id=${ACC_ID}，状态=$(json_get "$TMP/create.resp" entry.status)"

post_action() {
  local step="$1" action="$2" body="$3" expect="$4"
  log "$step 执行「${action}」，期望状态：${expect}"
  printf '%s' "$body" >"$TMP/action.json"
  curl -fsS -m 10 -X POST "$ENDPOINT/${ACC_ID}/actions" \
    -H 'Content-Type: application/json' -d @"$TMP/action.json" >"$TMP/action.resp"
  if [ "$(json_get "$TMP/action.resp" ok)" != "True" ]; then
    die "「${action}」被后端拒绝：$(json_get "$TMP/action.resp" message)"
  fi
  local got
  got="$(json_get "$TMP/action.resp" entry.status)"
  [ "$got" = "$expect" ] || die "「${action}」后状态应为「${expect}」，实际「${got}」"
  ok "状态流转到「${got}」"
}

post_action "② 事故上报" "上报事故" \
  '{"values": {"action": "上报事故", "事故描述": "示例链路：司机已现场取证并向保险公司报案"}}' \
  "已上报"

post_action "③ 损失核定" "损失核定" \
  '{"values": {"action": "损失核定", "损失金额": 12000, "事故描述": "示例链路：冻品货损 12000 元，发票与质检单齐全"}}' \
  "待理赔"

post_action "④ 保险理赔" "启动理赔" \
  '{"values": {"action": "启动理赔", "保险理赔": "理赔材料已提交，等待保险公司审核"}}' \
  "理赔中"

# 保险按 80% 赔付：12000 -> 9600
post_action "⑤ 理赔到账" "理赔到账" \
  '{"values": {"action": "理赔到账", "赔付金额": 9600, "理赔结论": "保险已赔付", "保险理赔": "已到账 9600 元"}}' \
  "已理赔"

LOSS="$(json_get "$TMP/action.resp" entry.损失金额)"
PAYOUT="$(json_get "$TMP/action.resp" entry.赔付金额)"
CONCLUSION="$(json_get "$TMP/action.resp" entry.理赔结论)"

cat >"$RUN_DIR/accident-demo.json" <<JSON
{
  "id": ${ACC_ID},
  "事故编号": "${ACC_NO}",
  "base_url": "${BASE_URL}",
  "损失金额": ${LOSS},
  "赔付金额": ${PAYOUT},
  "理赔结论": "${CONCLUSION}",
  "终态": "已理赔",
  "created_at": "$(date '+%Y-%m-%d %H:%M:%S')"
}
JSON
ok "示例链路数据已写入 $RUN_DIR/accident-demo.json"
warn "可用 scripts/verify-claim.sh 复核理赔结论与接口返回是否一致"
