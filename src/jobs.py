"""
业务 job：练后点评 / 晨报 / 伤病预警 / 周报。

多用户模式：每个业务由 API 路由针对单个用户手动触发，拆成两段，四个业务
统一遵循同一个模式：

- check_*()：判断"有没有值得处理的新内容"，**同时把 process 阶段需要的全部
  COROS 数据一次性拉齐**（不止是元数据判断）。路由层直接 await 这一段，
  没有新内容就立刻告诉 App"暂无新记录"，不需要让用户对着一个不会有结果的
  "分析中"占位干等。
- process_*()：纯 LLM 分析 + 落库 + 推送，**不再有任何 COROS 请求**，用的都是
  check_* 已经准备好的数据。慢（通常几十秒，主要是 LLM 调用），由路由层丢进
  BackgroundTasks 异步执行，完成后靠推送通知告诉用户。

这样拆的好处：COROS 鉴权失败只会发生在 check_* 阶段（同步、路由层能立刻
捕获转成 COROS_TOKEN_INVALID），process_* 阶段只可能因为 LLM/落库失败，
排查问题时不用怀疑是不是 COROS 那边出的错。
"""
import logging
from datetime import date, timedelta

from coros_lib.models import StoredAuth

from src import coros_client, analyzer, notifier, store
from src.risk import assess_injury_risk
from src.store import User

logger = logging.getLogger(__name__)

# 同一训练课内两条活动之间允许的最大间隔（秒）
# 例：热身结束 → 重点训练开始，中间可能有几分钟休息
_SESSION_GAP_SECONDS = 2 * 3600  # 2 小时


def _group_into_sessions(activities: list) -> list[list]:
    """
    把活动列表按训练课分组。

    规则：按 start_time 排序后，相邻两条活动的间隔 <= 2小时，视为同一课。
    同一个晚上的热身 + 重点课 + 冷身，就会被归进同一组。

    返回：[[session1_act1, session1_act2], [session2_act1], ...]
    """
    if not activities:
        return []

    # key=lambda 相当于 JS 的 .sort((a,b) => a.start_time - b.start_time)
    # 按开始时间从早到晚排序，确保后面的间隔计算是顺序的
    sorted_acts = sorted(activities, key=lambda a: int(a.start_time or 0))

    sessions = []
    current_session = [sorted_acts[0]]  # 用第一条活动初始化第一课

    # [1:] 相当于 JS 的 .slice(1)，从第二条开始遍历，跳过已放入 current_session 的第一条
    for activity in sorted_acts[1:]:
        # [-1] 取列表最后一个元素，相当于 JS 的 arr[arr.length - 1]
        prev = current_session[-1]
        # 用上一条的 end_time 计算间隔，没有 end_time 就用 start_time 兜底
        prev_end = int(prev.end_time or prev.start_time or 0)
        curr_start = int(activity.start_time or 0)
        gap = curr_start - prev_end

        if gap <= _SESSION_GAP_SECONDS:
            # 间隔在阈值内：同一课，追加进去
            current_session.append(activity)
        else:
            # 间隔太大：新的一课，把当前课存起来，重新开一课
            sessions.append(current_session)
            current_session = [activity]

    sessions.append(current_session)  # 最后一课别忘了加进去
    return sessions


# ---------------------------------------------------------------------------
# 练后点评
# ---------------------------------------------------------------------------

async def check_new_activity(user: User, auth: StoredAuth) -> list[dict] | None:
    """
    检查 + 把 process 需要的全部数据一次性拉齐（跟晨报/风险预警一致的模式）：
    有没有新训练课；有的话把每课的活动详情、共用的14天背景数据都请求好，
    process 阶段只做 LLM + 落库 + 推送，不再有任何 COROS 请求。
    返回 None 表示没有新训练课。
    """
    # days=4：覆盖数据同步延迟，同时避免拉太多历史数据
    activities = await coros_client.get_recent_activities(auth, days=4)
    sessions = _group_into_sessions(activities)
    new_sessions = []
    for s in sessions:
        # any() 内部有 await，不能用列表推导式，必须显式 for 循环
        has_new = any([not await store.is_processed(user.id, a.activity_id) for a in s])
        if has_new:
            new_sessions.append(s)

    if not new_sessions:
        return None

    # 14天背景数据：所有课共用一份，在循环外拉一次
    # 理由：COROS 数据不会在同一次 job 的几秒内发生变化，
    # 多次调用结果相同，只会浪费 API 请求
    daily_ctx = await coros_client.get_recent_daily_records(auth, days=14)
    daily_dicts = [r.model_dump() for r in daily_ctx]

    prepared = []
    for session in new_sessions:
        session_id = session[0].activity_id
        details = []
        for activity in session:
            detail = await coros_client.get_activity_detail(
                auth, activity.activity_id, activity.sport_type or 0
            )
            details.append(detail)
        prepared.append({
            "session_id": session_id,
            "activity_ids": [a.activity_id for a in session],
            "details": details,
            "daily_dicts": daily_dicts,
        })
    return prepared


