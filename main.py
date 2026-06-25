"""
调试用命令行入口。

python main.py --once      运行练后分析
python main.py --morning   运行晨报
python main.py --risk      运行伤病风险检测
python main.py --weekly    运行周报（上周数据）

正常运行走 uvicorn api.main:app，定时任务在 api/main.py 的 lifespan 中管理。
"""
import asyncio
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

from src import store
from src.jobs import on_new_activity, morning_report, injury_risk_check, weekly_report


async def main():
    await store.init_db()

    if "--once" in sys.argv:
        logger.info("--once mode: running on_new_activity and exiting")
        await on_new_activity()
    elif "--morning" in sys.argv:
        logger.info("--morning mode: running morning_report and exiting")
        await morning_report()
    elif "--risk" in sys.argv:
        logger.info("--risk mode: running injury_risk_check and exiting")
        await injury_risk_check()
    elif "--weekly" in sys.argv:
        logger.info("--weekly mode: running weekly_report and exiting")
        await weekly_report()
    else:
        logger.error("请指定 --once / --morning / --risk / --weekly")


if __name__ == "__main__":
    asyncio.run(main())
