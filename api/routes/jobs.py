import logging
from fastapi import APIRouter, BackgroundTasks

from src.jobs import on_new_activity, morning_report, injury_risk_check, weekly_report

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/activity")
async def trigger_activity(background_tasks: BackgroundTasks):
    """手动触发练后分析（等价于 --once）"""
    background_tasks.add_task(on_new_activity)
    return {"status": "triggered", "job": "on_new_activity"}


@router.post("/morning")
async def trigger_morning(background_tasks: BackgroundTasks):
    """手动触发晨报（等价于 --morning）"""
    background_tasks.add_task(morning_report)
    return {"status": "triggered", "job": "morning_report"}


@router.post("/risk")
async def trigger_risk(background_tasks: BackgroundTasks):
    """手动触发伤病风险检测（等价于 --risk）"""
    background_tasks.add_task(injury_risk_check)
    return {"status": "triggered", "job": "injury_risk_check"}


@router.post("/weekly")
async def trigger_weekly(background_tasks: BackgroundTasks):
    """手动触发周报（等价于 --weekly）"""
    background_tasks.add_task(weekly_report)
    return {"status": "triggered", "job": "weekly_report"}
