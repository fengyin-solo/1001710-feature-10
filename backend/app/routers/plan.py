"""点检计划接口：维护点检计划，覆盖批量送审、提交审批、确认批复、作废计划等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, BatchSubmitPayload, EntryPayload, PageResult
from app.services.plan import PlanService

router = APIRouter(prefix="/api/plan", tags=["点检计划"])

service = PlanService()

LIST_FIELDS = ["计划编号", "点检对象", "点检周期", "点检项目", "计划工期", "编制人员", "审批人员", "计划状态"]
STATUSES = ["待编制", "待审批", "已批复", "已作废"]
BATCH_LIMIT = 200


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


@router.get("/stats", response_model=dict)
def plan_stats() -> dict[str, int]:
    """按审批状态汇总计划数量，送审后列表与待审数量看到的是同一份最新结果。"""
    return service.status_stats()


@router.post("/batch-submit", response_model=dict)
def batch_submit(payload: BatchSubmitPayload) -> dict[str, Any]:
    """把勾选的待送审点检计划一次推给审批人。

    逐条独立处理：资料不全先挑出、已被别人审过只跳过该张、批内重复只认第一次，
    一张失败不会让整批作废；响应里带回每张计划的成功/失败回执。
    """
    if not payload.ids:
        raise HTTPException(status_code=400, detail="请先勾选需要送审的点检计划")
    if len(payload.ids) > BATCH_LIMIT:
        raise HTTPException(status_code=400, detail=f"单次最多送审 {BATCH_LIMIT} 张，请分批提交")
    return service.batch_submit(payload.ids, approver=payload.approver)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出点检计划清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "plan", "total": total, "items": items}


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
