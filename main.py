"""
Entry point.

Normal mode:  python main.py
              Starts BlockingScheduler, polls every POLL_INTERVAL_MINUTES.

One-shot mode: python main.py --once
               Runs on_new_activity() immediately and exits. Good for testing.
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
from src.jobs import on_new_activity, morning_report


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

    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()
    scheduler.add_job(
        on_new_activity,
        trigger="interval",
        minutes=settings.poll_interval_minutes,
        id="poll_activities",
    )

    # 晨报：和练后分析一样走轮询，检测到当天睡眠数据同步后才推，内部去重
    scheduler.add_job(
        morning_report,
        trigger="interval",
        minutes=settings.poll_interval_minutes,
        id="morning_report",
    )

    logger.info(f"Scheduler started. Polling every {settings.poll_interval_minutes} minutes.")
    scheduler.start()


if __name__ == "__main__":
    main()
