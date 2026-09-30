"""点检计划接口：维护点检计划，覆盖提交审批、确认批复、作废计划与批量送审。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, BatchResult, BatchSubmitPayload, EntryPayload, PageResult
from app.services.plan import PlanService

router = APIRouter(prefix="/api/plan", tags=["点检计划"])

service = PlanService()

LIST_FIELDS = ["计划编号", "点检对象", "点检周期", "点检项目", "计划工期", "编制人员", "审批人员", "计划状态"]
STATUSES = ["待编制", "待审批", "已批复", "已作废"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按计划编号检索"),
    status: str | None = Query(default=None, description="待编制、待审批、已批复、已作废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按计划编号与状态过滤点检计划列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def status_stats() -> dict[str, int]:
    """各审批状态的计划数量：送审后待审数量随列表一起刷新，重进页面看到的也是这份。"""
    return service.status_summary()


@router.post("/batch-submit", response_model=BatchResult)
def submit_batch(payload: BatchSubmitPayload) -> BatchResult:
    """把勾选的计划一次推给审批人：缺字段的先挑出，其余逐条回执，单张失败不作废整批。"""
    if not payload.ids:
        return BatchResult(ok=False, message="请先勾选要送审的点检计划")
    approver = (payload.approver or "").strip() or None
    result = service.submit_batch(payload.ids, approver=approver)
    return BatchResult(**result)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条点检计划明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"点检计划 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条点检计划，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="点检计划已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条点检计划执行提交审批、确认批复、作废计划；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出点检计划清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "plan", "total": total, "items": items}
