"""
Thin async wrapper around coros_lib.

多用户模式：不再由后端持有/刷新 COROS 账密，token 由 App 端登录 COROS 后
随每次请求传入，这里只负责拿着调用方给的 auth 去请求数据，不做登录、
不做刷新、不落库。token 失效由上层（API 路由）捕获并返回专门的错误码，
交给 App 端静默重新登录 COROS 后重试。

All functions are async — callers (jobs, routes) must await them.
"""
from datetime import date, timedelta

from coros_lib.coros_api import (
    fetch_activities,
    fetch_activity_detail,
    fetch_daily_records,
    fetch_hrv,
    fetch_sleep,
)
from coros_lib.models import StoredAuth


def build_auth(access_token: str, coros_user_id: str, region: str = "cn") -> StoredAuth:
    """
    用 App 端登录 COROS 后拿到的 token 直接构造 auth，不经过后端登录流程。
    timestamp 设为当前时间——这里只是满足 StoredAuth 的字段要求，
    后端不使用它做过期判断（过期判断和刷新完全交给 App 端负责）。
    """
    import time
    return StoredAuth(
        access_token=access_token,
        user_id=coros_user_id,
        region=region,
        timestamp=int(time.time() * 1000),
    )


def _date_str(d: date) -> str:
    return d.strftime("%Y%m%d")


def is_auth_error(e: Exception) -> bool:
    """COROS 返回 token 无效/过期时，_check_response 抛出的 ValueError 里会带这类描述"""
    msg = str(e).lower()
    return "token" in msg and ("invalid" in msg or "expired" in msg)


async def verify_token(auth: StoredAuth) -> bool:
    """
    验证 App 转交的 token 是否真实有效。
    没有专门的"whoami"接口，用一次最轻量的真实请求（1天范围的每日记录）探活，
    成功即视为 token 有效。
    """
    try:
        await fetch_daily_records(auth, _date_str(date.today()), _date_str(date.today()))
        return True
    except Exception as e:
        if is_auth_error(e):
            return False
        raise  # 非鉴权类错误（网络、COROS 服务异常）不应该被当成"token 无效"


# ---------------------------------------------------------------------------
# Public tool-shaped functions —— 全部要求调用方传入 auth
# ---------------------------------------------------------------------------

async def get_recent_activities(
    auth: StoredAuth, days: int = 7, *, start_date: date | None = None, end_date: date | None = None
) -> list:
    """Fetch activities. Pass start_date/end_date for explicit range, or days for rolling window."""
    end = end_date or date.today()
    start = start_date or (end - timedelta(days=days))
    activities, _ = await fetch_activities(auth, _date_str(start), _date_str(end))
    return activities


async def get_activity_detail(auth: StoredAuth, activity_id: str, sport_type: int) -> dict:
    """Fetch full detail for a single activity."""
    return await fetch_activity_detail(auth, activity_id, sport_type)


async def get_recent_daily_records(
    auth: StoredAuth, days: int = 14, *, start_date: date | None = None, end_date: date | None = None
) -> list:
    """Fetch daily metrics (HRV, load, VO2max, etc.). Pass start_date/end_date for explicit range, or days for rolling window."""
    end = end_date or date.today()
    start = start_date or (end - timedelta(days=days))
    return await fetch_daily_records(auth, _date_str(start), _date_str(end))


async def get_sleep(auth: StoredAuth, days: int = 1) -> list:
    end = date.today()
    start = end - timedelta(days=days)
    return await fetch_sleep(auth, _date_str(start), _date_str(end))


async def get_hrv(auth: StoredAuth) -> list:
    return await fetch_hrv(auth)
