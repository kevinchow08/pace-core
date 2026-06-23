import logging

from fastapi import FastAPI
from api.routes.health import router as health_router
from api.routes.jobs import router as jobs_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="PaceCoach API", version="0.1.0")

app.include_router(health_router)
app.include_router(jobs_router, prefix="/jobs")
