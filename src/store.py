"""
SQLite-backed store for deduplication and raw response logging.

Two tables:
- ProcessedActivity: tracks which activity IDs have already been pushed
- RunLog: raw API responses, useful for debugging when COROS changes their API
"""
import json
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from src.config import settings


engine = create_engine(settings.db_url)


class Base(DeclarativeBase):
    # SQLAlchemy reads ORM models from this base class and its metadata.
    pass


class ProcessedActivity(Base):
    __tablename__ = "processed_activities"

    # COROS labelId is the natural primary key for dedupe.
    label_id = Column(String, primary_key=True)
    # Filled when the row is created; used for auditing when we marked it processed.
    processed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RunLog(Base):
    __tablename__ = "run_logs"

    # Reuse labelId as the row identity so repeated writes can overwrite the same row.
    id = Column(String, primary_key=True)  # label_id
    # Store raw payloads as JSON text for debugging and replay.
    raw_activity = Column(Text)
    raw_daily = Column(Text)
    coaching = Column(Text)
    # Lets us inspect when the log row was written.
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def init_db():
    # Create tables that do not exist yet from the ORM metadata.
    # This is a bootstrap step, not a schema migration tool.
    Base.metadata.create_all(engine)


def is_processed(label_id: str) -> bool:
    # Each call opens a short-lived session, does one lookup, and closes it.
    with Session(engine) as session:
        return session.get(ProcessedActivity, label_id) is not None


def mark_processed(label_id: str):
    # add()：只能插入新记录，主键冲突直接报错（IntegrityError）
    # 语义是"这条记录必须是第一次写入"，比静默覆盖更严格，能暴露重复调用的 bug
    with Session(engine) as session:
        session.add(ProcessedActivity(label_id=label_id))
        session.commit()


def save_run_log(label_id: str, activity: dict, daily: dict, coaching: str):
    # merge()：主键存在则更新，不存在则插入（upsert）
    # 同一活动因失败重跑时需要覆盖旧记录，所以用 merge 而不是 add
    with Session(engine) as session:
        log = RunLog(
            id=label_id,
            raw_activity=json.dumps(activity, ensure_ascii=False),
            raw_daily=json.dumps(daily, ensure_ascii=False),
            coaching=coaching,
        )
        session.merge(log)
        session.commit()
