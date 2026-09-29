"""点检计划业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "plan"
REQUIRED_FIELDS = ["计划编号", "点检对象", "点检周期"]
# 送审前必须填全的资料：点检周期与计划工期缺任一项都要先被挑出来。
SUBMIT_REQUIRED_FIELDS = ["点检周期", "计划工期"]
STATUS_ORDER = ["待编制", "待审批", "已批复", "已作废"]
ACTION_RULES = {"提交审批": "待审批", "确认批复": "已批复", "作废计划": "已作废"}
NEGATIVE_ACTIONS = ["作废计划"]

# 批量送审回执里每张计划的结果码。
CODE_SUBMITTED = "submitted"
CODE_INCOMPLETE = "incomplete"
CODE_CONFLICT = "conflict"
CODE_NOT_FOUND = "not_found"
CODE_DUPLICATE = "duplicate"


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

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 登记时一并收下送审所需的扩展字段，避免补录的计划工期无处安放。
        for field in ("点检项目", "计划工期", "编制人员", "审批人员"):
            entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def status_stats(self) -> dict[str, int]:
        """按审批状态统计计划数量，待审数量与列表行同源，送审后两边同时变化。"""
        counts = {status: 0 for status in STATUS_ORDER}
        for row in store.rows(MODULE):
            status = row.get("status")
            if status in counts:
                counts[status] += 1
        return counts

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"点检计划 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于点检计划可执行范围"
        guard_error = self._check_transition(entry, action)
        if guard_error:
            return None, guard_error
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"点检计划已{action}"

    def batch_submit(
        self, entry_ids: list[int], approver: str | None = None
    ) -> dict[str, Any]:
        """把勾选的待送审计划一次推给审批人。

        - 批内同一张计划出现多次，只认第一次，其余记为重复；
        - 点检周期/计划工期没填全的先挑出来，不跟着送审；
        - 逐张独立处理：某张已被别人审过（状态已变）只跳过这张，不影响其余；
        - 每张都回执成功或失败原因，调用方按回执刷新行状态与待审数量。
        """
        approver = (approver or "").strip() or None
        index = {int(row["id"]): row for row in store.rows(MODULE)}
        seen: set[int] = set()
        items: list[dict[str, Any]] = []
        summary = {
            "requested": len(entry_ids),
            CODE_SUBMITTED: 0,
            CODE_INCOMPLETE: 0,
            CODE_CONFLICT: 0,
            CODE_NOT_FOUND: 0,
            CODE_DUPLICATE: 0,
        }

        for raw_id in entry_ids:
            entry_id = int(raw_id)
            if entry_id in seen:
                summary[CODE_DUPLICATE] += 1
                items.append(self._receipt(entry_id, None, CODE_DUPLICATE,
                                           "同一张计划重复送审，只认第一次，本条未重复处理"))
                continue
            seen.add(entry_id)

            entry = index.get(entry_id)
            if entry is None:
                summary[CODE_NOT_FOUND] += 1
                items.append(self._receipt(entry_id, None, CODE_NOT_FOUND,
                                           f"点检计划 {entry_id} 不存在或已归档，未送审"))
                continue

            code, message = self._submit_one(entry, approver)
            summary[code] += 1
            items.append(self._receipt(entry_id, entry, code, message))

        return {
            "ok": summary[CODE_SUBMITTED] > 0,
            "message": self._build_message(summary),
            "summary": summary,
            "items": items,
        }

    def _submit_one(self, entry: dict[str, Any], approver: str | None) -> tuple[str, str]:
        """处理单张计划送审；执行时再读一次状态，兜住期间被别人审过的情况。"""
        missing = [
            field for field in SUBMIT_REQUIRED_FIELDS
            if not str(entry.get(field) or "").strip()
        ]
        if missing:
            return (
                CODE_INCOMPLETE,
                f"计划编号 {entry.get('计划编号')}：{'、'.join(missing)}未填全，已挑出未送审",
            )
        current = str(entry.get("status") or "")
        if current != "待编制":
            return (
                CODE_CONFLICT,
                f"计划编号 {entry.get('计划编号')}：当前状态为「{current}」，可能已被别人审过，本张跳过，其余继续",
            )
        if approver:
            entry["审批人员"] = approver
        entry["status"] = "待审批"
        entry["pending"] = True
        entry["abnormal"] = False
        return CODE_SUBMITTED, f"计划编号 {entry.get('计划编号')}：送审成功，已推送给审批人{('（' + approver + '）') if approver else ''}"

    def _check_transition(self, entry: dict[str, Any], action: str) -> str:
        """动作前置校验：状态不对或送审资料不全时返回可读原因，通过则返回空串。"""
        current = str(entry.get("status") or "")
        if action == "提交审批":
            if current != "待编制":
                return f"当前状态为「{current}」，不能重复送审"
            missing = [
                field for field in SUBMIT_REQUIRED_FIELDS
                if not str(entry.get(field) or "").strip()
            ]
            if missing:
                return f"{'、'.join(missing)}未填全，请补齐后再送审"
        elif action == "确认批复" and current != "待审批":
            return f"当前状态为「{current}」，只有待审批的计划可以批复"
        elif action == "作废计划" and current in ("已批复", "已作废"):
            return f"当前状态为「{current}」，不能作废"
        return ""

    def _receipt(
        self, entry_id: int, entry: dict[str, Any] | None, code: str, message: str
    ) -> dict[str, Any]:
        return {
            "id": entry_id,
            "计划编号": (entry or {}).get("计划编号"),
            "ok": code == CODE_SUBMITTED,
            "code": code,
            "message": message,
            "entry": entry,
        }

    def _build_message(self, summary: dict[str, int]) -> str:
        parts = [f"成功 {summary[CODE_SUBMITTED]} 张"]
        if summary[CODE_INCOMPLETE]:
            parts.append(f"资料不全挑出 {summary[CODE_INCOMPLETE]} 张")
        if summary[CODE_CONFLICT]:
            parts.append(f"已被处理跳过 {summary[CODE_CONFLICT]} 张")
        if summary[CODE_NOT_FOUND]:
            parts.append(f"查无此单 {summary[CODE_NOT_FOUND]} 张")
        if summary[CODE_DUPLICATE]:
            parts.append(f"重复送审 {summary[CODE_DUPLICATE]} 次")
        return f"批量送审完成：{'，'.join(parts)}"
