"""
Scheduler jobs.

on_new_activity(): active (v0) — polls for new workouts, triggers analysis + push
morning_report():  stubbed (v0.1) — activated after sleep data is available
"""
import logging

from src import coros_client, analyzer, notifier, store

logger = logging.getLogger(__name__)


def on_new_activity() -> None:
    try:
        activities = coros_client.get_recent_activities(days=3)
        # activities is a list of ActivitySummary pydantic objects
        new = [a for a in activities if not store.is_processed(a.activity_id)]

        for activity in new:
            activity_id = activity.activity_id
            sport_type = activity.sport_type or 0
            logger.info(f"Processing new activity: {activity_id} ({activity.sport_name})")

            try:
                detail = coros_client.get_activity_detail(activity_id, sport_type)
                daily_ctx = coros_client.get_recent_daily_records(days=14)

                # Convert pydantic objects to dicts for the analyzer prompt
                daily_dicts = [r.model_dump() for r in daily_ctx]

                coaching = analyzer.analyze_workout(detail, daily_dicts)

                store.save_run_log(activity_id, detail, daily_dicts, coaching)
                notifier.push(title="练后点评", body=coaching)
                store.mark_processed(activity_id)

                logger.info(f"Pushed coaching for activity {activity_id}")

            except Exception as e:
                logger.error(f"Failed to process activity {activity_id}: {e}")
                notifier.push(title="PaceCoach Error", body=f"活动 {activity_id} 处理失败：{e}")

    except Exception as e:
        logger.error(f"on_new_activity job failed: {e}")
        notifier.push(title="PaceCoach Error", body=f"轮询失败：{e}")


def morning_report() -> None:
    # v0.1 — 有睡眠数据后实现
    logger.info("morning_report: pending sleep data (v0.1), skipping")