async def process_new_activity(user: User, prepared: list[dict]) -> None:
    """
    纯 LLM 分析 + 落库 + 推送，不再请求 COROS。
    prepared 由 check_new_activity() 拉齐传入。
    """
    for item in prepared:
        session_id = item["session_id"]
        logger.info(f"Processing session {session_id}")

        try:
            coaching = analyzer.analyze_workout(item["details"], item["daily_dicts"])

            await store.save_run_log(user.id, session_id, item["details"], item["daily_dicts"], coaching)
            notifier.push(title="练后点评", body=coaching)

            for activity_id in item["activity_ids"]:
                await store.mark_processed(user.id, activity_id)

            logger.info(f"Pushed coaching for session {session_id} ({len(item['activity_ids'])} activities)")

        except Exception as e:
            logger.error(f"Failed to process session {session_id}: {e}")
            notifier.push(title="PaceCoach Error", body=f"训练课 {session_id} 处理失败：{e}")


# ---------------------------------------------------------------------------
# 今日状态播报
# ---------------------------------------------------------------------------

async def check_morning_report(user: User, auth: StoredAuth) -> dict | None:
    """
    轻量检查：有没有可播报的今日状态。返回 None 表示暂时没有（睡眠数据未同步 /
    HRV 未同步 / 今天已经推过），否则返回准备好的数据供 process 直接使用。

    注意：睡眠数据走 COROS mobile session，调用这个函数本身就会踢掉用户手机端
    COROS App 的登录态（详见 coros_lib/coros_api.py 里 _mobile_login 的说明），
    跟最终有没有推送无关——这是 App 端需要向用户明确提示的副作用。
    """
    if not auth.mobile_access_token:
        # 明确拒绝，绝不能让流程走到 coros_lib 内部 _ensure_mobile_token() 的
        # 兜底逻辑——那个兜底读的是 os.environ 全局账密（Phase 1 单用户遗留），
        # 多用户场景下用了会导致所有用户的睡眠请求都串到同一个 COROS 账号上。
        raise ValueError("token invalid: missing COROS mobile access token")

    sleep_records = await coros_client.get_sleep(auth, days=2)
    if not sleep_records:
        logger.info("morning_report: no sleep data, skipping")
        return None

    sleep = sleep_records[-1]
    sleep_date = sleep.date if hasattr(sleep, "date") else sleep.get("date", "")

    if await store.is_morning_report_sent(user.id, sleep_date):
        logger.info("morning_report: already sent for %s, skipping", sleep_date)
        return None

    hrv_records = await coros_client.get_hrv(auth)
    hrv = next((h for h in reversed(hrv_records) if h.date == sleep_date), None)
    if not hrv:
        logger.info("morning_report: no HRV data for %s yet, skipping", sleep_date)
        return None

    daily_ctx = await coros_client.get_recent_daily_records(auth, days=7)
    daily_dicts = [r.model_dump() for r in daily_ctx]

    sleep_dict = sleep.model_dump() if hasattr(sleep, "model_dump") else sleep
    hrv_dict = hrv.model_dump() if hasattr(hrv, "model_dump") else hrv

    return {
        "sleep_date": sleep_date,
        "sleep_dict": sleep_dict,
        "hrv_dict": hrv_dict,
        "daily_dicts": daily_dicts,
    }


async def process_morning_report(user: User, prepared: dict) -> None:
    try:
        report = analyzer.analyze_morning(
            prepared["sleep_dict"], prepared["hrv_dict"], prepared["daily_dicts"]
        )
        await store.mark_morning_report_sent(
            user.id, prepared["sleep_date"], prepared["sleep_dict"],
            prepared["hrv_dict"], prepared["daily_dicts"], report,
        )
        notifier.push(title="今日状态播报", body=report)
        logger.info("morning_report: pushed for %s", prepared["sleep_date"])

    except Exception as e:
        logger.error("process_morning_report job failed: %s", e)
        notifier.push(title="PaceCoach Error", body=f"晨报生成失败：{e}")


# ---------------------------------------------------------------------------
# 伤病风险预警
# ---------------------------------------------------------------------------

