import logging

from fastapi import FastAPI

from api.errors import register_exception_handlers
from api.routes.auth import router as auth_router
from api.routes.feed import router as feed_router
from api.routes.health import router as health_router
from api.routes.jobs import router as jobs_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# 多用户模式下改为手动触发（App 端调用 /jobs/*，不再有全局定时轮询）：
# 自动轮询需要后端自己持有/刷新每个用户的 COROS 凭证，而 COROS 没有 OAuth，
# 只能靠代理登录，这会周期性踢掉用户手机端 COROS App，体验很差。
# 详见 docs/用户认证与COROS集成方案.md。
app = FastAPI(title="PaceCoach API", version="0.1.0")
register_exception_handlers(app)
app.include_router(health_router)
app.include_router(jobs_router, prefix="/jobs")
app.include_router(auth_router, prefix="/auth")
app.include_router(feed_router, prefix="/feed")
