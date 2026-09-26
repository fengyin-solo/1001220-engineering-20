#!/usr/bin/env python3
"""理赔结论复核脚本：确认「已理赔」事故的理赔结论与接口返回一致。

核对内容（全部通过才退出 0）：
1. 事故存在且终态为「已理赔」；
2. 接口返回带有赔付金额、理赔结论，且赔付金额 <= 核定损失金额；
3. 若给出 --frontend-base-url，则再经前端 dev server 的 /api 代理读一遍，
   确认前后端联调链路拿到的是同一份结论（直连后端与代理返回一致）；
4. 若给出 --expect-* 期望值（或使用 scripts 自动写入的 .run/accident-demo.json），
   逐字段比对是否相符。

用法：
  scripts/verify-claim.py                      # 复核 .run/accident-demo.json 记录的事故
  scripts/verify-claim.py --id 6               # 直接按事故 id 复核
  scripts/verify-claim.py --id 6 \\
      --backend-base-url http://127.0.0.1:8000 \\
      --frontend-base-url http://127.0.0.1:5173 \\
      --expect-loss 12000 --expect-payout 9600 \\
      --expect-conclusion 保险已赔付
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

TERMINAL_STATUS = "已理赔"
RUN_FILE = Path(__file__).resolve().parent.parent / ".run" / "accident-demo.json"


def fetch_entry(base_url: str, entry_id: int) -> dict:
    url = f"{base_url.rstrip('/')}/api/accident/{entry_id}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SystemExit(f"✘ 接口 {url} 返回 404：事故 {entry_id} 不存在") from exc
        raise SystemExit(f"✘ 接口 {url} 返回 HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(
            f"✘ 无法连接 {url}：{exc}\n"
            "  请先用 make dev-up（scripts/dev-up.sh）把前后端拉起来"
        ) from exc


def check_entry(entry: dict, source: str, expect: dict | None = None) -> list[str]:
    """对单份接口返回做业务断言，返回错误信息列表（空列表表示全部通过）。"""
    errors: list[str] = []
    prefix = f"[{source}]"

    status = entry.get("status")
    if status != TERMINAL_STATUS:
        errors.append(f"{prefix} 事故状态为「{status}」，应为终态「{TERMINAL_STATUS}」，理赔链路未走完整")

    loss = entry.get("损失金额")
    payout = entry.get("赔付金额")
    conclusion = entry.get("理赔结论")

    if not isinstance(loss, (int, float)):
        errors.append(f"{prefix} 缺少核定损失金额（损失金额={loss!r}），无法复核理赔")
    if not isinstance(payout, (int, float)):
        errors.append(f"{prefix} 缺少赔付金额（赔付金额={payout!r}），理赔结论无法成立")
    if not str(conclusion or "").strip():
        errors.append(f"{prefix} 理赔结论为空，已理赔事故必须留下结论（如：保险已赔付）")

    if isinstance(loss, (int, float)) and isinstance(payout, (int, float)):
        if payout < 0:
            errors.append(f"{prefix} 赔付金额 {payout} 为负数")
        if payout - loss > 0.01:
            errors.append(f"{prefix} 赔付金额 {payout} 超过核定损失金额 {loss}，理赔结论不成立")

    if expect:
        for key, field in (("loss", "损失金额"), ("payout", "赔付金额"), ("conclusion", "理赔结论")):
            wanted = expect.get(key)
            if wanted is None:
                continue
            actual = entry.get(field)
            if key in {"loss", "payout"}:
                ok = isinstance(actual, (int, float)) and abs(float(actual) - float(wanted)) < 0.01
            else:
                ok = str(actual or "") == str(wanted)
            if not ok:
                errors.append(f"{prefix} {field} 期望 {wanted!r}，接口返回 {actual!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="复核已理赔事故的结论与接口返回是否一致")
    parser.add_argument("--id", type=int, help="事故记录 id；缺省时读取 .run/accident-demo.json")
    parser.add_argument("--backend-base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--frontend-base-url",
        default=None,
        help="给出后会再经前端 vite 代理访问一次，校验前后端返回一致，如 http://127.0.0.1:5173",
    )
    parser.add_argument("--expect-loss", type=float, default=None)
    parser.add_argument("--expect-payout", type=float, default=None)
    parser.add_argument("--expect-conclusion", default=None)
    args = parser.parse_args()

    recorded: dict = {}
    entry_id = args.id
    if entry_id is None:
        if not RUN_FILE.exists():
            parser.error(
                f"未指定 --id，且找不到 {RUN_FILE}；"
                "请先执行 scripts/seed-accident-demo.sh 灌入示例链路，或显式传入 --id"
            )
        recorded = json.loads(RUN_FILE.read_text(encoding="utf-8"))
        entry_id = int(recorded["id"])
        print(f"读取 {RUN_FILE.name}：事故 {recorded.get('事故编号')} (id={entry_id})")

    expect: dict = {}
    # 命令行显式参数优先；否则沿用 seed 脚本记录的期望值
    expect["loss"] = args.expect_loss if args.expect_loss is not None else recorded.get("损失金额")
    expect["payout"] = args.expect_payout if args.expect_payout is not None else recorded.get("赔付金额")
    expect["conclusion"] = args.expect_conclusion or recorded.get("理赔结论")

    print(f"① 直连后端复核事故 id={entry_id} …")
    backend_entry = fetch_entry(args.backend_base_url, entry_id)
    errors = check_entry(backend_entry, "后端直连", expect)

    proxy_entry: dict | None = None
    if args.frontend_base_url:
        print(f"② 经前端代理 {args.frontend_base_url} 再读一次 …")
        proxy_entry = fetch_entry(args.frontend_base_url, entry_id)
        errors += check_entry(proxy_entry, "前端代理", expect)
        for field in ("status", "损失金额", "赔付金额", "理赔结论"):
            if backend_entry.get(field) != proxy_entry.get(field):
                errors.append(
                    f"[前后端一致性] {field} 不一致：后端={backend_entry.get(field)!r}，"
                    f"前端代理={proxy_entry.get(field)!r}"
                )

    print("-" * 60)
    if errors:
        for msg in errors:
            print(msg)
        print(f"✘ 复核未通过，共 {len(errors)} 处不一致")
        return 1

    print(
        f"✔ 事故 {backend_entry.get('事故编号')} (id={entry_id}) 理赔结论一致："
        f"状态={backend_entry['status']}，损失金额={backend_entry['损失金额']}，"
        f"赔付金额={backend_entry['赔付金额']}，理赔结论={backend_entry['理赔结论']}"
    )
    if proxy_entry is not None:
        print("✔ 后端直连与前端 /api 代理返回完全一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
