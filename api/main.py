import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from api.errors import register_exception_handlers
from api.routes.health import router as health_router
from api.routes.jobs import router as jobs_router
from src.config import settings
from src.jobs import on_new_activity, morning_report, injury_risk_check, weekly_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler()
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
    scheduler.start()

    yield  # 应用正常运行中，HTTP 请求在这里处理，定时任务在后台跑

    # 收到 SIGTERM（docker stop / Ctrl+C）时执行到这里
    # 等当前正在跑的 job 跑完再退出，避免数据库写到一半被强杀（优雅关闭）
    scheduler.shutdown()


app = FastAPI(title="PaceCoach API", version="0.1.0", lifespan=lifespan)
register_exception_handlers(app)
app.include_router(health_router)
app.include_router(jobs_router, prefix="/jobs")
