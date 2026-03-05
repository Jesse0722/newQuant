from fastapi import APIRouter
from app.schemas.strategy import IndicatorScreenRequest, AiScreenRequest, ScreenResult
from app.services.strategy_service import run_indicator_screen, SCREEN_TEMPLATES
from app.services.ai_screen_service import run_ai_screen
from app.tasks.background import submit_task, get_task_status
from app.exceptions import AppError

router = APIRouter(prefix="/api/strategy", tags=["strategy"])


@router.get("/templates")
def list_screen_templates():
    """获取指标选股模板列表"""
    return [
        {"id": k, "name": v["name"], "default_params": v["params"]}
        for k, v in SCREEN_TEMPLATES.items()
    ]


@router.post("/screen")
def run_screen(body: IndicatorScreenRequest):
    """提交指标组合选股任务"""
    conditions = [c.model_dump() for c in body.conditions]
    task_id = submit_task("strategy", run_indicator_screen, body.scope, conditions, body.logic)
    return {"task_id": task_id}


@router.post("/ai-screen")
def run_ai_screen_task(body: AiScreenRequest):
    """提交 AI 智能选股任务"""
    task_id = submit_task("ai_screen", run_ai_screen, body.description, body.scope or "full")
    return {"task_id": task_id}


@router.get("/result/{task_id}", response_model=ScreenResult)
def get_screen_result(task_id: str):
    """轮询选股任务结果（指标选股与 AI 选股共用）"""
    status = get_task_status(task_id)
    if not status:
        raise AppError(code=1004, message="任务不存在", status_code=404)
    result = status.result or {}
    return ScreenResult(
        task_id=status.id,
        status=status.status,
        progress=status.progress,
        message=status.message,
        ts_codes=result.get("ts_codes", []),
        stock_names=result.get("stock_names", {}),
        total=result.get("total", 0),
    )
