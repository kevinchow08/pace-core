"""
Entry point.

Normal mode:   python main.py
               Starts BlockingScheduler, polls every POLL_INTERVAL_MINUTES.

One-shot mode: python main.py --once      运行练后分析
               python main.py --morning   运行晨报
               python main.py --risk      运行伤病风险检测
               python main.py --weekly    运行周报（上周数据）
"""
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

from src import store
from src.config import settings
from src.jobs import on_new_activity, morning_report, injury_risk_check, weekly_report


def main():
    store.init_db()

    if "--once" in sys.argv:
        logger.info("--once mode: running on_new_activity and exiting")
        on_new_activity()
        return

    if "--morning" in sys.argv:
        logger.info("--morning mode: running morning_report and exiting")
        morning_report()
        return

    if "--risk" in sys.argv:
        logger.info("--risk mode: running injury_risk_check and exiting")
        injury_risk_check()
        return

    if "--weekly" in sys.argv:
        logger.info("--weekly mode: running weekly_report and exiting")
        weekly_report()
        return

    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()
    scheduler.add_job(
        on_new_activity,
        trigger="interval",
        minutes=settings.poll_interval_minutes,
        id="poll_activities",
    )
    scheduler.add_job(
        morning_report,
        trigger="interval",
        minutes=settings.poll_interval_minutes,
        id="morning_report",
    )
    scheduler.add_job(
        injury_risk_check,
        trigger="interval",
        minutes=settings.poll_interval_minutes,
        id="injury_risk_check",
    )
    # 周报：每周一早上8点触发（day_of_week=0 = 周一）
    scheduler.add_job(
        weekly_report,
        trigger="cron",
        day_of_week=0,
        hour=8,
        minute=0,
        id="weekly_report",
    )

    logger.info(f"Scheduler started. Polling every {settings.poll_interval_minutes} minutes.")
    scheduler.start()


if __name__ == "__main__":
    main()
