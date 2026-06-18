"""
SQLite-backed store for deduplication and raw response logging.

Three tables:
- ProcessedActivity: one row per activity ID (individual COROS labelId), used for dedupe
- RunLog: one row per training session (keyed by first activity's labelId), stores coaching result
- MorningLog: one row per sleep date, stores morning broadcast result
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


class MorningLog(Base):
    __tablename__ = "morning_logs"

    sleep_date = Column(String, primary_key=True)  # yyyyMMdd，睡眠所属日期
    raw_sleep = Column(Text)
    raw_hrv = Column(Text)
    raw_daily = Column(Text)
    report = Column(Text)
    sent_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RiskLog(Base):
    __tablename__ = "risk_logs"

    check_date = Column(String, primary_key=True)  # yyyyMMdd，检测日期，同一天只推一次
    signals = Column(Text)   # 触发的风险信号（JSON 列表）
    report = Column(Text)    # LLM 生成的预警内容
    sent_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


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


def is_morning_report_sent(sleep_date: str) -> bool:
    with Session(engine) as session:
        return session.get(MorningLog, sleep_date) is not None


def mark_morning_report_sent(sleep_date: str, sleep: dict, hrv: dict, daily: list, report: str):
    with Session(engine) as session:
        # merge()：主键存在则覆盖，不存在则插入；重跑时安全覆盖旧记录
        session.merge(MorningLog(
            sleep_date=sleep_date,
            raw_sleep=json.dumps(sleep, ensure_ascii=False),
            raw_hrv=json.dumps(hrv, ensure_ascii=False),
            raw_daily=json.dumps(daily, ensure_ascii=False),
            report=report,
        ))
        session.commit()


def is_risk_sent(check_date: str) -> bool:
    with Session(engine) as session:
        return session.get(RiskLog, check_date) is not None


def mark_risk_sent(check_date: str, signals: list, report: str):
    with Session(engine) as session:
        # merge()：主键存在则覆盖，不存在则插入；重跑时安全覆盖旧记录
        session.merge(RiskLog(
            check_date=check_date,
            signals=json.dumps(signals, ensure_ascii=False),
            report=report,
        ))
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