async def check_injury_risk(user: User, auth: StoredAuth) -> dict | None:
    """
    轻量检查：评估风险信号。返回 None 表示今天已经检测过，或者没有检测出风险
    （signals 计算是纯逻辑判断，不涉及 LLM，所以这一步本身就很快）。
    """
    check_date = date.today().strftime("%Y%m%d")

    if await store.is_risk_sent(user.id, check_date):
        logger.info("injury_risk_check: already checked for %s, skipping", check_date)
        return None

    daily_ctx = await coros_client.get_recent_daily_records(auth, days=14)
    daily_dicts = [r.model_dump() for r in daily_ctx]

    # 把 HRVRecord 的 standard_deviation 按日期合并进 daily_dicts
    # DailyRecord 拿不到 sd，HRVRecord 才有（来自 /dashboard/query）
    hrv_records = await coros_client.get_hrv(auth)
    hrv_sd_by_date = {
        r.date: r.standard_deviation
        for r in hrv_records
        if r.standard_deviation is not None
    }
    for d in daily_dicts:
        if d["date"] in hrv_sd_by_date:
            d["standard_deviation"] = hrv_sd_by_date[d["date"]]

    signals = assess_injury_risk(daily_dicts)
    if signals is None:
        logger.info("injury_risk_check: no risk detected for %s", check_date)
        return None

    logger.info("injury_risk_check: risk detected, signals=%s", signals)
    return {"check_date": check_date, "signals": signals, "daily_dicts": daily_dicts}


async def process_injury_risk(user: User, prepared: dict) -> None:
    try:
        report = analyzer.analyze_risk(prepared["signals"], prepared["daily_dicts"])
        await store.mark_risk_sent(user.id, prepared["check_date"], prepared["signals"], report)
        notifier.push(title="⚠️ 伤病风险预警", body=report)
        logger.info("injury_risk_check: pushed for %s", prepared["check_date"])

    except Exception as e:
        logger.error("process_injury_risk job failed: %s", e)
        notifier.push(title="PaceCoach Error", body=f"风险检测失败：{e}")


# ---------------------------------------------------------------------------
# 周报
# ---------------------------------------------------------------------------

async def check_weekly_report(user: User, auth: StoredAuth) -> dict | None:
    """
    检查 + 把 process 需要的全部数据一次性拉齐（跟晨报/风险预警一致的模式）：
    先判断本周是否已经推过（查库），没推过就把上周的每日记录、活动详情都
    从 COROS 拉好，process 阶段只做 LLM + 落库 + 推送，不再有任何 COROS 请求。
    返回 None 表示本周已经推送过。

    注意：即使本周没有任何训练，也应该照常生成周报（"这周没练"本身就是有效信息），
    所以这里不检查"有没有活动"，只检查"是否已推送过"。
    """
    today = date.today()
    # 找本周周一，再往前7天 = 上周周一，无论周几触发结果都一样
    this_monday = today - timedelta(days=today.weekday())
    week_start_dt = this_monday - timedelta(days=7)
    week_start = week_start_dt.strftime("%Y%m%d")
    week_end_dt = this_monday - timedelta(days=1)  # 上周周日

    if await store.is_weekly_report_sent(user.id, week_start):
        logger.info("weekly_report: already sent for week %s, skipping", week_start)
        return None

    daily_ctx = await coros_client.get_recent_daily_records(auth, start_date=week_start_dt, end_date=week_end_dt)
    daily_dicts = [r.model_dump() for r in daily_ctx]

    # 活动详情直接从 COROS API 拉，不依赖 run_logs（避免因用户没有及时
    # 手动触发练后点评导致数据缺失）
    activities = await coros_client.get_recent_activities(auth, start_date=week_start_dt, end_date=week_end_dt)
    sessions = []
    for act in activities:
        detail = await coros_client.get_activity_detail(auth, act.activity_id, act.sport_type or 0)
        s = detail.get("summary", {})
        weather = detail.get("weather", {})
        temp_raw = weather.get("temperature")
        hum_raw = weather.get("humidity")
        sessions.append({
            "train_type": s.get("trainType"),
            "distance_km": round(s.get("distance", 0) / 100000, 2),
            "training_load": s.get("trainingLoad", 0),
            "aerobic_effect": s.get("aerobicEffect"),
            "temp": round(temp_raw / 10, 1) if temp_raw else None,
            "humidity": round(hum_raw / 10, 1) if hum_raw else None,
        })

    logger.info("weekly_report: week=%s, sessions=%d", week_start, len(sessions))
    return {"week_start": week_start, "daily_dicts": daily_dicts, "sessions": sessions}


async def process_weekly_report(user: User, prepared: dict) -> None:
    """纯 LLM 分析 + 落库 + 推送，不再请求 COROS。prepared 由 check_weekly_report() 拉齐传入。"""
    try:
        week_start = prepared["week_start"]
        report = analyzer.analyze_weekly(prepared["daily_dicts"], prepared["sessions"], week_start)

        await store.mark_weekly_report_sent(
            user.id, week_start, prepared["daily_dicts"], prepared["sessions"], report
        )
        notifier.push(title="📊 本周训练周报", body=report)
        logger.info("weekly_report: pushed for week %s", week_start)

    except Exception as e:
        logger.error("process_weekly_report job failed: %s", e)
        notifier.push(title="PaceCoach Error", body=f"周报生成失败：{e}")
