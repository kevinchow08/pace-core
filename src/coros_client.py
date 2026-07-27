"""
Thin async wrapper around coros_lib.

多用户模式：不再由后端持有/刷新 COROS 账密，token 由 App 端登录 COROS 后
随每次请求传入，这里只负责拿着调用方给的 auth 去请求数据，不做登录、
不做刷新、不落库。token 失效由上层（API 路由）捕获并返回专门的错误码，
交给 App 端静默重新登录 COROS 后重试。

重试 + 熔断：鉴权错误（is_auth_error）不重试、不计入熔断——token 无效重试
三次还是无效，纯粹浪费时间，直接抛出去让上层转成 COROS_TOKEN_INVALID；
只有网络抖动、COROS 服务瞬时故障这类才值得重试/计入熔断失败次数。

All functions are async — callers (jobs, routes) must await them.
"""
import time
from datetime import date, timedelta

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from coros_lib.coros_api import (
    fetch_activities,
    fetch_activity_detail,
    fetch_daily_records,
    fetch_hrv,
    fetch_sleep,
)
from coros_lib.models import StoredAuth
from src.resilience import CircuitBreaker

_coros_breaker = CircuitBreaker(name="COROS", failure_threshold=5, recovery_timeout=60)


def build_auth(
    access_token: str,
    coros_user_id: str,
    region: str = "cn",
    mobile_access_token: str | None = None,
) -> StoredAuth:
    """
    用 App 端登录 COROS 后拿到的 token 直接构造 auth，不经过后端登录流程。
    timestamp 设为当前时间——这里只是满足 StoredAuth 的字段要求，
    后端不使用它做过期判断（过期判断和刷新完全交给 App 端负责）。

    mobile_access_token 只有晨报（睡眠数据）需要——COROS 的活动/HRV 数据走
    web session，睡眠数据走另一条独立的 mobile session，两者互不相通。
    不传这个字段时，绝不能指望 coros_lib 内部的兜底逻辑（那个兜底是读
    os.environ 里的全局账密，是 Phase 1 单用户时代的遗留行为，多用户场景下
    用了会导致所有用户的睡眠请求都用同一个账号去登录，串号）。
    """
    return StoredAuth(
        access_token=access_token,
        user_id=coros_user_id,
        region=region,
        timestamp=int(time.time() * 1000),
        mobile_access_token=mobile_access_token,
    )


def _date_str(d: date) -> str:
    return d.strftime("%Y%m%d")


def is_auth_error(e: Exception) -> bool:
    """COROS 返回 token 无效/过期时，_check_response 抛出的 ValueError 里会带这类描述"""
    msg = str(e).lower()
    return "token" in msg and ("invalid" in msg or "expired" in msg)


def _should_retry(e: BaseException) -> bool:
    # 鉴权错误不值得重试——重试也是一样的结果（token 无效），纯粹浪费时间
    return not is_auth_error(e)


@retry(
    retry=retry_if_exception(_should_retry),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
async def _call_coros_with_retry(fn, *args, **kwargs):
    """只负责重试，完全不碰熔断器——熔断器要统计的是"一次外部调用"的
    成败，不该被这里内部重试了几次影响到（reload before_call/record_* 的
    话，一次外部失败会被内部重试次数放大，阈值提前触发，语义不对）。"""
    return await fn(*args, **kwargs)


async def _call_coros(fn, *args, **kwargs):
    """真正对外的入口：熔断器只在这一层记录一次，内部重试（最多3次）对它不可见。"""
    _coros_breaker.before_call()
    try:
        result = await _call_coros_with_retry(fn, *args, **kwargs)
    except Exception as e:
        if not is_auth_error(e):
            # 鉴权错误不算"COROS 服务故障"，是 token 本身的问题，不计入熔断失败次数
            _coros_breaker.record_failure()
        raise
    else:
        _coros_breaker.record_success()
        return result


# ---------------------------------------------------------------------------
# Public tool-shaped functions —— 全部要求调用方传入 auth
# ---------------------------------------------------------------------------

async def get_recent_activities(
    auth: StoredAuth, days: int = 7, *, start_date: date | None = None, end_date: date | None = None
) -> list:
    """Fetch activities. Pass start_date/end_date for explicit range, or days for rolling window."""
    end = end_date or date.today()
    start = start_date or (end - timedelta(days=days))
    activities, _ = await _call_coros(fetch_activities, auth, _date_str(start), _date_str(end))
    return activities


async def get_activity_detail(auth: StoredAuth, activity_id: str, sport_type: int) -> dict:
    """Fetch full detail for a single activity."""
    return await _call_coros(fetch_activity_detail, auth, activity_id, sport_type)


async def get_recent_daily_records(
    auth: StoredAuth, days: int = 14, *, start_date: date | None = None, end_date: date | None = None
) -> list:
    """Fetch daily metrics (HRV, load, VO2max, etc.). Pass start_date/end_date for explicit range, or days for rolling window."""
    end = end_date or date.today()
    start = start_date or (end - timedelta(days=days))
    return await _call_coros(fetch_daily_records, auth, _date_str(start), _date_str(end))


async def get_sleep(auth: StoredAuth, days: int = 1) -> list:
    end = date.today()
    start = end - timedelta(days=days)
    return await _call_coros(fetch_sleep, auth, _date_str(start), _date_str(end))


async def get_hrv(auth: StoredAuth) -> list:
    return await _call_coros(fetch_hrv, auth)


async def verify_token(auth: StoredAuth) -> bool:
    """
    验证 App 转交的 token 是否真实有效。
    没有专门的"whoami"接口，用一次最轻量的真实请求（1天范围的每日记录）探活，
    成功即视为 token 有效。复用 get_recent_daily_records()，天然带上重试 + 熔断。
    """
    try:
        await get_recent_daily_records(auth, start_date=date.today(), end_date=date.today())
        return True
    except Exception as e:
        if is_auth_error(e):
            return False
        raise  # 非鉴权类错误（网络、COROS 服务异常）不应该被当成"token 无效"
