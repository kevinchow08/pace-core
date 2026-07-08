from pydantic import BaseModel
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import Response

from api.deps import get_current_user
from api.errors import BizCode, BizException
from src import coros_client
from src.jobs import on_new_activity, morning_report, injury_risk_check, weekly_report
from src.store import User

router = APIRouter()


class TriggerRequest(BaseModel):
    # App 端登录 COROS 后随每次触发请求带来，用完即弃，后端不落库
    coros_access_token: str
    coros_user_id: str
    coros_region: str = "cn"


async def _verify_and_build_auth(body: TriggerRequest):
    auth = coros_client.build_auth(body.coros_access_token, body.coros_user_id, body.coros_region)
    # 同步验证放在这里而不是丢进后台任务：无效 token 要能立刻让 App 感知到，
    # 触发它"静默重新登录 COROS 再重试"的逻辑，而不是等后台任务默默失败、
    # 只发一条推送通知草草了事
    if not await coros_client.verify_token(auth):
        raise BizException(BizCode.COROS_TOKEN_INVALID, "COROS 登录状态无效，请重新登录")
    return auth


@router.post("/activity")
async def trigger_activity(
    body: TriggerRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    auth = await _verify_and_build_auth(body)
    background_tasks.add_task(on_new_activity, current_user, auth)
    return Response(status_code=202)


@router.post("/morning")
async def trigger_morning(
    body: TriggerRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    auth = await _verify_and_build_auth(body)
    background_tasks.add_task(morning_report, current_user, auth)
    return Response(status_code=202)


@router.post("/risk")
async def trigger_risk(
    body: TriggerRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    auth = await _verify_and_build_auth(body)
    background_tasks.add_task(injury_risk_check, current_user, auth)
    return Response(status_code=202)


@router.post("/weekly")
async def trigger_weekly(
    body: TriggerRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    auth = await _verify_and_build_auth(body)
    background_tasks.add_task(weekly_report, current_user, auth)
    return Response(status_code=202)
