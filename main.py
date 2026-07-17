"""
调试用命令行入口。

python main.py --once      运行练后分析
python main.py --morning   运行晨报
python main.py --risk      运行伤病风险检测
python main.py --weekly    运行周报（上周数据）

多用户模式下业务拆成 check_*（同步检查）+ process_*（真正分析+推送）两段，
这里用 .env 里的 COROS_EMAIL/COROS_PASSWORD 走一次真实登录，本地调试用，
模拟 App 端登录后把 token 转交给后端的过程。

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
from src import jobs
from src.store import get_or_create_user


async def main():
    # skip_mobile=False：本地调试也要真实获取 mobile token，
    # 不然 --morning 会静默落进 coros_lib 内部读 os.environ 账密的兜底逻辑，
    # 意外掩盖"多用户场景下 mobile token 缺失"这个真实 bug（掉进这个坑过一次）
    auth = await coros_login(
        settings.coros_email, settings.coros_password, settings.coros_region, skip_mobile=False
    )
    user = await get_or_create_user(auth.user_id, settings.coros_email)

    if "--once" in sys.argv:
        prepared = await jobs.check_new_activity(user, auth)
        if prepared is None:
            logger.info("--once mode: no new sessions, nothing to do")
            return
        logger.info("--once mode: %d new session(s), processing", len(prepared))
        await jobs.process_new_activity(user, prepared)

    elif "--morning" in sys.argv:
        prepared = await jobs.check_morning_report(user, auth)
        if prepared is None:
            logger.info("--morning mode: nothing to report")
            return
        logger.info("--morning mode: processing")
        await jobs.process_morning_report(user, prepared)

    elif "--risk" in sys.argv:
        prepared = await jobs.check_injury_risk(user, auth)
        if prepared is None:
            logger.info("--risk mode: no risk detected or already checked today")
            return
        logger.info("--risk mode: processing")
        await jobs.process_injury_risk(user, prepared)

    elif "--weekly" in sys.argv:
        prepared = await jobs.check_weekly_report(user, auth)
        if prepared is None:
            logger.info("--weekly mode: already sent this week")
            return
        logger.info("--weekly mode: processing")
        await jobs.process_weekly_report(user, prepared)

    else:
        logger.error("请指定 --once / --morning / --risk / --weekly")


if __name__ == "__main__":
    asyncio.run(main())
