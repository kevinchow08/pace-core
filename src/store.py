"""
SQLite-backed store for deduplication and raw response logging.

Two tables:
- ProcessedActivity: tracks which activity IDs have already been pushed
- RunLog: raw API responses, useful for debugging when COROS changes their API
"""
import json
from datetime import datetime

from sqlalchemy import create_engine, Column, String, DateTime, Text
from sqlalchemy.orm import DeclarativeBase, Session

from src.config import settings


engine = create_engine(settings.db_url)


class Base(DeclarativeBase):
    pass


class ProcessedActivity(Base):
    __tablename__ = "processed_activities"

    label_id = Column(String, primary_key=True)
    processed_at = Column(DateTime, default=datetime.utcnow)


class RunLog(Base):
    __tablename__ = "run_logs"

    id = Column(String, primary_key=True)  # label_id
    raw_activity = Column(Text)
    raw_daily = Column(Text)
    coaching = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(engine)


def is_processed(label_id: str) -> bool:
    with Session(engine) as session:
        return session.get(ProcessedActivity, label_id) is not None


def mark_processed(label_id: str):
    with Session(engine) as session:
        session.add(ProcessedActivity(label_id=label_id))
        session.commit()


def save_run_log(label_id: str, activity: dict, daily: dict, coaching: str):
    with Session(engine) as session:
        log = RunLog(
            id=label_id,
            raw_activity=json.dumps(activity, ensure_ascii=False),
            raw_daily=json.dumps(daily, ensure_ascii=False),
            coaching=coaching,
        )
        session.merge(log)
        session.commit()
