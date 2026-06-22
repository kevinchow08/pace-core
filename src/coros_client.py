"""
Thin wrapper around coros_lib.

All coros_lib functions are async; we wrap them with asyncio.run() here
so the rest of the app (BlockingScheduler + sync SQLAlchemy) stays simple.

Functions are shaped as tools — each does one thing, returns clean data or raises.
Phase 2: these become agent tool definitions with minimal changes.

Retry logic: exponential backoff, max 3 attempts.
"""
import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Any

from coros_lib.coros_api import (
    fetch_activities,
    fetch_activity_detail,
    fetch_daily_records,
    fetch_hrv,
    fetch_sleep,
    get_stored_auth,
    try_auto_login,
    _is_token_valid,
)
from src.config import settings

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


def _date_str(d: date) -> str:
    return d.strftime("%Y%m%d")


def _get_auth():
    """Return valid auth, auto-logging in if token is missing or expired."""
    auth = get_stored_auth()
    if auth and _is_token_valid(auth):
        return auth
    auth = asyncio.run(try_auto_login())
    if not auth:
        raise RuntimeError("COROS authentication failed. Check COROS_EMAIL / COROS_PASSWORD in .env")
    return auth


def _is_auth_error(e: Exception) -> bool:
    msg = str(e).lower()
    return "token" in msg and ("invalid" in msg or "expired" in msg)


def _with_retry(fn, *args, **kwargs) -> Any:
    for attempt in range(_MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt == _MAX_RETRIES - 1:
                raise
            if _is_auth_error(e):
                logger.warning("Auth token invalid, forcing re-login before retry...")
                asyncio.run(try_auto_login())
            else:
                wait = 2 ** attempt
                logger.warning(f"Attempt {attempt + 1} failed, retrying in {wait}s: {e}")
                time.sleep(wait)


# ---------------------------------------------------------------------------
# Public tool-shaped functions
# ---------------------------------------------------------------------------

def get_recent_activities(days: int = 7, *, start_date: date | None = None, end_date: date | None = None) -> list:
    """Fetch activities. Pass start_date/end_date for explicit range, or days for rolling window."""
    def _call():
        auth = _get_auth()
        end = end_date or date.today()
        start = start_date or (end - timedelta(days=days))
        activities, _ = asyncio.run(
            fetch_activities(auth, _date_str(start), _date_str(end))
        )
        return activities

    return _with_retry(_call)


def get_activity_detail(activity_id: str, sport_type: int) -> dict:
    """Fetch full detail for a single activity."""
    def _call():
        auth = _get_auth()
        return asyncio.run(fetch_activity_detail(auth, activity_id, sport_type))

    return _with_retry(_call)


def get_recent_daily_records(days: int = 14, *, start_date: date | None = None, end_date: date | None = None) -> list:
    """Fetch daily metrics (HRV, load, VO2max, etc.). Pass start_date/end_date for explicit range, or days for rolling window."""
    def _call():
        auth = _get_auth()
        end = end_date or date.today()
        start = start_date or (end - timedelta(days=days))
        return asyncio.run(
            fetch_daily_records(auth, _date_str(start), _date_str(end))
        )

    return _with_retry(_call)


# --- v0.1 (sleep scene, activated when sleep data available) ---

def get_sleep(days: int = 1) -> list:
    def _call():
        auth = _get_auth()
        end = date.today()
        start = end - timedelta(days=days)
        return asyncio.run(fetch_sleep(auth, _date_str(start), _date_str(end)))

    return _with_retry(_call)


def get_hrv() -> list:
    def _call():
        auth = _get_auth()
        return asyncio.run(fetch_hrv(auth))

    return _with_retry(_call)
