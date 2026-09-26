#!/usr/bin/env python3
"""事故记录链路可复现检查脚本。

做两件事：
1. 校验示例数据覆盖四个状态（待上报、已上报、理赔中、已结案），
   且事故编号、事故类型、损失金额字段齐全；
2. 调接口把一条新事故从头走到尾：上报事故 → 启动理赔（损失核定）
   → 结案归档（写入保险理赔结论），再分别用 GET 详情和状态过滤列表
   核对接口返回与理赔结论一致。

用法：
    make check
    python3 scripts/check_accident_flow.py
    API_BASE=http://127.0.0.1:8000 python3 scripts/check_accident_flow.py

任一校验不通过都会打印 ✗ 并以非 0 退出；全部通过打印 ✓ 汇总。
只依赖 Python 标准库，不需要进入虚拟环境。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000").rstrip("/")
ENDPOINT = f"{BASE}/api/accident"
STATUSES = ["待上报", "已上报", "理赔中", "已结案"]

# 检查脚本专用的一组可复现数据：编号固定，金额固定，理赔结论固定
CHECK_NO = "ACCI-CHECK"
ACCIDENT_TYPE = "温控失效货损"
INITIAL_LOSS = 20000.0
# 损失核定：剔除免责部分后核定金额
ASSESSED_LOSS = 18000.0
# 理赔结论：结案时写回「保险理赔」字段，后续所有核对都以此为准
CLAIM_RESULT = f"已结案，保险已赔付 {ASSESSED_LOSS:.1f} 元"

failures: list[str] = []
passed = 0


def ok(message: str) -> None:
    global passed
    passed += 1
    print(f"  ✓ {message}")


def fail(message: str) -> None:
    failures.append(message)
    print(f"  ✗ {message}")


def request(method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def must(condition: bool, success: str, error: str) -> bool:
    if condition:
        ok(success)
        return True
    fail(error)
    return False


def wait_for_backend() -> None:
    print(f"检查后端：{BASE}/api/health")
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            status, body = request("GET", f"{BASE}/api/health")
            if status == 200 and body.get("ok"):
                ok("后端健康检查通过，示例数据已就绪")
                return
        except Exception:
            pass
        time.sleep(0.5)
    fail(f"后端 {BASE} 未就绪，请先执行 make start（或单独启动 backend/run.sh）")
    sys.exit(1)


def check_seed_data() -> None:
    print("检查示例数据：事故记录需覆盖完整状态链")
    status, body = request("GET", f"{ENDPOINT}?size=200")
    if not must(status == 200, "事故列表接口可访问", f"事故列表接口返回 {status}"):
        return
    rows = body.get("items", [])
    by_number = {row.get("事故编号"): row for row in rows}

    # 精确核对种子数据 ACCI-0001..4 的四态链，不受检查脚本自身写入记录的影响
    for index, stage in enumerate(STATUSES, start=1):
        number = f"ACCI-{index:04d}"
        row = by_number.get(number)
        if not must(row is not None, f"示例数据包含 {number}（{stage}）", f"示例数据缺少 {number}"):
            continue
        if not must(
            row.get("status") == stage,
            f"{number} 状态为「{stage}」",
            f"{number} 状态应为「{stage}」，实际「{row.get('status')}」",
        ):
            continue
        missing = [
            field
            for field in ("事故编号", "事故类型", "损失金额")
            if row.get(field) in (None, "")
        ]
        must(
            not missing,
            f"{number} 的事故编号/事故类型/损失金额齐全（{row.get('事故类型')}，{row.get('损失金额')} 元）",
            f"{number} 缺少字段：{missing}",
        )

    seed_closed = by_number.get("ACCI-0004")
    must(
        seed_closed is not None and str(seed_closed.get("保险理赔", "")).strip() != "",
        f"已结案示例 ACCI-0004 带理赔结论：{seed_closed.get('保险理赔') if seed_closed else None}",
        "已结案示例 ACCI-0004 的「保险理赔」为空，理赔结论缺失",
    )


def run_full_chain() -> None:
    print("走查完整链路：登记 → 上报事故 → 启动理赔（损失核定）→ 结案归档（保险理赔）")

    status, body = request("POST", ENDPOINT, {
        "values": {
            "事故编号": CHECK_NO,
            "关联任务": "DISP-CHECK",
            "事故类型": ACCIDENT_TYPE,
            "发生时间": "2026-09-26 10:00",
            "事故描述": "检查脚本构造的温控失效事故，用于可复现核对理赔结论",
            "损失金额": INITIAL_LOSS,
            "保险理赔": "未报案",
        }
    })
    if not must(
        status == 200 and body.get("ok") and body.get("entry"),
        "登记事故记录成功（初始状态：待上报）",
        f"登记事故记录失败：{body}",
    ):
        return
    entry = body["entry"]
    entry_id = entry["id"]

    if not must(
        entry.get("status") == "待上报" and entry.get("损失金额") == INITIAL_LOSS,
        f"初始损失金额 {INITIAL_LOSS} 已随登记落库",
        f"登记返回与预期不符：{entry}",
    ):
        return

    def act(action: str, expect: str, extra: dict | None = None) -> dict | None:
        values = {"action": action, **(extra or {})}
        code, result = request("POST", f"{ENDPOINT}/{entry_id}/actions", {"values": values})
        if code != 200 or not result.get("ok"):
            fail(f"动作「{action}」失败：{result}")
            return None
        got = result["entry"]["status"]
        if got != expect:
            fail(f"动作「{action}」后状态应为「{expect}」，接口返回「{got}」")
            return None
        ok(f"「{action}」生效，状态流转为「{expect}」")
        return result["entry"]

    entry = act("上报事故", "已上报")
    if entry is None:
        return

    entry = act("启动理赔", "理赔中", {"损失金额": ASSESSED_LOSS})
    if not must(
        entry is not None and entry.get("损失金额") == ASSESSED_LOSS,
        f"损失核定金额 {ASSESSED_LOSS} 已写回记录",
        f"损失核定未落库：{entry}",
    ):
        return

    entry = act("结案归档", "已结案", {"保险理赔": CLAIM_RESULT})
    if not must(
        entry is not None and entry.get("保险理赔") == CLAIM_RESULT,
        f"理赔结论已写回：{CLAIM_RESULT}",
        f"理赔结论未落库：{entry}",
    ):
        return
    if entry is not None:
        must(
            entry.get("pending") is False,
            "已结案记录不再计入待处理",
            f"已结案记录 pending 应为 false，实际：{entry.get('pending')}",
        )

    # 理赔完成后，用两个独立读接口复核结论，确保不是只在动作响应里自说自话
    code, detail = request("GET", f"{ENDPOINT}/{entry_id}")
    if must(code == 200, f"GET /{entry_id} 详情接口可访问", f"详情接口返回 {code}：{detail}"):
        must(
            detail.get("status") == "已结案"
            and detail.get("事故编号") == CHECK_NO
            and detail.get("事故类型") == ACCIDENT_TYPE
            and detail.get("损失金额") == ASSESSED_LOSS
            and detail.get("保险理赔") == CLAIM_RESULT,
            "详情接口返回与理赔结论一致（状态/编号/类型/核定金额/理赔结论）",
            f"详情接口返回与理赔结论不一致：{detail}",
        )

    code, page = request("GET", f"{ENDPOINT}?status={urllib.parse.quote('已结案')}&size=200")
    if must(code == 200, "状态过滤列表接口可访问", f"列表接口返回 {code}：{page}"):
        listed = [row for row in page.get("items", []) if row.get("id") == entry_id]
        if must(len(listed) == 1, "检查事故出现在「已结案」过滤结果中",
                f"检查事故未出现在 status=已结案 的列表里：{page.get('items')}"):
            row = listed[0]
            must(
                row.get("保险理赔") == CLAIM_RESULT and row.get("损失金额") == ASSESSED_LOSS,
                "列表中的理赔结论、核定金额与详情/动作返回一致",
                f"列表数据与结论不一致：{row}",
            )

    code, page = request("GET", f"{ENDPOINT}?keyword={CHECK_NO}")
    must(
        code == 200 and any(row.get("id") == entry_id for row in page.get("items", [])),
        f"按事故编号 {CHECK_NO} 可检索到该记录",
        f"按编号检索未命中：{page}",
    )


def main() -> int:
    print("=" * 72)
    print("事故记录链路检查：事故上报 → 损失核定 → 保险理赔")
    print("=" * 72)
    wait_for_backend()
    check_seed_data()
    run_full_chain()

    print("-" * 72)
    if failures:
        print(f"检查失败：{len(failures)} 项未通过（通过 {passed} 项）")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print(f"全部通过：{passed} 项检查，理赔结论与接口返回一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
