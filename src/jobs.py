"""
Scheduler jobs.

on_new_activity(): active (v0) — polls for new workouts, triggers analysis + push
morning_report():  stubbed (v0.1) — activated after sleep data is available
"""
import logging

from src import coros_client, analyzer, notifier, store

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


def on_new_activity() -> None:
    try:
        # days=2：覆盖数据同步延迟，同时避免拉太多历史数据
        activities = coros_client.get_recent_activities(days=2)

        # 过滤：只保留含有至少一条未处理活动的训练课
        sessions = _group_into_sessions(activities)
        new_sessions = [
            s for s in sessions
            if any(not store.is_processed(a.activity_id) for a in s)
        ]

        logger.info(f"Found {len(new_sessions)} new session(s) to process")

        # 14天背景数据：所有课共用一份，在循环外拉一次
        # 理由：COROS 数据不会在同一次 job 的几秒内发生变化，
        # 多次调用结果相同，只会浪费 API 请求
        daily_ctx = coros_client.get_recent_daily_records(days=14)
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
                    detail = coros_client.get_activity_detail(
                        activity.activity_id, activity.sport_type or 0
                    )
                    details.append(detail)

                # 整课一起分析，一条推送
                coaching = analyzer.analyze_workout(details, daily_dicts)

                store.save_run_log(session_id, details, daily_dicts, coaching)
                notifier.push(title="练后点评", body=coaching)

                # 把本课所有活动都标记为已处理
                for activity in session:
                    store.mark_processed(activity.activity_id)

                logger.info(f"Pushed coaching for session {session_id} ({len(session)} activities)")

            except Exception as e:
                logger.error(f"Failed to process session {session_id}: {e}")
                notifier.push(title="PaceCoach Error", body=f"训练课 {session_id} 处理失败：{e}")

    except Exception as e:
        logger.error(f"on_new_activity job failed: {e}")
        notifier.push(title="PaceCoach Error", body=f"轮询失败：{e}")


def morning_report() -> None:
    # v0.1 — 有睡眠数据后实现
    logger.info("morning_report: pending sleep data (v0.1), skipping")
