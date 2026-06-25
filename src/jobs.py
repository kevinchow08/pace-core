"""
Scheduler jobs.

on_new_activity():    active — polls for new workouts, triggers analysis + push
morning_report():     active — daily morning broadcast (sleep + HRV + load)
injury_risk_check():  active — daily risk check, only pushes when ≥2 signals triggered
weekly_report():      active — Monday morning weekly summary
"""
import logging
from datetime import date, timedelta

from src import coros_client, analyzer, notifier, store
from src.risk import assess_injury_risk

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


async def on_new_activity() -> None:
    try:
        # days=4：覆盖数据同步延迟，同时避免拉太多历史数据
        activities = await coros_client.get_recent_activities(days=4)

        # 过滤：只保留含有至少一条未处理活动的训练课
        sessions = _group_into_sessions(activities)
        new_sessions = []
        for s in sessions:
            # any() 内部有 await，不能用列表推导式，必须显式 for 循环
            has_new = any([not await store.is_processed(a.activity_id) for a in s])
            if has_new:
                new_sessions.append(s)

        logger.info(f"Found {len(new_sessions)} new session(s) to process")

        # 14天背景数据：所有课共用一份，在循环外拉一次
        # 理由：COROS 数据不会在同一次 job 的几秒内发生变化，
        # 多次调用结果相同，只会浪费 API 请求
        daily_ctx = await coros_client.get_recent_daily_records(days=14)
        daily_dicts = [r.model_dump() for r in daily_ctx]

        for session in new_sessions:
            # 用本课第一条活动的 ID 作为这次推送的代表 ID（用于日志和存储）
            session_id = session[0].activity_id
            sport_names = [a.sport_name or "Unknown" for a in session]
            logger.info(f"Processing session {session_id}: {sport_names}")

            try:
                # 拉本课所有活动的详情
                details = []
                for activity in session:
                    detail = await coros_client.get_activity_detail(
                        activity.activity_id, activity.sport_type or 0
                    )
                    details.append(detail)

                # 整课一起分析，一条推送
                coaching = analyzer.analyze_workout(details, daily_dicts)

                await store.save_run_log(session_id, details, daily_dicts, coaching)
                notifier.push(title="练后点评", body=coaching)

                # 把本课所有活动都标记为已处理
                for activity in session:
                    await store.mark_processed(activity.activity_id)

                logger.info(f"Pushed coaching for session {session_id} ({len(session)} activities)")

            except Exception as e:
                logger.error(f"Failed to process session {session_id}: {e}")
                notifier.push(title="PaceCoach Error", body=f"训练课 {session_id} 处理失败：{e}")

    except Exception as e:
        logger.error(f"on_new_activity job failed: {e}")
        notifier.push(title="PaceCoach Error", body=f"轮询失败：{e}")


async def morning_report() -> None:
    """
    今日状态播报。

    触发逻辑：取最新一条睡眠记录，如果还没推过就推，推过就跳过。
    不补发历史日期——历史播报对当天决策没有意义。
    """
    try:
        sleep_records = await coros_client.get_sleep(days=2)
        if not sleep_records:
            logger.info("morning_report: no sleep data, skipping")
            return

        sleep = sleep_records[-1]
        sleep_date = sleep.date if hasattr(sleep, "date") else sleep.get("date", "")

        if await store.is_morning_report_sent(sleep_date):
            logger.info("morning_report: already sent for %s, skipping", sleep_date)
            return

        hrv_records = await coros_client.get_hrv()
        hrv = next((h for h in reversed(hrv_records) if h.date == sleep_date), None)
        if not hrv:
            logger.info("morning_report: no HRV data for %s yet, skipping", sleep_date)
            return

        daily_ctx = await coros_client.get_recent_daily_records(days=7)
        daily_dicts = [r.model_dump() for r in daily_ctx]

        sleep_dict = sleep.model_dump() if hasattr(sleep, "model_dump") else sleep
        hrv_dict = hrv.model_dump() if hasattr(hrv, "model_dump") else hrv

        report = analyzer.analyze_morning(sleep_dict, hrv_dict, daily_dicts)

        await store.mark_morning_report_sent(sleep_date, sleep_dict, hrv_dict, daily_dicts, report)
        notifier.push(title="今日状态播报", body=report)
        logger.info("morning_report: pushed for %s", sleep_date)

    except Exception as e:
        logger.error("morning_report job failed: %s", e)
        notifier.push(title="PaceCoach Error", body=f"晨报生成失败：{e}")


async def injury_risk_check() -> None:
    """
    每日伤病风险检测。拉取近14天数据，评估风险信号。
    有风险（≥2个信号）才推送，同一天不重复推。
    """
    try:
        check_date = date.today().strftime("%Y%m%d")

        if await store.is_risk_sent(check_date):
            logger.info("injury_risk_check: already checked for %s, skipping", check_date)
            return

        daily_ctx = await coros_client.get_recent_daily_records(days=14)
        daily_dicts = [r.model_dump() for r in daily_ctx]

        # 把 HRVRecord 的 standard_deviation 按日期合并进 daily_dicts
        # DailyRecord 拿不到 sd，HRVRecord 才有（来自 /dashboard/query）
        hrv_records = await coros_client.get_hrv()
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
            return

        logger.info("injury_risk_check: risk detected, signals=%s", signals)
        report = analyzer.analyze_risk(signals, daily_dicts)

        await store.mark_risk_sent(check_date, signals, report)
        notifier.push(title="⚠️ 伤病风险预警", body=report)
        logger.info("injury_risk_check: pushed for %s", check_date)

    except Exception as e:
        logger.error("injury_risk_check job failed: %s", e)
        notifier.push(title="PaceCoach Error", body=f"风险检测失败：{e}")


async def weekly_report() -> None:
    """
    每周一推送上周训练周报。
    数据来源：
    - get_recent_daily_records(start_date, end_date)：上周一到周日身体状态
    - get_recent_activities(start_date, end_date) + get_activity_detail()：直接从 COROS API 拉，
      不依赖 run_logs（避免因后端未及时轮询导致数据缺失）
    同一周不重复推。
    """
    try:
        today = date.today()
        # 找本周周一，再往前7天 = 上周周一，无论周几触发结果都一样
        this_monday = today - timedelta(days=today.weekday())
        week_start_dt = this_monday - timedelta(days=7)
        week_start = week_start_dt.strftime("%Y%m%d")

        if await store.is_weekly_report_sent(week_start):
            logger.info("weekly_report: already sent for week %s, skipping", week_start)
            return

        week_end_dt = this_monday - timedelta(days=1)  # 上周周日

        daily_ctx = await coros_client.get_recent_daily_records(start_date=week_start_dt, end_date=week_end_dt)
        daily_dicts = [r.model_dump() for r in daily_ctx]

        activities = await coros_client.get_recent_activities(start_date=week_start_dt, end_date=week_end_dt)
        sessions = []
        for act in activities:
            detail = await coros_client.get_activity_detail(act.activity_id, act.sport_type or 0)
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
        report = analyzer.analyze_weekly(daily_dicts, sessions, week_start)

        await store.mark_weekly_report_sent(week_start, daily_dicts, sessions, report)
        notifier.push(title="📊 本周训练周报", body=report)
        logger.info("weekly_report: pushed for week %s", week_start)

    except Exception as e:
        logger.error("weekly_report job failed: %s", e)
        notifier.push(title="PaceCoach Error", body=f"周报生成失败：{e}")
