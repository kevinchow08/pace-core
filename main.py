"""
调试用命令行入口。

python main.py --once      运行练后分析
python main.py --morning   运行晨报
python main.py --risk      运行伤病风险检测
python main.py --weekly    运行周报（上周数据）

多用户模式下业务 job 需要 (user, auth) 两个参数，这里用 .env 里的
COROS_EMAIL/COROS_PASSWORD 走一次真实登录，本地调试用，模拟 App 端登录后
把 token 转交给后端的过程。

正常运行走 uvicorn api.main:app，由 API 路由接收 App 请求后调用 job。
"""
import asyncio
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

from coros_lib.coros_api import login as coros_login
from src.config import settings
from src.jobs import on_new_activity, morning_report, injury_risk_check, weekly_report
from src.store import get_or_create_user


async def main():
    auth = await coros_login(settings.coros_email, settings.coros_password, settings.coros_region)
    user = await get_or_create_user(auth.user_id, settings.coros_email)

    if "--once" in sys.argv:
        logger.info("--once mode: running on_new_activity and exiting")
        await on_new_activity(user, auth)
    elif "--morning" in sys.argv:
        logger.info("--morning mode: running morning_report and exiting")
        await morning_report(user, auth)
    elif "--risk" in sys.argv:
        logger.info("--risk mode: running injury_risk_check and exiting")
        await injury_risk_check(user, auth)
    elif "--weekly" in sys.argv:
        logger.info("--weekly mode: running weekly_report and exiting")
        await weekly_report(user, auth)
    else:
        logger.error("请指定 --once / --morning / --risk / --weekly")


if __name__ == "__main__":
    asyncio.run(main())
