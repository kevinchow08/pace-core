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
from src.jobs import on_new_activity


def main():
    store.init_db()

    if "--once" in sys.argv:
        logger.info("--once mode: running on_new_activity and exiting")
        on_new_activity()
        return

    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()
    scheduler.add_job(
        on_new_activity,
        trigger="interval",
        minutes=settings.poll_interval_minutes,
        id="poll_activities",
    )

    # v0.1: morning_report job — uncomment when sleep data is available
    # from src.jobs import morning_report
    # scheduler.add_job(morning_report, trigger="cron", hour=7, minute=30, id="morning_report")

    logger.info(f"Scheduler started. Polling every {settings.poll_interval_minutes} minutes.")
    scheduler.start()


if __name__ == "__main__":
    main()
