"""事故记录业务规则：状态流转、字段校验与筛选口径都收在这里。

整条链路分三段：
  事故上报（待上报 -> 已上报）
  损失核定（已上报 -> 待理赔，核定损失金额）
  保险理赔（待理赔 -> 理赔中 -> 已理赔，登记赔付金额与理赔结论）
动作只能按顺序往下走，跳步会被拦下，保证联调时每一段都能复现。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "accident"
REQUIRED_FIELDS = ["事故编号", "关联任务", "事故类型"]
# 建单时可一并带上的业务字段，动作里也允许更新其中部分字段
OPTIONAL_FIELDS = ["发生时间", "事故描述", "损失金额", "保险理赔"]
STATUS_ORDER = ["待上报", "已上报", "待理赔", "理赔中", "已理赔"]
# 动作 -> (目标状态, 该动作允许写入的字段)
ACTION_RULES: dict[str, tuple[str, list[str]]] = {
    "上报事故": ("已上报", ["发生时间", "事故描述"]),
    "损失核定": ("待理赔", ["损失金额", "事故描述"]),
    "启动理赔": ("理赔中", ["保险理赔"]),
    "理赔到账": ("已理赔", ["赔付金额", "理赔结论", "保险理赔"]),
}
# 各动作允许顺带更新的字段白名单（含建单可选字段之外的赔付信息）
ACTION_FIELD_WHITELIST = set(OPTIONAL_FIELDS) | {"赔付金额", "理赔结论"}
NEGATIVE_ACTIONS: list[str] = []


def _to_amount(value: Any) -> float | None:
    """把金额入参收敛成 float；空值与无法解析的值返回 None，由调用方决定是否报错。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return round(amount, 2)


class AccidentService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("事故编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in OPTIONAL_FIELDS:
            if values.get(field) is not None:
                entry[field] = values.get(field)
        # 建单时允许直接给损失金额（金额字段做一次数值化，避免示例数据里混入字符串）
        amount = _to_amount(entry.get("损失金额"))
        if amount is not None:
            entry["损失金额"] = amount
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"事故记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于事故记录可执行范围"
        target, allowed_fields = ACTION_RULES[action]
        current_index = STATUS_ORDER.index(entry["status"]) if entry["status"] in STATUS_ORDER else -1
        target_index = STATUS_ORDER.index(target)
        # 只允许顺序流转：既不能跳步，也不能对已走完的节点重复操作
        if target_index != current_index + 1:
            return None, (
                f"事故记录当前为「{entry['status']}」，不能执行「{action}」；"
                f"请按 {' → '.join(STATUS_ORDER)} 的顺序流转"
            )

        values = values or {}
        # 损失核定必须拿到可核验的损失金额；金额非法时拦下并说明
        if action in {"损失核定", "理赔到账", "启动理赔"}:
            amount_field = "赔付金额" if action == "理赔到账" else "损失金额"
            if amount_field in allowed_fields and amount_field in values:
                amount = _to_amount(values.get(amount_field))
                if amount is None:
                    return None, f"{amount_field}必须是数字，收到的是「{values.get(amount_field)}」"
                if amount < 0:
                    return None, f"{amount_field}不能为负数，收到的是 {amount}"
                values[amount_field] = amount
        if action == "理赔到账" and not str(values.get("理赔结论") or entry.get("理赔结论") or "").strip():
            return None, "理赔到账必须填写理赔结论（如：保险已赔付 / 拒赔 / 部分赔付）"

        for field in allowed_fields:
            if values.get(field) is not None:
                entry[field] = values[field]
        # 建单后一直未核定金额的，核定时金额已写入；理赔到账后核对赔付不超过损失
        if action == "理赔到账":
            payout = float(entry["赔付金额"])
            loss = _to_amount(entry.get("损失金额"))
            if loss is not None and payout > loss + 0.01:
                return None, f"赔付金额 {payout} 超过核定损失金额 {loss}，请复核后再结案"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"事故记录已{action}"
