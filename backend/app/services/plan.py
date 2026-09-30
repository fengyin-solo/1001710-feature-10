"""点检计划业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "plan"
REQUIRED_FIELDS = ["计划编号", "点检对象", "点检周期"]
OPTIONAL_FIELDS = ["点检项目", "计划工期", "编制人员", "审批人员"]
SUBMIT_REQUIRED_FIELDS = ["点检周期", "计划工期"]
STATUS_ORDER = ["待编制", "待审批", "已批复", "已作废"]
ACTION_RULES = {"提交审批": "待审批", "确认批复": "已批复", "作废计划": "已作废"}
NEGATIVE_ACTIONS = ["作废计划"]
REVIEWED_STATUSES = {"已批复", "已作废"}


class PlanService:
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
            rows = [row for row in rows if keyword in str(row.get("计划编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def status_summary(self) -> dict[str, int]:
        """各审批状态的计划数量：列表刷新时一起取，保证待审数量与计划行同步。"""
        rows = store.rows(MODULE)
        summary = {status: 0 for status in STATUS_ORDER}
        for row in rows:
            status = str(row.get("status") or "")
            if status in summary:
                summary[status] += 1
        summary["total"] = len(rows)
        return summary

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["计划状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"点检计划 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于点检计划可执行范围"
        if action == "提交审批":
            missing = self._submit_missing(entry)
            if missing:
                return None, f"缺少{'、'.join(missing)}，不能送审"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["计划状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"点检计划已{action}"

    def submit_batch(self, entry_ids: list[int], approver: str | None = None) -> dict[str, Any]:
        """批量送审：按勾选顺序逐张处理并各自回执，单张出问题不影响其余计划。"""
        results = [self._submit_one(entry_id, approver=approver) for entry_id in entry_ids]
        summary = {
            "total": len(results),
            "submitted": sum(1 for item in results if item["category"] == "submitted"),
            "duplicated": sum(1 for item in results if item["category"] == "duplicated"),
            "skipped": sum(1 for item in results if item["category"] == "skipped"),
            "failed": sum(1 for item in results if item["category"] == "failed"),
        }
        message = (
            f"批量送审完成：新送审 {summary['submitted']} 张，"
            f"重复送审 {summary['duplicated']} 张，"
            f"挑出 {summary['skipped']} 张，"
            f"未通过 {summary['failed']} 张"
        )
        return {"ok": True, "message": message, "results": results, "summary": summary}

    def _submit_one(self, entry_id: int, *, approver: str | None) -> dict[str, Any]:
        receipt: dict[str, Any] = {
            "id": entry_id,
            "计划编号": None,
            "ok": False,
            "category": "failed",
            "message": "",
        }
        entry = store.find(MODULE, entry_id)
        if entry is None:
            receipt["message"] = f"点检计划 {entry_id} 不存在或已归档"
            return receipt
        receipt["计划编号"] = entry.get("计划编号")
        missing = self._submit_missing(entry)
        if missing:
            receipt["category"] = "skipped"
            receipt["message"] = f"缺少{'、'.join(missing)}，已被挑出，未随批送审"
            return receipt
        status = str(entry.get("status") or "")
        if status == "待审批":
            receipt["ok"] = True
            receipt["category"] = "duplicated"
            receipt["message"] = "该计划已在审批中，重复送审按首次处理"
            return receipt
        if status in REVIEWED_STATUSES:
            receipt["message"] = f"该计划已被审批（当前状态：{status}），本张不再送审，其余继续"
            return receipt
        entry["status"] = "待审批"
        entry["计划状态"] = "待审批"
        entry["pending"] = True
        entry["abnormal"] = False
        if approver:
            entry["审批人员"] = approver
        receipt["ok"] = True
        receipt["category"] = "submitted"
        receipt["message"] = "已送审，等待审批人处理"
        return receipt

    @staticmethod
    def _submit_missing(entry: dict[str, Any]) -> list[str]:
        return [field for field in SUBMIT_REQUIRED_FIELDS if not str(entry.get(field) or "").strip()]
