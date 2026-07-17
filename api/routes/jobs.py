from pydantic import BaseModel
from fastapi import APIRouter, BackgroundTasks, Depends

from api.deps import get_current_user
from api.errors import BizCode, BizException
from src import coros_client, jobs
from src.store import User

router = APIRouter()


class TriggerRequest(BaseModel):
    # App 端登录 COROS 后随每次触发请求带来，用完即弃，后端不落库
    coros_access_token: str
    coros_user_id: str
    coros_region: str = "cn"
    # 只有 /morning 需要——COROS 的睡眠数据走另一条独立的 mobile session，
    # 跟活动/HRV 数据用的 web session 不是同一回事，必须单独登录、单独传
    coros_mobile_access_token: str | None = None


class TriggerResponse(BaseModel):
    # processing：后台已经在跑真正的分析，稍后收到推送
    # no_new_data：检查过了，暂时没有新内容值得处理，App 应立刻提示用户，
    #              不要展示"分析中"占位——那个占位永远不会有结果
    status: str
    new_count: int | None = None


async def get_verified_auth(body: TriggerRequest):
    """
    依赖注入：跟 get_current_user 一样，是"路由要用、但跟核心业务逻辑无关的
    前置计算"——只是这次依赖的是请求体字段 + 一次网络请求（验证 token），
    不是请求头，Depends 不限定只能用来解析 header。
    """
    auth = coros_client.build_auth(
        body.coros_access_token,
        body.coros_user_id,
        body.coros_region,
        mobile_access_token=body.coros_mobile_access_token,
    )
    # 同步验证放在这里而不是丢进后台任务：无效 token 要能立刻让 App 感知到，
    # 触发它"静默重新登录 COROS 再重试"的逻辑，而不是等后台任务默默失败、
    # 只发一条推送通知草草了事
    #
    # 注意：这里验证的是 web session（走 fetch_daily_records 探活）。
    # 晨报用的是 mobile session（睡眠数据），是另一条独立会话，这一步
    # 验证不出 mobile token 是否有效——所以下面 check_* 调用还要再兜底一层。
    if not await coros_client.verify_token(auth):
        raise BizException(BizCode.COROS_TOKEN_INVALID, "COROS 登录状态无效，请重新登录")
    return auth


async def _run_check(check_coro):
    """
    统一包一层：check_* 内部真正请求 COROS 时如果遇到鉴权失败（常见于晨报的
    mobile session，get_verified_auth 验证不到这一层），转换成
    COROS_TOKEN_INVALID 精确返回给 App，而不是被兜底成一个模糊的 500。
    """
    try:
        return await check_coro
    except Exception as e:
        if coros_client.is_auth_error(e):
            raise BizException(BizCode.COROS_TOKEN_INVALID, "COROS 登录状态无效，请重新登录")
        raise


@router.post("/activity", response_model=TriggerResponse)
async def trigger_activity(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    auth=Depends(get_verified_auth),
):
    prepared = await _run_check(jobs.check_new_activity(current_user, auth))
    if prepared is None:
        return TriggerResponse(status="no_new_data")

    background_tasks.add_task(jobs.process_new_activity, current_user, prepared)
    return TriggerResponse(status="processing", new_count=len(prepared))


@router.post("/morning", response_model=TriggerResponse)
async def trigger_morning(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    auth=Depends(get_verified_auth),
):
    if not auth.mobile_access_token:
        raise BizException(BizCode.COROS_TOKEN_INVALID, "缺少 COROS 睡眠数据授权，请在 App 内重新登录")

    prepared = await _run_check(jobs.check_morning_report(current_user, auth))
    if prepared is None:
        return TriggerResponse(status="no_new_data")

    background_tasks.add_task(jobs.process_morning_report, current_user, prepared)
    return TriggerResponse(status="processing")


@router.post("/risk", response_model=TriggerResponse)
async def trigger_risk(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    auth=Depends(get_verified_auth),
):
    prepared = await _run_check(jobs.check_injury_risk(current_user, auth))
    if prepared is None:
        return TriggerResponse(status="no_new_data")

    background_tasks.add_task(jobs.process_injury_risk, current_user, prepared)
    return TriggerResponse(status="processing")


@router.post("/weekly", response_model=TriggerResponse)
async def trigger_weekly(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    auth=Depends(get_verified_auth),
):
    prepared = await _run_check(jobs.check_weekly_report(current_user, auth))
    if prepared is None:
        return TriggerResponse(status="no_new_data")

    background_tasks.add_task(jobs.process_weekly_report, current_user, prepared)
    return TriggerResponse(status="processing")
