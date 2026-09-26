"""事故记录业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "accident"
REQUIRED_FIELDS = ["事故编号", "关联任务", "事故类型"]
# 登记时允许一并带上的业务字段：事故编号、事故类型、损失金额是链路里必须可见的字段
OPTIONAL_FIELDS = ["发生时间", "事故描述", "损失金额", "保险理赔", "事故状态"]
STATUS_ORDER = ["待上报", "已上报", "理赔中", "已结案"]
ACTION_RULES = {"上报事故": "已上报", "启动理赔": "理赔中", "结案归档": "已结案"}
NEGATIVE_ACTIONS = []


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
            # 损失金额可能是数值，不能直接用真值判断；有带且非空白就落库
            if field in values and str(values.get(field) or "").strip():
                entry[field] = values[field]
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"事故记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于事故记录可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        values = values or {}
        if action == "启动理赔" and str(values.get("损失金额") or "").strip():
            # 损失核定：进入理赔环节时可以带上核定后的损失金额
            entry["损失金额"] = values["损失金额"]
        if action == "结案归档" and str(values.get("保险理赔") or "").strip():
            # 保险理赔结案：把最终理赔结论写回记录，供对账与检查脚本核对
            entry["保险理赔"] = values["保险理赔"]
        entry["status"] = target
        entry["事故状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"事故记录已{action}"
